// Copyright (c) 2026 and onwards The McBopomofo Authors.

#include "NeuralLMPathScorer.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <numeric>

namespace McBopomofo {

namespace {

inline float sigmoid(float x) {
  if (x > 20.f) return 1.f;
  if (x < -20.f) return 0.f;
  return 1.f / (1.f + std::exp(-x));
}

inline float tanh_approx(float x) { return std::tanh(x); }

bool readExact(std::ifstream& in, void* dst, size_t n) {
  in.read(reinterpret_cast<char*>(dst), static_cast<std::streamsize>(n));
  return static_cast<size_t>(in.gcount()) == n;
}

}  // namespace

bool NeuralLMPathScorer::load(const std::string& path) {
  loaded_ = false;
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;

  char magic[8];
  if (!readExact(in, magic, 8) || std::memcmp(magic, "LWLSTM1\0", 8) != 0) {
    return false;
  }
  if (!readExact(in, &emb_, 4) || !readExact(in, &hidden_, 4) ||
      !readExact(in, &layers_, 4) || !readExact(in, &vocab_, 4)) {
    return false;
  }
  if (emb_ <= 0 || hidden_ <= 0 || layers_ <= 0 || vocab_ <= 4 || layers_ > 4) {
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

  if (!readF(emb_w_, static_cast<size_t>(vocab_) * static_cast<size_t>(emb_))) {
    return false;
  }

  w_ih_.assign(static_cast<size_t>(layers_), {});
  w_hh_.assign(static_cast<size_t>(layers_), {});
  b_ih_.assign(static_cast<size_t>(layers_), {});
  b_hh_.assign(static_cast<size_t>(layers_), {});
  for (int li = 0; li < layers_; ++li) {
    int inDim = (li == 0) ? emb_ : hidden_;
    size_t wih = static_cast<size_t>(4 * hidden_) * static_cast<size_t>(inDim);
    size_t whh = static_cast<size_t>(4 * hidden_) * static_cast<size_t>(hidden_);
    size_t b = static_cast<size_t>(4 * hidden_);
    if (!readF(w_ih_[static_cast<size_t>(li)], wih) ||
        !readF(w_hh_[static_cast<size_t>(li)], whh) ||
        !readF(b_ih_[static_cast<size_t>(li)], b) ||
        !readF(b_hh_[static_cast<size_t>(li)], b)) {
      return false;
    }
  }
  if (!readF(fc_w_, static_cast<size_t>(vocab_) * static_cast<size_t>(hidden_)) ||
      !readF(fc_b_, static_cast<size_t>(vocab_))) {
    return false;
  }

  loaded_ = true;
  return true;
}

size_t NeuralLMPathScorer::parameterCount() const {
  if (!loaded_) return 0;
  size_t n = emb_w_.size() + fc_w_.size() + fc_b_.size();
  for (int li = 0; li < layers_; ++li) {
    n += w_ih_[static_cast<size_t>(li)].size();
    n += w_hh_[static_cast<size_t>(li)].size();
    n += b_ih_[static_cast<size_t>(li)].size();
    n += b_hh_[static_cast<size_t>(li)].size();
  }
  return n;
}

std::vector<std::string> NeuralLMPathScorer::flattenChars(
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

void NeuralLMPathScorer::lstmStep(int layer, const float* x,
                                  const float* h_prev, const float* c_prev,
                                  float* h_out, float* c_out) const {
  const int H = hidden_;
  const int inDim = (layer == 0) ? emb_ : hidden_;
  const auto& Wih = w_ih_[static_cast<size_t>(layer)];
  const auto& Whh = w_hh_[static_cast<size_t>(layer)];
  const auto& bih = b_ih_[static_cast<size_t>(layer)];
  const auto& bhh = b_hh_[static_cast<size_t>(layer)];

  // gates: i, f, g, o  each size H; PyTorch packs as [4H, in]
  std::vector<float> gates(static_cast<size_t>(4 * H), 0.f);
  for (int g = 0; g < 4 * H; ++g) {
    float s = bih[static_cast<size_t>(g)] + bhh[static_cast<size_t>(g)];
    for (int j = 0; j < inDim; ++j) {
      s += Wih[static_cast<size_t>(g) * static_cast<size_t>(inDim) +
               static_cast<size_t>(j)] *
           x[j];
    }
    for (int j = 0; j < H; ++j) {
      s += Whh[static_cast<size_t>(g) * static_cast<size_t>(H) +
               static_cast<size_t>(j)] *
           h_prev[j];
    }
    gates[static_cast<size_t>(g)] = s;
  }
  for (int j = 0; j < H; ++j) {
    float i_g = sigmoid(gates[static_cast<size_t>(j)]);
    float f_g = sigmoid(gates[static_cast<size_t>(H + j)]);
    float g_g = tanh_approx(gates[static_cast<size_t>(2 * H + j)]);
    float o_g = sigmoid(gates[static_cast<size_t>(3 * H + j)]);
    float c = f_g * c_prev[j] + i_g * g_g;
    float h = o_g * tanh_approx(c);
    c_out[j] = c;
    h_out[j] = h;
  }
}

void NeuralLMPathScorer::forwardLogits(const std::vector<int>& ids,
                                       std::vector<float>& logits,
                                       std::vector<float>& h,
                                       std::vector<float>& c) const {
  // h,c layout: layers * H
  const int H = hidden_;
  const int L = layers_;
  h.assign(static_cast<size_t>(L * H), 0.f);
  c.assign(static_cast<size_t>(L * H), 0.f);
  logits.assign(static_cast<size_t>(vocab_), 0.f);

  if (ids.empty()) return;

  int last = ids.back();
  // Run full sequence to get logits for next token after last id
  // Actually scoreSentence needs log p of each next token; we step per char.
  (void)last;
}

double NeuralLMPathScorer::scoreSentence(
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

  const int H = hidden_;
  const int L = layers_;
  std::vector<float> h(static_cast<size_t>(L * H), 0.f);
  std::vector<float> c(static_cast<size_t>(L * H), 0.f);
  std::vector<float> h2(static_cast<size_t>(L * H), 0.f);
  std::vector<float> c2(static_cast<size_t>(L * H), 0.f);
  std::vector<float> x(static_cast<size_t>(emb_));
  std::vector<float> layer_in(static_cast<size_t>(std::max(emb_, hidden_)));
  std::vector<float> logits(static_cast<size_t>(vocab_));

  double log10e = 1.0 / std::log(10.0);
  double sumLog10 = 0.0;
  int scored = 0;

  // Teacher forcing: for t = 0..T-2, condition on ids[t], score ids[t+1]
  for (size_t t = 0; t + 1 < ids.size(); ++t) {
    int id = ids[t];
    if (id < 0 || id >= vocab_) id = unk_id_;
    // embed
    const float* e =
        emb_w_.data() + static_cast<size_t>(id) * static_cast<size_t>(emb_);
    std::vector<float> cur(static_cast<size_t>(emb_));
    std::copy(e, e + emb_, cur.begin());
    std::vector<float> next_h(static_cast<size_t>(H));
    std::vector<float> next_c(static_cast<size_t>(H));

    for (int li = 0; li < L; ++li) {
      float* hp = h.data() + static_cast<size_t>(li * H);
      float* cp = c.data() + static_cast<size_t>(li * H);
      const float* xin = cur.data();
      lstmStep(li, xin, hp, cp, next_h.data(), next_c.data());
      std::copy(next_h.begin(), next_h.end(), hp);
      std::copy(next_c.begin(), next_c.end(), cp);
      // next layer input is this layer's new h (size H)
      cur.assign(next_h.begin(), next_h.end());
    }

    // logits from top layer h
    const float* ht = h.data() + static_cast<size_t>((L - 1) * H);
    float maxv = -1e30f;
    for (int v = 0; v < vocab_; ++v) {
      float s = fc_b_[static_cast<size_t>(v)];
      const float* w =
          fc_w_.data() + static_cast<size_t>(v) * static_cast<size_t>(H);
      for (int j = 0; j < H; ++j) s += w[j] * ht[j];
      logits[static_cast<size_t>(v)] = s;
      if (s > maxv) maxv = s;
    }
    // log-softmax of target
    double sumExp = 0.0;
    for (int v = 0; v < vocab_; ++v) {
      sumExp += std::exp(static_cast<double>(logits[static_cast<size_t>(v)] - maxv));
    }
    int target = ids[t + 1];
    if (target < 0 || target >= vocab_) target = unk_id_;
    double logp = static_cast<double>(logits[static_cast<size_t>(target)] - maxv) -
                  std::log(sumExp);
    sumLog10 += logp * log10e;
    ++scored;
  }

  return scored > 0 ? sumLog10 : 0.0;
}

}  // namespace McBopomofo
