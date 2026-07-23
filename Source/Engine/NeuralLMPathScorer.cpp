// Copyright (c) 2026 and onwards The McBopomofo Authors.

#include "NeuralLMPathScorer.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <unordered_map>

// Accelerate BLAS: forward-declare the single symbol we use (cblas_sgemv)
// instead of including <Accelerate/Accelerate.h>. The umbrella header pulls in
// BNNS, which fails to build as a C++ module under recent SDKs. The framework
// is still linked (OTHER_LDFLAGS / CMake / -framework Accelerate) for the symbol.
extern "C" {
void cblas_sgemv(int order, int trans_a, int m, int n, float alpha,
                 const float* a, int lda, const float* x, int incx, float beta,
                 float* y, int incy);
}
namespace {
constexpr int kCblasRowMajor = 101;
constexpr int kCblasNoTrans = 111;
}  // namespace

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
  if (!readExact(in, magic, 8)) return false;
  bool int8 = std::memcmp(magic, "LWLSTM8\0", 8) == 0;
  if (!int8 && std::memcmp(magic, "LWLSTM1\0", 8) != 0) {
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
  // int8 tensor: rows×cols int8 body + per-row float scale → dequant to fp32
  // (row-major, matches quantize_lstm_int8.cpp). "Really reads int8": bytes on
  // disk are int8; we reconstruct fp32 in RAM so the forward path is unchanged.
  auto readRowInt8 = [&](std::vector<float>& v, int rows, int cols) -> bool {
    size_t n = static_cast<size_t>(rows) * static_cast<size_t>(cols);
    std::vector<int8_t> q(n);
    std::vector<float> scale(static_cast<size_t>(rows));
    if (!readExact(in, q.data(), n) ||
        !readExact(in, scale.data(),
                   static_cast<size_t>(rows) * sizeof(float))) {
      return false;
    }
    v.resize(n);
    for (int r = 0; r < rows; ++r) {
      float s = scale[static_cast<size_t>(r)];
      for (int j = 0; j < cols; ++j) {
        v[static_cast<size_t>(r) * cols + j] =
            static_cast<float>(q[static_cast<size_t>(r) * cols + j]) * s;
      }
    }
    return true;
  };
  auto readW = [&](std::vector<float>& v, int rows, int cols) -> bool {
    return int8 ? readRowInt8(v, rows, cols)
                : readF(v, static_cast<size_t>(rows) * cols);
  };

  if (!readW(emb_w_, vocab_, emb_)) return false;

  w_ih_.assign(static_cast<size_t>(layers_), {});
  w_hh_.assign(static_cast<size_t>(layers_), {});
  b_ih_.assign(static_cast<size_t>(layers_), {});
  b_hh_.assign(static_cast<size_t>(layers_), {});
  for (int li = 0; li < layers_; ++li) {
    int inDim = (li == 0) ? emb_ : hidden_;
    size_t b = static_cast<size_t>(4 * hidden_);
    if (!readW(w_ih_[static_cast<size_t>(li)], 4 * hidden_, inDim) ||
        !readW(w_hh_[static_cast<size_t>(li)], 4 * hidden_, hidden_) ||
        !readF(b_ih_[static_cast<size_t>(li)], b) ||
        !readF(b_hh_[static_cast<size_t>(li)], b)) {
      return false;
    }
  }
  if (!readW(fc_w_, vocab_, hidden_) ||
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
  const int H = hidden_;
  const int L = layers_;
  h.assign(static_cast<size_t>(L * H), 0.f);
  c.assign(static_cast<size_t>(L * H), 0.f);
  logits.assign(static_cast<size_t>(vocab_), 0.f);
  if (ids.empty()) return;
  (void)ids.back();
}

// Shared teacher-forced pass. includeEos=true → BOS..chars..EOS (sentence
// score). includeEos=false → BOS..chars only, one log10 per content char.
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
  std::vector<float> logits(static_cast<size_t>(vocab_));

  double log10e = 1.0 / std::log(10.0);
  double sumLog10 = 0.0;
  int scored = 0;

  for (size_t t = 0; t + 1 < ids.size(); ++t) {
    int id = ids[t];
    if (id < 0 || id >= vocab_) id = unk_id_;
    const float* e =
        emb_w_.data() + static_cast<size_t>(id) * static_cast<size_t>(emb_);
    std::vector<float> cur(static_cast<size_t>(emb_));
    std::copy(e, e + emb_, cur.begin());
    std::vector<float> next_h(static_cast<size_t>(H));
    std::vector<float> next_c(static_cast<size_t>(H));

    for (int li = 0; li < L; ++li) {
      float* hp = h.data() + static_cast<size_t>(li * H);
      float* cp = c.data() + static_cast<size_t>(li * H);
      lstmStep(li, cur.data(), hp, cp, next_h.data(), next_c.data());
      std::copy(next_h.begin(), next_h.end(), hp);
      std::copy(next_c.begin(), next_c.end(), cp);
      cur.assign(next_h.begin(), next_h.end());
    }

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
    double sumExp = 0.0;
    for (int v = 0; v < vocab_; ++v) {
      sumExp +=
          std::exp(static_cast<double>(logits[static_cast<size_t>(v)] - maxv));
    }
    int target = ids[t + 1];
    if (target < 0 || target >= vocab_) target = unk_id_;
    double logp =
        static_cast<double>(logits[static_cast<size_t>(target)] - maxv) -
        std::log(sumExp);
    sumLog10 += logp * log10e;
    ++scored;
  }

  return scored > 0 ? sumLog10 : 0.0;
}

