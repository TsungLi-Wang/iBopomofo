// Optimized N=10 rerank latency harness (shipping-debt Pareto).
//
// Reranks the SAME n-best the engine produces (reading_grid walkNBest), so
// "correct" is faithful to the shipped rerank path; only the scorer is
// optimized. Two levers vs the per-candidate NeuralLMPathScorer:
//   (1) prefix-state sharing — the 10 candidates share most of the sentence;
//       a char-id trie computes each distinct prefix's LSTM step + softmax
//       ONCE instead of restarting from BOS per candidate.
//   (2) Accelerate BLAS (cblas_sgemv) for the 4H×in gate matvecs and the V×H
//       output projection (the memory-bound cost).
//   (3) optional weight-only int8 (per-output-row symmetric) — cuts the V×H
//       projection's bandwidth ~4×; accuracy loss measured, not assumed.
//
// fp32 mode must reproduce the engine's rerank score exactly (trie + BLAS do
// not change the math beyond float reassociation) → same tw538 correct.
//
// Usage:
//   rerank_opt <sentences> <data> <bigrams> <lambda> <lstm.bin> <nu> [int8]
//   int8 ∈ {0,1} (default 0). nu = the fusion weight (walk + nu*neural).

#include <Accelerate/Accelerate.h>

#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <unordered_map>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

#include "../benchmark_gate.h"

using Formosa::Gramambular2::ReadingGrid;
using iBopomofo::CorpusBigramContextModel;
using iBopomofo::ParselessLM;

namespace {

std::vector<std::string> splitSyllables(const std::string& r) {
  std::vector<std::string> out;
  size_t s = 0;
  for (size_t i = 0; i < r.size(); ++i) {
    if (r[i] == '-') {
      if (i > s) out.push_back(r.substr(s, i - s));
      s = i + 1;
    }
  }
  if (s < r.size()) out.push_back(r.substr(s));
  return out;
}

ReadingGrid makeGrid(ParselessLM* lm) {
  ReadingGrid grid(std::shared_ptr<Formosa::Gramambular2::LanguageModel>(
      lm, [](Formosa::Gramambular2::LanguageModel*) {}));
  grid.setReadingSeparator("-");
  return grid;
}

bool feed(ReadingGrid& grid, const std::string& readings) {
  for (const auto& syl : splitSyllables(readings)) {
    grid.setCursor(grid.length());
    if (!grid.insertReading(syl)) return false;
  }
  return true;
}

struct Case {
  std::string readings;
  std::string expected;
};

std::vector<Case> loadCases(const std::string& path) {
  std::ifstream in(path);
  std::vector<Case> cases;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#') continue;
    size_t tab = line.find('\t');
    if (tab == std::string::npos) continue;
    cases.push_back({line.substr(0, tab), line.substr(tab + 1)});
  }
  return cases;
}

std::vector<std::string> utf8Chars(const std::string& s) {
  std::vector<std::string> out;
  size_t i = 0;
  while (i < s.size()) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len = 1;
    if ((c & 0x80) == 0) len = 1;
    else if ((c & 0xE0) == 0xC0) len = 2;
    else if ((c & 0xF0) == 0xE0) len = 3;
    else if ((c & 0xF8) == 0xF0) len = 4;
    if (i + len > s.size()) len = 1;
    out.push_back(s.substr(i, len));
    i += len;
  }
  return out;
}

inline float sigmoidf(float x) {
  if (x > 20.f) return 1.f;
  if (x < -20.f) return 0.f;
  return 1.f / (1.f + std::exp(-x));
}

