// Copyright (c) 2026 and onwards The McBopomofo Authors.

#include "NeuralTFPathScorer.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>

namespace iBopomofo {

namespace {

bool readExact(std::ifstream& in, void* dst, size_t n) {
  in.read(reinterpret_cast<char*>(dst), static_cast<std::streamsize>(n));
  return static_cast<size_t>(in.gcount()) == n;
}

// PyTorch Linear: y = x @ W.T + b with W stored [out, in].
// We store W as [out, in] row-major (same as state_dict).
inline void linearOutIn(const float* x, const float* W, const float* b,
                        int outDim, int inDim, float* y) {
  for (int o = 0; o < outDim; ++o) {
    float s = b ? b[o] : 0.f;
    const float* row = W + static_cast<size_t>(o) * static_cast<size_t>(inDim);
    for (int i = 0; i < inDim; ++i) s += row[i] * x[i];
    y[o] = s;
  }
}

// For exported FFN W1 as [D, FFN] meaning y = x @ W1 (W1 columns = out).
// Stored row-major W1[i, j] i in D, j in FFN → index i*FFN+j
inline void linearDinFout(const float* x, const float* W, const float* b, int D,
                          int F, float* y) {
  for (int j = 0; j < F; ++j) {
    float s = b ? b[j] : 0.f;
    for (int i = 0; i < D; ++i) s += x[i] * W[static_cast<size_t>(i) * F + j];
    y[j] = s;
  }
}

// W2 [FFN, D] row-major for y = h @ W2
inline void linearFinDout(const float* x, const float* W, const float* b, int F,
                          int D, float* y) {
  for (int j = 0; j < D; ++j) {
    float s = b ? b[j] : 0.f;
    for (int i = 0; i < F; ++i)
      s += x[i] * W[static_cast<size_t>(i) * D + j];
    y[j] = s;
  }
}

}  // namespace

bool NeuralTFPathScorer::load(const std::string& path) {
  loaded_ = false;
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;

  char magic[8];
  if (!readExact(in, magic, 8) || std::memcmp(magic, "LWTFMR1\0", 8) != 0) {
    return false;
  }
  if (!readExact(in, &dModel_, 4) || !readExact(in, &nHead_, 4) ||
      !readExact(in, &nLayer_, 4) || !readExact(in, &ffn_, 4) ||
      !readExact(in, &maxCtx_, 4) || !readExact(in, &vocab_, 4)) {
    return false;
  }
  if (dModel_ <= 0 || nHead_ <= 0 || nLayer_ <= 0 || ffn_ <= 0 || maxCtx_ <= 0 ||
      vocab_ <= 4 || dModel_ % nHead_ != 0 || nLayer_ > 16) {
    return false;
  }

  itos_.assign(static_cast<size_t>(vocab_), "");
  stoi_.clear();
  for (int i = 0; i < vocab_; ++i) {
    int16_t len = 0;
    if (!readExact(in, &len, 2) || len < 0) return false;
    std::string s(static_cast<size_t>(len), '\0');
    if (len > 0 && !readExact(in, s.data(), static_cast<size_t>(len))) {
      return false;
    }
    itos_[static_cast<size_t>(i)] = s;
    if (!s.empty()) stoi_[s] = i;
  }
  unk_id_ = stoi_.count("<unk>") ? stoi_["<unk>"] : 1;
  bos_id_ = stoi_.count("<s>") ? stoi_["<s>"] : 2;
  eos_id_ = stoi_.count("</s>") ? stoi_["</s>"] : 3;

  auto readF = [&](std::vector<float>& v, size_t n) -> bool {
    v.resize(n);
    return readExact(in, v.data(), n * sizeof(float));
  };

  const int D = dModel_;
  const int F = ffn_;
  if (!readF(emb_, static_cast<size_t>(vocab_) * D) ||
      !readF(pos_, static_cast<size_t>(maxCtx_) * D)) {
    return false;
  }

  layers_.assign(static_cast<size_t>(nLayer_), {});
  for (int li = 0; li < nLayer_; ++li) {
    Layer& L = layers_[static_cast<size_t>(li)];
    if (!readF(L.ln1_w, D) || !readF(L.ln1_b, D)) return false;
    if (!readF(L.Wq, static_cast<size_t>(D) * D) ||
        !readF(L.Wk, static_cast<size_t>(D) * D) ||
        !readF(L.Wv, static_cast<size_t>(D) * D) ||
        !readF(L.Wo, static_cast<size_t>(D) * D)) {
      return false;
    }
    if (!readF(L.bq, D) || !readF(L.bk, D) || !readF(L.bv, D) ||
        !readF(L.bo, D)) {
      return false;
    }
    if (!readF(L.ln2_w, D) || !readF(L.ln2_b, D)) return false;
    if (!readF(L.W1, static_cast<size_t>(D) * F) || !readF(L.b1, F) ||
        !readF(L.W2, static_cast<size_t>(F) * D) || !readF(L.b2, D)) {
      return false;
    }
  }
  if (!readF(ln_f_w_, D) || !readF(ln_f_b_, D)) return false;
  if (!readF(lm_w_, static_cast<size_t>(vocab_) * D) ||
      !readF(lm_b_, static_cast<size_t>(vocab_))) {
    return false;
  }

  loaded_ = true;
  return true;
}

size_t NeuralTFPathScorer::parameterCount() const {
  if (!loaded_) return 0;
  size_t n = emb_.size() + pos_.size() + ln_f_w_.size() + ln_f_b_.size() +
             lm_w_.size() + lm_b_.size();
  for (const auto& L : layers_) {
    n += L.ln1_w.size() + L.ln1_b.size();
    n += L.Wq.size() + L.Wk.size() + L.Wv.size() + L.Wo.size();
    n += L.bq.size() + L.bk.size() + L.bv.size() + L.bo.size();
    n += L.ln2_w.size() + L.ln2_b.size();
    n += L.W1.size() + L.b1.size() + L.W2.size() + L.b2.size();
  }
  return n;
}

std::vector<std::string> NeuralTFPathScorer::flattenChars(
    const std::vector<std::string>& words) {
  std::vector<std::string> chars;
  for (const auto& w : words) {
    size_t i = 0;
    while (i < w.size()) {
      unsigned char c = static_cast<unsigned char>(w[i]);
      size_t len = 1;
      if ((c & 0x80) == 0)
        len = 1;
      else if ((c & 0xE0) == 0xC0)
        len = 2;
      else if ((c & 0xF0) == 0xE0)
        len = 3;
      else if ((c & 0xF8) == 0xF0)
        len = 4;
      if (i + len > w.size()) len = 1;
      chars.push_back(w.substr(i, len));
      i += len;
    }
  }
  return chars;
}

void NeuralTFPathScorer::layerNorm(const float* x, const float* w,
                                   const float* b, int D, float* out) {
  float mean = 0.f;
  for (int i = 0; i < D; ++i) mean += x[i];
  mean /= static_cast<float>(D);
  float var = 0.f;
  for (int i = 0; i < D; ++i) {
    float d = x[i] - mean;
    var += d * d;
  }
  var /= static_cast<float>(D);
  float inv = 1.f / std::sqrt(var + 1e-5f);
  for (int i = 0; i < D; ++i) {
    out[i] = (x[i] - mean) * inv * w[i] + b[i];
  }
}

void NeuralTFPathScorer::gelu(float* x, int n) {
  // tanh approximation of GELU
  for (int i = 0; i < n; ++i) {
    float v = x[i];
    float u = 0.7978845608f * (v + 0.044715f * v * v * v);
    x[i] = 0.5f * v * (1.f + std::tanh(u));
  }
}

void NeuralTFPathScorer::attnBlock(const Layer& L, const float* x, int T,
                                   float* y) const {
  const int D = dModel_;
  const int H = nHead_;
  const int hd = D / H;
  // x,y: [T, D]
  std::vector<float> xn(static_cast<size_t>(T) * D);
  for (int t = 0; t < T; ++t) {
    layerNorm(x + t * D, L.ln1_w.data(), L.ln1_b.data(), D, xn.data() + t * D);
  }

  std::vector<float> Q(static_cast<size_t>(T) * D);
  std::vector<float> K(static_cast<size_t>(T) * D);
  std::vector<float> V(static_cast<size_t>(T) * D);
  for (int t = 0; t < T; ++t) {
    linearOutIn(xn.data() + t * D, L.Wq.data(), L.bq.data(), D, D,
                Q.data() + t * D);
    linearOutIn(xn.data() + t * D, L.Wk.data(), L.bk.data(), D, D,
                K.data() + t * D);
    linearOutIn(xn.data() + t * D, L.Wv.data(), L.bv.data(), D, D,
                V.data() + t * D);
  }

  std::vector<float> ctx(static_cast<size_t>(T) * D, 0.f);
  const float scale = 1.f / std::sqrt(static_cast<float>(hd));

  for (int h = 0; h < H; ++h) {
    for (int t = 0; t < T; ++t) {
      // scores over s=0..t
      std::vector<float> scores(static_cast<size_t>(t + 1));
      float maxv = -1e30f;
      for (int s = 0; s <= t; ++s) {
        float dot = 0.f;
        const float* q = Q.data() + t * D + h * hd;
        const float* k = K.data() + s * D + h * hd;
        for (int i = 0; i < hd; ++i) dot += q[i] * k[i];
        scores[static_cast<size_t>(s)] = dot * scale;
        if (scores[static_cast<size_t>(s)] > maxv)
          maxv = scores[static_cast<size_t>(s)];
      }
      float sum = 0.f;
      for (int s = 0; s <= t; ++s) {
        scores[static_cast<size_t>(s)] =
            std::exp(scores[static_cast<size_t>(s)] - maxv);
        sum += scores[static_cast<size_t>(s)];
      }
      for (int s = 0; s <= t; ++s)
        scores[static_cast<size_t>(s)] /= sum;
      float* out = ctx.data() + t * D + h * hd;
      for (int i = 0; i < hd; ++i) out[i] = 0.f;
      for (int s = 0; s <= t; ++s) {
        const float* v = V.data() + s * D + h * hd;
        float a = scores[static_cast<size_t>(s)];
        for (int i = 0; i < hd; ++i) out[i] += a * v[i];
      }
    }
  }

  // out proj + residual
  for (int t = 0; t < T; ++t) {
    float proj[512];
    // D can be up to 512 in our configs; use heap if larger
    std::vector<float> pbuf(static_cast<size_t>(D));
    linearOutIn(ctx.data() + t * D, L.Wo.data(), L.bo.data(), D, D, pbuf.data());
    const float* xin = x + t * D;
    float* yout = y + t * D;
    for (int i = 0; i < D; ++i) yout[i] = xin[i] + pbuf[static_cast<size_t>(i)];
  }
}

void NeuralTFPathScorer::ffnBlock(const Layer& L, const float* x, int T,
                                  float* y) const {
  const int D = dModel_;
  const int F = ffn_;
  std::vector<float> xn(static_cast<size_t>(T) * D);
  for (int t = 0; t < T; ++t) {
    layerNorm(x + t * D, L.ln2_w.data(), L.ln2_b.data(), D, xn.data() + t * D);
  }
  std::vector<float> h(static_cast<size_t>(F));
  std::vector<float> o(static_cast<size_t>(D));
  for (int t = 0; t < T; ++t) {
    linearDinFout(xn.data() + t * D, L.W1.data(), L.b1.data(), D, F, h.data());
    gelu(h.data(), F);
    linearFinDout(h.data(), L.W2.data(), L.b2.data(), F, D, o.data());
    const float* xin = x + t * D;
    float* yout = y + t * D;
    for (int i = 0; i < D; ++i) yout[i] = xin[i] + o[static_cast<size_t>(i)];
  }
}

double NeuralTFPathScorer::scoreSentence(
    const std::vector<std::string>& words) {
  if (!loaded_ || words.empty()) return 0.0;
  auto chars = flattenChars(words);
  if (chars.empty()) return 0.0;

  std::vector<int> ids;
  ids.push_back(bos_id_);
  for (const auto& ch : chars) {
    auto it = stoi_.find(ch);
    ids.push_back(it == stoi_.end() ? unk_id_ : it->second);
  }
  ids.push_back(eos_id_);

  // One forward over full sequence (truncate left if > maxCtx).
  // At position t we read logits for target ids[t+1] (teacher-forced).
  const int D = dModel_;
  int fullT = static_cast<int>(ids.size());
  int start = 0;
  int T = fullT;
  if (T > maxCtx_) {
    start = T - maxCtx_;
    T = maxCtx_;
  }

  std::vector<float> h(static_cast<size_t>(T) * D);
  for (int i = 0; i < T; ++i) {
    int id = ids[static_cast<size_t>(start + i)];
    if (id < 0 || id >= vocab_) id = unk_id_;
    const float* e = emb_.data() + static_cast<size_t>(id) * D;
    const float* p = pos_.data() + static_cast<size_t>(i) * D;
    float* out = h.data() + static_cast<size_t>(i) * D;
    for (int j = 0; j < D; ++j) out[j] = e[j] + p[j];
  }
  std::vector<float> h2(static_cast<size_t>(T) * D);
  for (int li = 0; li < nLayer_; ++li) {
    attnBlock(layers_[static_cast<size_t>(li)], h.data(), T, h2.data());
    ffnBlock(layers_[static_cast<size_t>(li)], h2.data(), T, h.data());
  }
  // final LN all positions
  std::vector<float> hn(static_cast<size_t>(T) * D);
  for (int t = 0; t < T; ++t) {
    layerNorm(h.data() + static_cast<size_t>(t) * D, ln_f_w_.data(),
              ln_f_b_.data(), D, hn.data() + static_cast<size_t>(t) * D);
  }

  double log10e = 1.0 / std::log(10.0);
  double sumLog10 = 0.0;
  int scored = 0;
  // Score next-token for each position except last (no next after EOS input)
  // When truncated, first window position may not score earliest tokens — acceptable
  // for long rare cases; tw538 sentences are short.
  for (int t = 0; t + 1 < T; ++t) {
    const float* last = hn.data() + static_cast<size_t>(t) * D;
    std::vector<float> logits(static_cast<size_t>(vocab_));
    float maxv = -1e30f;
    for (int v = 0; v < vocab_; ++v) {
      float s = lm_b_[static_cast<size_t>(v)];
      const float* w = lm_w_.data() + static_cast<size_t>(v) * D;
      for (int j = 0; j < D; ++j) s += w[j] * last[j];
      logits[static_cast<size_t>(v)] = s;
      if (s > maxv) maxv = s;
    }
    double sumExp = 0.0;
    for (int v = 0; v < vocab_; ++v) {
      sumExp +=
          std::exp(static_cast<double>(logits[static_cast<size_t>(v)] - maxv));
    }
    int target = ids[static_cast<size_t>(start + t + 1)];
    if (target < 0 || target >= vocab_) target = unk_id_;
    double logp =
        static_cast<double>(logits[static_cast<size_t>(target)] - maxv) -
        std::log(sumExp);
    sumLog10 += logp * log10e;
    ++scored;
  }
  return scored > 0 ? sumLog10 : 0.0;
}

}  // namespace iBopomofo