std::vector<double> NeuralLMPathScorer::scoreNBest(
    const std::vector<std::vector<std::string>>& paths) {
  if (!loaded_ || paths.empty()) {
    return std::vector<double>(paths.size(), 0.0);
  }
  const int H = hidden_;
  const int L = layers_;
  const int E = emb_;
  const int V = vocab_;

  // Build id sequences: BOS + content chars + EOS.
  std::vector<std::vector<int>> seqs(paths.size());
  for (size_t si = 0; si < paths.size(); ++si) {
    auto chars = flattenChars(paths[si]);
    auto& s = seqs[si];
    s.reserve(chars.size() + 2);
    s.push_back(bos_id_);
    for (const auto& ch : chars) {
      auto it = stoi_.find(ch);
      s.push_back(it == stoi_.end() ? unk_id_ : it->second);
    }
    s.push_back(eos_id_);
  }

  // Prefix trie over the id sequences: each distinct prefix computes its LSTM
  // step + one full-vocab softmax exactly once (identical prefixes are shared).
  struct TrieNode {
    std::vector<float> h, c;              // state AFTER consuming incoming id
    std::unordered_map<int, int> child;   // id -> node index
    bool stateReady = false;
  };
  std::vector<TrieNode> nodes(1);
  nodes[0].h.assign(static_cast<size_t>(L) * H, 0.f);
  nodes[0].c.assign(static_cast<size_t>(L) * H, 0.f);
  nodes[0].stateReady = true;
  std::vector<std::vector<std::pair<int, int>>> seqEdges(seqs.size());
  for (size_t si = 0; si < seqs.size(); ++si) {
    int cur = 0;
    for (int id : seqs[si]) {
      auto it = nodes[cur].child.find(id);
      int nxt;
      if (it == nodes[cur].child.end()) {
        nxt = static_cast<int>(nodes.size());
        nodes.emplace_back();
        nodes[cur].child[id] = nxt;
      } else {
        nxt = it->second;
      }
      seqEdges[si].emplace_back(cur, id);
      cur = nxt;
    }
  }

  // LSTM advance from (hIn,cIn) consuming id → (hOut,cOut), via BLAS gate matvec.
  auto advance = [&](const std::vector<float>& hIn, const std::vector<float>& cIn,
                     int id, std::vector<float>& hOut, std::vector<float>& cOut) {
    hOut.assign(static_cast<size_t>(L) * H, 0.f);
    cOut.assign(static_cast<size_t>(L) * H, 0.f);
    if (id < 0 || id >= V) id = unk_id_;
    std::vector<float> cur(
        emb_w_.data() + static_cast<size_t>(id) * E,
        emb_w_.data() + static_cast<size_t>(id) * E + E);
    std::vector<float> gates(static_cast<size_t>(4 * H));
    for (int l = 0; l < L; ++l) {
      int inDim = (l == 0) ? E : H;
      const float* hp = hIn.data() + static_cast<size_t>(l) * H;
      const float* cp = cIn.data() + static_cast<size_t>(l) * H;
      // gates = Wih@cur + Whh@hp
      cblas_sgemv(kCblasRowMajor, kCblasNoTrans, 4 * H, inDim, 1.0f,
                  w_ih_[static_cast<size_t>(l)].data(), inDim, cur.data(), 1,
                  0.0f, gates.data(), 1);
      cblas_sgemv(kCblasRowMajor, kCblasNoTrans, 4 * H, H, 1.0f,
                  w_hh_[static_cast<size_t>(l)].data(), H, hp, 1, 1.0f,
                  gates.data(), 1);
      const float* bih = b_ih_[static_cast<size_t>(l)].data();
      const float* bhh = b_hh_[static_cast<size_t>(l)].data();
      float* ho = hOut.data() + static_cast<size_t>(l) * H;
      float* co = cOut.data() + static_cast<size_t>(l) * H;
      for (int j = 0; j < H; ++j) {
        float ig = sigmoid(gates[j] + bih[j] + bhh[j]);
        float fg = sigmoid(gates[H + j] + bih[H + j] + bhh[H + j]);
        float gg = std::tanh(gates[2 * H + j] + bih[2 * H + j] + bhh[2 * H + j]);
        float og = sigmoid(gates[3 * H + j] + bih[3 * H + j] + bhh[3 * H + j]);
        float cc = fg * cp[j] + ig * gg;
        co[j] = cc;
        ho[j] = og * std::tanh(cc);
      }
      cur.assign(ho, ho + H);
    }
  };

  const double log10e = 1.0 / std::log(10.0);
  std::unordered_map<long long, double> edgeLogp;
  auto edgeKey = [](int p, int id) {
    return (static_cast<long long>(p) << 20) ^ static_cast<long long>(id);
  };
  std::vector<int> order;
  order.reserve(nodes.size());
  order.push_back(0);
  std::vector<float> logits(static_cast<size_t>(V));
  for (size_t qi = 0; qi < order.size(); ++qi) {
    int ni = order[qi];
    if (nodes[ni].child.empty()) continue;
    // softmax at this node's last-layer hidden
    const float* hLast = nodes[ni].h.data() + static_cast<size_t>(L - 1) * H;
    cblas_sgemv(kCblasRowMajor, kCblasNoTrans, V, H, 1.0f, fc_w_.data(), H, hLast,
                1, 0.0f, logits.data(), 1);
    float maxv = -1e30f;
    for (int v = 0; v < V; ++v) {
      logits[static_cast<size_t>(v)] += fc_b_[static_cast<size_t>(v)];
      if (logits[static_cast<size_t>(v)] > maxv) maxv = logits[static_cast<size_t>(v)];
    }
    double sumExp = 0.0;
    for (int v = 0; v < V; ++v)
      sumExp += std::exp(static_cast<double>(logits[static_cast<size_t>(v)] - maxv));
    double logZ = std::log(sumExp);
    for (const auto& kv : nodes[ni].child) {
      int id = kv.first;
      int tgt = (id < 0 || id >= V) ? unk_id_ : id;
      double lp =
          (static_cast<double>(logits[static_cast<size_t>(tgt)] - maxv) - logZ) *
          log10e;
      edgeLogp[edgeKey(ni, id)] = lp;
      int childIdx = kv.second;
      if (!nodes[childIdx].stateReady) {
        advance(nodes[ni].h, nodes[ni].c, id, nodes[childIdx].h,
                nodes[childIdx].c);
        nodes[childIdx].stateReady = true;
      }
      order.push_back(childIdx);
    }
  }

  std::vector<double> out(seqs.size(), 0.0);
  for (size_t si = 0; si < seqs.size(); ++si) {
    if (seqEdges[si].size() <= 1) continue;  // need ≥1 scored edge past BOS
    double s = 0.0;
    for (size_t e = 1; e < seqEdges[si].size(); ++e) {  // skip root→BOS
      s += edgeLogp[edgeKey(seqEdges[si][e].first, seqEdges[si][e].second)];
    }
    out[si] = s;
  }
  return out;
}