// ---- Optimized char-LSTM scorer (LWLSTM1) --------------------------------
class FastLSTM {
 public:
  bool load(const std::string& path, bool int8) {
    int8_ = int8;
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    char magic[8];
    in.read(magic, 8);
    if (std::memcmp(magic, "LWLSTM1\0", 8) != 0) return false;
    in.read(reinterpret_cast<char*>(&E_), 4);
    in.read(reinterpret_cast<char*>(&H_), 4);
    in.read(reinterpret_cast<char*>(&L_), 4);
    in.read(reinterpret_cast<char*>(&V_), 4);
    if (E_ <= 0 || H_ <= 0 || L_ <= 0 || V_ <= 4) return false;
    itos_.resize(V_);
    for (int i = 0; i < V_; ++i) {
      int16_t len = 0;
      in.read(reinterpret_cast<char*>(&len), 2);
      std::string s(len > 0 ? static_cast<size_t>(len) : 0, '\0');
      if (len > 0) in.read(s.data(), len);
      itos_[i] = s;
      if (!s.empty()) stoi_[s] = i;
    }
    unk_ = stoi_.count("<unk>") ? stoi_["<unk>"] : 1;
    bos_ = stoi_.count("<s>") ? stoi_["<s>"] : 2;
    eos_ = stoi_.count("</s>") ? stoi_["</s>"] : 3;
    auto rf = [&](std::vector<float>& v, size_t n) {
      v.resize(n);
      in.read(reinterpret_cast<char*>(v.data()), n * sizeof(float));
    };
    rf(emb_, static_cast<size_t>(V_) * E_);
    wih_.resize(L_); whh_.resize(L_); bih_.resize(L_); bhh_.resize(L_);
    for (int l = 0; l < L_; ++l) {
      int in_ = (l == 0) ? E_ : H_;
      rf(wih_[l], static_cast<size_t>(4 * H_) * in_);
      rf(whh_[l], static_cast<size_t>(4 * H_) * H_);
      rf(bih_[l], 4 * H_);
      rf(bhh_[l], 4 * H_);
    }
    rf(fc_w_, static_cast<size_t>(V_) * H_);
    rf(fc_b_, V_);
    if (!in) return false;
    if (int8_) quantize();
    loaded_ = true;
    return true;
  }

  bool loaded() const { return loaded_; }
  int vocab() const { return V_; }
  size_t params() const {
    size_t n = emb_.size() + fc_w_.size() + fc_b_.size();
    for (int l = 0; l < L_; ++l)
      n += wih_[l].size() + whh_[l].size() + bih_[l].size() + bhh_[l].size();
    return n;
  }

  int idOf(const std::string& ch) const {
    auto it = stoi_.find(ch);
    return it == stoi_.end() ? unk_ : it->second;
  }
  int bos() const { return bos_; }
  int eos() const { return eos_; }

  // Score a batch of id-sequences (each = BOS, chars..., EOS) via a prefix
  // trie. Returns sum_t log10 P(id[t+1] | id[0..t]) per sequence.
  std::vector<double> scoreBatch(const std::vector<std::vector<int>>& seqs) {
    // ---- build trie ----
    // node 0 = root (zero state, "nothing consumed"). Edge label = consumed id.
    struct Node {
      std::vector<float> h, c;         // state AFTER consuming incoming id
      std::unordered_map<int, int> ch; // id -> child node index
      bool stateReady = false;
    };
    std::vector<Node> nodes(1);
    nodes[0].h.assign(static_cast<size_t>(L_) * H_, 0.f);
    nodes[0].c.assign(static_cast<size_t>(L_) * H_, 0.f);
    nodes[0].stateReady = true;
    // per-seq edge list (node, targetId, edgeScored?) — edge from parent to
    // child; scored unless it is the root→BOS edge.
    std::vector<std::vector<std::pair<int, int>>> seqEdges(seqs.size());
    for (size_t si = 0; si < seqs.size(); ++si) {
      int cur = 0;
      for (size_t t = 0; t < seqs[si].size(); ++t) {
        int id = seqs[si][t];
        auto it = nodes[cur].ch.find(id);
        int nxt;
        if (it == nodes[cur].ch.end()) {
          nxt = static_cast<int>(nodes.size());
          nodes.emplace_back();
          nodes[cur].ch[id] = nxt;
        } else {
          nxt = it->second;
        }
        // edge (parent=cur, target=id): scored if it predicts a content/eos
        // token, i.e. NOT the very first BOS consumption (t==0).
        seqEdges[si].emplace_back(cur, id);
        cur = nxt;
      }
    }
    // ---- BFS: for each node with children, one softmax; advance each child ----
    // edgeLogp[(parent,id)] filled as we go.
    std::unordered_map<long long, double> edgeLogp;
    auto key = [](int p, int id) {
      return (static_cast<long long>(p) << 20) ^ id;
    };
    std::vector<int> order;
    order.push_back(0);
    for (size_t qi = 0; qi < order.size(); ++qi) {
      int ni = order[qi];
      if (nodes[ni].ch.empty()) continue;
      // softmax at this node's last-layer hidden
      const float* hLast = nodes[ni].h.data() + static_cast<size_t>(L_ - 1) * H_;
      std::vector<float> logits(V_);
      cblas_sgemv(CblasRowMajor, CblasNoTrans, V_, H_, 1.0f, fc_w_.data(),
                  H_, hLast, 1, 0.0f, logits.data(), 1);
      float maxv = -1e30f;
      for (int v = 0; v < V_; ++v) {
        logits[v] += fc_b_[v];
        if (logits[v] > maxv) maxv = logits[v];
      }
      double sumExp = 0.0;
      for (int v = 0; v < V_; ++v)
        sumExp += std::exp(static_cast<double>(logits[v] - maxv));
      double logZ = std::log(sumExp);
      static const double kLog10e = 1.0 / std::log(10.0);
      for (const auto& kv : nodes[ni].ch) {
        int id = kv.first;
        double lp = (static_cast<double>(logits[id] - maxv) - logZ) * kLog10e;
        edgeLogp[key(ni, id)] = lp;
        // advance LSTM to child
        int childIdx = kv.second;
        if (!nodes[childIdx].stateReady) {
          advance(nodes[ni].h, nodes[ni].c, id, nodes[childIdx].h,
                  nodes[childIdx].c);
          nodes[childIdx].stateReady = true;
        }
        order.push_back(childIdx);
      }
    }
    // ---- sum per-seq (skip the first edge = BOS consumption) ----
    std::vector<double> out(seqs.size(), 0.0);
    for (size_t si = 0; si < seqs.size(); ++si) {
      double s = 0.0;
      for (size_t e = 1; e < seqEdges[si].size(); ++e) {  // skip root→BOS
        s += edgeLogp[key(seqEdges[si][e].first, seqEdges[si][e].second)];
      }
      out[si] = seqEdges[si].size() > 1 ? s : 0.0;
    }
    return out;
  }

 private:
  // Per-output-row symmetric int8 round-trip in place: w := round(w/scale)*scale
  // (scale = row max-abs / 127). Dequantized values are exactly what int8-weight
  // inference would use, so running the normal fp32 path over them measures the
  // true accuracy loss. On-disk size of such a model = params×1B + row scales
  // (~1/4 of fp32); that is deterministic arithmetic, reported in the doc.
  static void rowQuantInPlace(std::vector<float>& w, int rows, int cols) {
    for (int r = 0; r < rows; ++r) {
      float* row = w.data() + static_cast<size_t>(r) * cols;
      float amax = 1e-9f;
      for (int j = 0; j < cols; ++j) amax = std::max(amax, std::fabs(row[j]));
      float scale = amax / 127.0f;
      for (int j = 0; j < cols; ++j) {
        int q = static_cast<int>(std::lround(row[j] / scale));
        q = std::max(-127, std::min(127, q));
        row[j] = static_cast<float>(q) * scale;
      }
    }
  }

  void quantize() {
    rowQuantInPlace(emb_, V_, E_);
    rowQuantInPlace(fc_w_, V_, H_);
    for (int l = 0; l < L_; ++l) {
      int in_ = (l == 0) ? E_ : H_;
      rowQuantInPlace(wih_[l], 4 * H_, in_);
      rowQuantInPlace(whh_[l], 4 * H_, H_);
    }
  }

  void advance(const std::vector<float>& hIn, const std::vector<float>& cIn,
               int id, std::vector<float>& hOut, std::vector<float>& cOut) {
    hOut.assign(static_cast<size_t>(L_) * H_, 0.f);
    cOut.assign(static_cast<size_t>(L_) * H_, 0.f);
    std::vector<float> cur(emb_.data() + static_cast<size_t>(id) * E_,
                           emb_.data() + static_cast<size_t>(id) * E_ + E_);
    std::vector<float> gates(4 * H_);
    for (int l = 0; l < L_; ++l) {
      int in_ = (l == 0) ? E_ : H_;
      const float* hp = hIn.data() + static_cast<size_t>(l) * H_;
      const float* cp = cIn.data() + static_cast<size_t>(l) * H_;
      // gates = Wih@cur + Whh@hp + bih + bhh
      cblas_sgemv(CblasRowMajor, CblasNoTrans, 4 * H_, in_, 1.0f,
                  wih_[l].data(), in_, cur.data(), 1, 0.0f, gates.data(), 1);
      cblas_sgemv(CblasRowMajor, CblasNoTrans, 4 * H_, H_, 1.0f, whh_[l].data(),
                  H_, hp, 1, 1.0f, gates.data(), 1);
      float* ho = hOut.data() + static_cast<size_t>(l) * H_;
      float* co = cOut.data() + static_cast<size_t>(l) * H_;
      for (int j = 0; j < H_; ++j) {
        float ig = sigmoidf(gates[j] + bih_[l][j] + bhh_[l][j]);
        float fg = sigmoidf(gates[H_ + j] + bih_[l][H_ + j] + bhh_[l][H_ + j]);
        float gg = std::tanh(gates[2 * H_ + j] + bih_[l][2 * H_ + j] +
                             bhh_[l][2 * H_ + j]);
        float og = sigmoidf(gates[3 * H_ + j] + bih_[l][3 * H_ + j] +
                            bhh_[l][3 * H_ + j]);
        float cc = fg * cp[j] + ig * gg;
        co[j] = cc;
        ho[j] = og * std::tanh(cc);
      }
      cur.assign(ho, ho + H_);
    }
  }