std::vector<double> NeuralLMPathScorer::scoreCharsLog10(
    const std::vector<std::string>& words) {
  std::vector<double> out;
  if (!loaded_ || words.empty()) return out;

  auto chars = flattenChars(words);
  if (chars.empty()) return out;

  // BOS + content only (no EOS): one score per content char.
  std::vector<int> ids;
  ids.push_back(bos_id_);
  for (const auto& ch : chars) {
    auto it = stoi_.find(ch);
    ids.push_back(it == stoi_.end() ? unk_id_ : it->second);
  }

  const int H = hidden_;
  const int L = layers_;
  std::vector<float> h(static_cast<size_t>(L * H), 0.f);
  std::vector<float> c(static_cast<size_t>(L * H), 0.f);
  std::vector<float> logits(static_cast<size_t>(vocab_));
  double log10e = 1.0 / std::log(10.0);

  for (size_t t = 0; t + 1 < ids.size(); ++t) {
    int id = ids[t];
    if (id < 0 || id >= vocab_) id = unk_id_;
    const float* e =
        emb_w_.data() + static_cast<size_t>(id) * static_cast<size_t>(emb_);
    std::vector<float> cur(static_cast<size_t>(emb_));
    std::copy(e, e + emb_, cur.begin());
    std::vector<float> next_h(static_cast<size_t>(H));
    std::vector<float> next_c(static_cast<size_t>(H));

    for (int li = 0; li < L; ++li) {
      float* hp = h.data() + static_cast<size_t>(li * H);
      float* cp = c.data() + static_cast<size_t>(li * H);
      lstmStep(li, cur.data(), hp, cp, next_h.data(), next_c.data());
      std::copy(next_h.begin(), next_h.end(), hp);
      std::copy(next_c.begin(), next_c.end(), cp);
      cur.assign(next_h.begin(), next_h.end());
    }

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
    double sumExp = 0.0;
    for (int v = 0; v < vocab_; ++v) {
      sumExp +=
          std::exp(static_cast<double>(logits[static_cast<size_t>(v)] - maxv));
    }
    int target = ids[t + 1];
    if (target < 0 || target >= vocab_) target = unk_id_;
    double logp =
        static_cast<double>(logits[static_cast<size_t>(target)] - maxv) -
        std::log(sumExp);
    out.push_back(logp * log10e);
  }
  return out;
}