  bool loaded_ = false, int8_ = false;
  int E_ = 0, H_ = 0, L_ = 0, V_ = 0, unk_ = 1, bos_ = 2, eos_ = 3;
  std::vector<std::string> itos_;
  std::unordered_map<std::string, int> stoi_;
  std::vector<float> emb_, fc_w_, fc_b_;
  std::vector<std::vector<float>> wih_, whh_, bih_, bhh_;
};

}  // namespace

int main(int argc, char** argv) {
  if (argc < 7) {
    std::cerr << "Usage: rerank_opt sentences data bigrams lambda lstm.bin nu "
                 "[int8]\n";
    return 1;
  }
  iBopomofoEval::AbortUnlessTw538(argv[1]);
  auto cases = loadCases(argv[1]);
  ParselessLM lm;
  if (!lm.open(argv[2])) { std::cerr << "data fail\n"; return 1; }
  CorpusBigramContextModel cm;
  if (!cm.load(argv[3])) { std::cerr << "bigram fail\n"; return 1; }
  cm.setLambda(std::stod(argv[4]));
  double nu = std::stod(argv[6]);
  bool int8 = argc > 7 && std::stoi(argv[7]) != 0;

  FastLSTM lstm;
  if (!lstm.load(argv[5], int8)) { std::cerr << "lstm fail\n"; return 1; }
  std::cout << "scorer=FastLSTM int8=" << int8 << " params=" << lstm.params()
            << " vocab=" << lstm.vocab() << " nu=" << nu << "\n";

  int correct = 0, n = 0;
  long long usNbest = 0, usScore = 0;
  for (const auto& c : cases) {
    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, c.readings)) continue;
    g.setContextModel(&cm);
    auto t0 = std::chrono::steady_clock::now();
    auto nbest = g.walkNBest(10);
    auto t1 = std::chrono::steady_clock::now();
    usNbest += std::chrono::duration_cast<std::chrono::microseconds>(t1 - t0)
                   .count();
    ++n;
    if (nbest.empty()) continue;

    auto ts0 = std::chrono::steady_clock::now();
    // build id sequences (BOS + chars + EOS) for each candidate
    std::vector<std::vector<int>> seqs(nbest.size());
    for (size_t pi = 0; pi < nbest.size(); ++pi) {
      std::string text;
      for (const auto& w : nbest[pi].words) text += w;
      auto chars = utf8Chars(text);
      auto& s = seqs[pi];
      s.reserve(chars.size() + 2);
      s.push_back(lstm.bos());
      for (const auto& ch : chars) s.push_back(lstm.idOf(ch));
      s.push_back(lstm.eos());
    }
    auto scores = lstm.scoreBatch(seqs);
    size_t best = 0;
    double bestFinal = -1e300;
    for (size_t pi = 0; pi < nbest.size(); ++pi) {
      double f = nbest[pi].walkScore + nu * scores[pi];
      if (f > bestFinal) { bestFinal = f; best = pi; }
    }
    auto ts1 = std::chrono::steady_clock::now();
    usScore += std::chrono::duration_cast<std::chrono::microseconds>(ts1 - ts0)
                   .count();

    std::string picked;
    for (const auto& w : nbest[best].words) picked += w;
    if (picked == c.expected) ++correct;
  }
  double msNbest = n ? (double)usNbest / n / 1000.0 : 0;
  double msScore = n ? (double)usScore / n / 1000.0 : 0;
  std::cout << "CORRECT " << correct << "/" << cases.size() << "\n";
  std::cout << "MEAN_MS_TOTAL " << (msNbest + msScore)
            << " (nbest " << msNbest << " + rerank_score " << msScore << ")\n";
  std::cout << "N " << n << "\n";
  return 0;
}