double NeuralLMPathScorer::scoreContinuation(
    const std::vector<std::string>& prefixWords, const std::string& nextWord) {
  if (!loaded_ || nextWord.empty()) return 0.0;

  // Build id stream: BOS + prefix chars + nextWord chars.
  // Score only the nextWord portion (predictions of those targets).
  std::vector<std::string> prefixChars = flattenChars(prefixWords);
  std::vector<std::string> nextChars = flattenChars({nextWord});
  if (nextChars.empty()) return 0.0;

  std::vector<int> ids;
  ids.push_back(bos_id_);
  for (const auto& ch : prefixChars) {
    auto it = stoi_.find(ch);
    ids.push_back(it == stoi_.end() ? unk_id_ : it->second);
  }
  const size_t prefixIdCount = ids.size();  // includes BOS
  for (const auto& ch : nextChars) {
    auto it = stoi_.find(ch);
    ids.push_back(it == stoi_.end() ? unk_id_ : it->second);
  }

  const int H = hidden_;
  const int L = layers_;
  std::vector<float> h(static_cast<size_t>(L * H), 0.f);
  std::vector<float> c(static_cast<size_t>(L * H), 0.f);
  std::vector<float> logits(static_cast<size_t>(vocab_));
  double log10e = 1.0 / std::log(10.0);
  double sumLog10 = 0.0;
  int scored = 0;

  // t indexes the conditioning id; we score ids[t+1].
  // Only accumulate when the target is part of nextWord
  // (t+1 >= prefixIdCount).
  for (size_t t = 0; t + 1 < ids.size(); ++t) {
    int id = ids[t];
    if (id < 0 || id >= vocab_) id = unk_id_;
    const float* e =
        emb_w_.data() + static_cast<size_t>(id) * static_cast<size_t>(emb_);
    std::vector<float> cur(static_cast<size_t>(emb_));
    std::copy(e, e + emb_, cur.begin());
    std::vector<float> next_h(static_cast<size_t>(H));
    std::vector<float> next_c(static_cast<size_t>(H));

    for (int li = 0; li < L; ++li) {
      float* hp = h.data() + static_cast<size_t>(li * H);
      float* cp = c.data() + static_cast<size_t>(li * H);
      lstmStep(li, cur.data(), hp, cp, next_h.data(), next_c.data());
      std::copy(next_h.begin(), next_h.end(), hp);
      std::copy(next_c.begin(), next_c.end(), cp);
      cur.assign(next_h.begin(), next_h.end());
    }

    // Only score targets that belong to nextWord.
    if (t + 1 < prefixIdCount) continue;

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
    double sumExp = 0.0;
    for (int v = 0; v < vocab_; ++v) {
      sumExp +=
          std::exp(static_cast<double>(logits[static_cast<size_t>(v)] - maxv));
    }
    int target = ids[t + 1];
    if (target < 0 || target >= vocab_) target = unk_id_;
    double logp =
        static_cast<double>(logits[static_cast<size_t>(target)] - maxv) -
        std::log(sumExp);
    sumLog10 += logp * log10e;
    ++scored;
  }
  return scored > 0 ? sumLog10 : 0.0;
}

}  // namespace McBopomofo
