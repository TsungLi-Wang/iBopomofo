// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// Permission is hereby granted, free of charge, to any person
// obtaining a copy of this software and associated documentation
// files (the "Software"), to deal in the Software without
// restriction, including without limitation the rights to use,
// copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the
// Software is furnished to do so, subject to the following
// conditions:
//
// The above copyright notice and this permission notice shall be
// included in all copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
// EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
// OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
// NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
// HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
// WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
// FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
// OTHER DEALINGS IN THE SOFTWARE.

#include "NodeHomophoneExpert.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>

namespace iBopomofo {

namespace {

constexpr char kMagic[8] = {'I', 'Z', 'N', 'E', 'X', 'P', '1', '\0'};
constexpr int kPad = 0;
constexpr int kUnk = 1;

// 這一組永遠不開火，即使有人把它塞進白名單。
// PTT 上「該寫得」有很大比例寫成「的」，標籤本身是髒的；那組神經路線已死
// （docs/dead-ends.md D）。現役的 ParticleRuleDisambiguator 規則留著，
// 不准這顆專家去搶。硬擋在這裡，不靠呼叫端自律。
constexpr const char* kNeverFireReading = "ㄉㄜ˙";

inline float gelu(float x) {
  return 0.5f * x * (1.f + std::erf(x * 0.70710678118654752f));
}

bool readExact(std::ifstream& in, void* dst, size_t n) {
  in.read(static_cast<char*>(dst), static_cast<std::streamsize>(n));
  return static_cast<size_t>(in.gcount()) == n;
}

bool readFloats(std::ifstream& in, std::vector<float>* v, size_t n) {
  v->resize(n);
  return readExact(in, v->data(), n * sizeof(float));
}

std::vector<std::string> splitUtf8(const std::string& s) {
  std::vector<std::string> out;
  size_t i = 0;
  while (i < s.size()) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len = 1;
    if ((c & 0x80) == 0) {
      len = 1;
    } else if ((c & 0xE0) == 0xC0) {
      len = 2;
    } else if ((c & 0xF0) == 0xE0) {
      len = 3;
    } else if ((c & 0xF8) == 0xF0) {
      len = 4;
    }
    if (i + len > s.size()) len = 1;
    out.push_back(s.substr(i, len));
    i += len;
  }
  return out;
}

std::vector<std::string> splitReading(const std::string& reading) {
  std::vector<std::string> out;
  size_t start = 0;
  for (size_t i = 0; i <= reading.size(); ++i) {
    if (i == reading.size() || reading[i] == '-') {
      if (i > start) out.push_back(reading.substr(start, i - start));
      start = i + 1;
    }
  }
  return out;
}

// y = gelu(W0·x + b0) 之後再 W1·y + b1（與訓練端 nn.Sequential 相同）
void mlp2(const std::vector<float>& w0, const std::vector<float>& b0,
          const std::vector<float>& w1, const std::vector<float>& b1,
          const std::vector<float>& x, int hid, std::vector<float>* out) {
  const size_t inDim = x.size();
  std::vector<float> mid(static_cast<size_t>(hid));
  for (int i = 0; i < hid; ++i) {
    float s = b0[static_cast<size_t>(i)];
    const float* row = &w0[static_cast<size_t>(i) * inDim];
    for (size_t j = 0; j < inDim; ++j) s += row[j] * x[j];
    mid[static_cast<size_t>(i)] = gelu(s);
  }
  out->assign(static_cast<size_t>(hid), 0.f);
  for (int i = 0; i < hid; ++i) {
    float s = b1[static_cast<size_t>(i)];
    const float* row = &w1[static_cast<size_t>(i) * hid];
    for (int j = 0; j < hid; ++j) s += row[j] * mid[static_cast<size_t>(j)];
    (*out)[static_cast<size_t>(i)] = s;
  }
}

}  // namespace

bool NodeHomophoneExpert::load(const std::string& path) {
  loaded_ = false;
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;

  char magic[8];
  if (!readExact(in, magic, 8)) return false;
  if (std::memcmp(magic, kMagic, 8) != 0) return false;

  int32_t hdr[5];
  int32_t dims[3];
  if (!readExact(in, hdr, sizeof(hdr)) || !readExact(in, dims, sizeof(dims))) {
    return false;
  }
  emb_ = hdr[0];
  sylEmb_ = hdr[1];
  hid_ = hdr[2];
  nChar_ = hdr[3];
  nSyl_ = hdr[4];
  ctxChars_ = dims[0];
  candChars_ = dims[1];
  maxCands_ = dims[2];
  if (emb_ <= 0 || sylEmb_ <= 0 || hid_ <= 0 || nChar_ <= 2 || nSyl_ <= 2 ||
      ctxChars_ <= 0 || candChars_ <= 0 || maxCands_ <= 1) {
    return false;
  }

  auto readTable = [&](std::vector<std::string>* v,
                       std::unordered_map<std::string, int>* m, int n) -> bool {
    v->assign(static_cast<size_t>(n), "");
    m->clear();
    for (int i = 0; i < n; ++i) {
      int16_t len = 0;
      if (!readExact(in, &len, 2) || len < 0) return false;
      std::string s(static_cast<size_t>(len), '\0');
      if (len > 0 && !readExact(in, s.data(), static_cast<size_t>(len))) {
        return false;
      }
      (*v)[static_cast<size_t>(i)] = s;
      if (!s.empty()) (*m)[s] = i;
    }
    return true;
  };
  if (!readTable(&itos_, &ctoi_, nChar_)) return false;
  if (!readTable(&stos_, &stoi_, nSyl_)) return false;

  const size_t ctxIn =
      static_cast<size_t>(emb_) * ctxChars_ * 2 + sylEmb_ + 1;
  const size_t candIn = static_cast<size_t>(emb_) * candChars_ + 4;
  const size_t h = static_cast<size_t>(hid_);
  if (!readFloats(in, &charEmb_, static_cast<size_t>(nChar_) * emb_) ||
      !readFloats(in, &sylEmbW_, static_cast<size_t>(nSyl_) * sylEmb_) ||
      !readFloats(in, &ctx0W_, h * ctxIn) || !readFloats(in, &ctx0B_, h) ||
      !readFloats(in, &ctx1W_, h * h) || !readFloats(in, &ctx1B_, h) ||
      !readFloats(in, &cand0W_, h * candIn) || !readFloats(in, &cand0B_, h) ||
      !readFloats(in, &cand1W_, h * h) || !readFloats(in, &cand1B_, h) ||
      !readFloats(in, &head0W_, h * 2 * h) || !readFloats(in, &head0B_, h) ||
      !readFloats(in, &head1W_, h) || !readFloats(in, &head1B_, 1)) {
    return false;
  }

  loaded_ = true;
  return true;
}

size_t NodeHomophoneExpert::parameterCount() const {
  return charEmb_.size() + sylEmbW_.size() + ctx0W_.size() + ctx0B_.size() +
         ctx1W_.size() + ctx1B_.size() + cand0W_.size() + cand0B_.size() +
         cand1W_.size() + cand1B_.size() + head0W_.size() + head0B_.size() +
         head1W_.size() + head1B_.size();
}

std::vector<float> NodeHomophoneExpert::scoreCandidates(
    const std::vector<std::string>& leftChars,
    const std::vector<std::string>& rightChars,
    const std::vector<std::string>& readingSyllables, bool rightEmpty,
    const std::vector<std::string>& candValues,
    const std::vector<std::array<float, 4>>& candFeatures) const {
  std::vector<float> out;
  if (!loaded_ || candValues.empty() ||
      candValues.size() != candFeatures.size()) {
    return out;
  }

  auto charId = [&](const std::string& c) {
    auto it = ctoi_.find(c);
    return it == ctoi_.end() ? kUnk : it->second;
  };

  // ── 上下文向量：左右各 ctxChars_ 個字，**不足補 PAD 補到滿** ──
  // 訓練端餵的永遠是滿 ctxChars_（左邊靠右對齊、右邊靠左對齊）。少餵幾格
  // 就跟訓練不同分，而且不會報錯 —— parity 檢查就是在守這一條。
  const size_t ctxIn =
      static_cast<size_t>(emb_) * ctxChars_ * 2 + sylEmb_ + 1;
  std::vector<float> x(ctxIn, 0.f);
  size_t take = std::min<size_t>(leftChars.size(), ctxChars_);
  for (size_t k = 0; k < take; ++k) {
    const int id = charId(leftChars[leftChars.size() - take + k]);
    const size_t slot = static_cast<size_t>(ctxChars_) - take + k;
    const float* e = &charEmb_[static_cast<size_t>(id) * emb_];
    std::copy(e, e + emb_, x.begin() + static_cast<long>(slot * emb_));
  }
  take = std::min<size_t>(rightChars.size(), ctxChars_);
  const size_t rightBase = static_cast<size_t>(emb_) * ctxChars_;
  for (size_t k = 0; k < take; ++k) {
    const int id = charId(rightChars[k]);
    const float* e = &charEmb_[static_cast<size_t>(id) * emb_];
    std::copy(e, e + emb_,
              x.begin() + static_cast<long>(rightBase + k * emb_));
  }
  const size_t sylBase = static_cast<size_t>(emb_) * ctxChars_ * 2;
  for (const std::string& s : readingSyllables) {
    auto it = stoi_.find(s);
    const int id = it == stoi_.end() ? kUnk : it->second;
    if (id == kPad) continue;
    const float* e = &sylEmbW_[static_cast<size_t>(id) * sylEmb_];
    for (int j = 0; j < sylEmb_; ++j) {
      x[sylBase + static_cast<size_t>(j)] += e[j];
    }
  }
  x[ctxIn - 1] = rightEmpty ? 1.f : 0.f;

  std::vector<float> hctx;
  mlp2(ctx0W_, ctx0B_, ctx1W_, ctx1B_, x, hid_, &hctx);

  const size_t candIn = static_cast<size_t>(emb_) * candChars_ + 4;
  std::vector<float> logits;
  logits.reserve(candValues.size());
  std::vector<float> cx(candIn, 0.f);
  std::vector<float> hcand;
  std::vector<float> joined(static_cast<size_t>(hid_) * 2);
  std::vector<float> hh(static_cast<size_t>(hid_));
  for (size_t i = 0; i < candValues.size(); ++i) {
    std::fill(cx.begin(), cx.end(), 0.f);
    const auto chars = splitUtf8(candValues[i]);
    for (size_t k = 0; k < chars.size() && k < static_cast<size_t>(candChars_);
         ++k) {
      const float* e = &charEmb_[static_cast<size_t>(charId(chars[k])) * emb_];
      std::copy(e, e + emb_, cx.begin() + static_cast<long>(k * emb_));
    }
    for (int j = 0; j < 4; ++j) {
      cx[static_cast<size_t>(emb_) * candChars_ + static_cast<size_t>(j)] =
          candFeatures[i][static_cast<size_t>(j)];
    }
    mlp2(cand0W_, cand0B_, cand1W_, cand1B_, cx, hid_, &hcand);
    std::copy(hctx.begin(), hctx.end(), joined.begin());
    std::copy(hcand.begin(), hcand.end(),
              joined.begin() + static_cast<long>(hid_));
    // head：Linear→GELU→Linear(1)
    for (int r = 0; r < hid_; ++r) {
      float s = head0B_[static_cast<size_t>(r)];
      const float* row = &head0W_[static_cast<size_t>(r) * 2 * hid_];
      for (size_t j = 0; j < joined.size(); ++j) s += row[j] * joined[j];
      hh[static_cast<size_t>(r)] = gelu(s);
    }
    float s = head1B_[0];
    for (int j = 0; j < hid_; ++j) {
      s += head1W_[static_cast<size_t>(j)] * hh[static_cast<size_t>(j)];
    }
    logits.push_back(s);
  }

  // log-softmax，限制在這個節點的候選集合上（與訓練端相同）
  float mx = -std::numeric_limits<float>::infinity();
  for (float v : logits) mx = std::max(mx, v);
  float sum = 0.f;
  for (float v : logits) sum += std::exp(v - mx);
  const float logZ = mx + std::log(sum);
  for (float& v : logits) v -= logZ;
  return logits;
}

bool NodeHomophoneExpert::isAppliedByUs(
    const ReadingGrid::NodePtr& node) const {
  auto it = applied_.find(node.get());
  if (it == applied_.end()) return false;
  return !it->second.expired();
}

bool NodeHomophoneExpert::rescoreWalk(const ReadingGrid::WalkResult& walk) {
  if (!loaded_) return false;
  // PMI 特徵在抽取時是真的算過的。沒有 context model 就餵不出同樣的特徵，
  // 那會是訓練推論不一致 —— 寧可什麼都不做，也不要拿半套特徵去改人家的字。
  if (contextModel_ == nullptr) return false;

  for (auto it = applied_.begin(); it != applied_.end();) {
    it = it->second.expired() ? applied_.erase(it) : std::next(it);
  }

  // ⚠️ 一律 chosenValueAt，不是 node->value()。value() 是最高頻候選，
  // 開了情境 walk／神經重排之後常常不是使用者看到的字
  // （ParticleRuleDisambiguator 踩過，少修約三成）。
  const std::vector<ReadingGrid::NodePtr>& nodes = walk.nodes;
  std::vector<std::string> nodeValues;
  std::vector<std::string> flatChars;
  std::vector<size_t> nodeCharStart;
  for (size_t n = 0; n < nodes.size(); ++n) {
    nodeValues.push_back(walk.chosenValueAt(n));
    nodeCharStart.push_back(flatChars.size());
    for (const auto& c : splitUtf8(nodeValues.back())) flatChars.push_back(c);
  }

  bool changed = false;
  for (size_t n = 0; n < nodes.size(); ++n) {
    const auto& node = nodes[n];
    const auto syllables = splitReading(node->reading());

    bool fire = false;
    for (const auto& s : syllables) {
      if (s == kNeverFireReading) {  // 硬擋，白名單也蓋不過
        fire = false;
        break;
      }
      if (fireReadings_.count(s)) fire = true;
    }
    if (!fire) continue;

    const auto& unigrams = node->unigrams();
    if (unigrams.size() < 2) continue;
    ++counters_.considered;

    // 絕不跟使用者或別的機制搶。
    if (node->isOverridden() && !isAppliedByUs(node)) {
      ++counters_.skipped_user_override;
      continue;
    }

    // 候選按 unigram 分數取前 maxCands_ —— 與訓練端同一條規則。
    std::vector<const Formosa::Gramambular2::LanguageModel::Unigram*> sorted;
    sorted.reserve(unigrams.size());
    for (const auto& u : unigrams) sorted.push_back(&u);
    std::stable_sort(sorted.begin(), sorted.end(),
                     [](const auto* a, const auto* b) {
                       return a->score() > b->score();
                     });
    if (sorted.size() > static_cast<size_t>(maxCands_)) {
      sorted.resize(static_cast<size_t>(maxCands_));
    }

    const std::string& chosen = nodeValues[n];
    size_t chosenIdx = sorted.size();
    for (size_t i = 0; i < sorted.size(); ++i) {
      if (sorted[i]->value() == chosen) chosenIdx = i;
    }
    if (chosenIdx == sorted.size()) {
      // 引擎目前選的字被截斷了 → 我們看不到它，沒有比較基準，直接棄權。
      ++counters_.abstained_same;
      continue;
    }

    const std::string leftWord = n > 0 ? nodeValues[n - 1] : "";
    const std::string rightWord =
        (n + 1 < nodeValues.size()) ? nodeValues[n + 1] : "";
    const size_t start = nodeCharStart[n];
    const size_t end = start + splitUtf8(chosen).size();
    std::vector<std::string> leftChars(
        flatChars.begin() + static_cast<long>(start > 6 ? start - 6 : 0),
        flatChars.begin() + static_cast<long>(start));
    std::vector<std::string> rightChars(
        flatChars.begin() + static_cast<long>(std::min(end, flatChars.size())),
        flatChars.begin() +
            static_cast<long>(std::min(end + 6, flatChars.size())));
    const bool rightEmpty = end >= flatChars.size();

    std::vector<std::string> values;
    std::vector<std::array<float, 4>> feats;
    for (size_t i = 0; i < sorted.size(); ++i) {
      const auto* u = sorted[i];
      double stateL = 0.0;
      double stateR = 0.0;
      values.push_back(u->value());
      feats.push_back({static_cast<float>(u->score() / 10.0),
                       static_cast<float>(
                           contextModel_->score(leftWord, u->value(), stateL)),
                       static_cast<float>(
                           contextModel_->score(u->value(), rightWord, stateR)),
                       u->value() == chosen ? 1.f : 0.f});
    }

    const auto scores =
        scoreCandidates(leftChars, rightChars, syllables, rightEmpty, values,
                        feats);
    if (scores.size() != values.size()) continue;

    size_t best = 0;
    for (size_t i = 1; i < scores.size(); ++i) {
      if (scores[i] > scores[best]) best = i;
    }
    if (best == chosenIdx) {
      ++counters_.abstained_same;
      continue;
    }
    // 棄權是預設：沒把握就完全不動。
    if (!(scores[best] - scores[chosenIdx] > tau_)) {
      ++counters_.abstained_tau;
      continue;
    }

    if (node->selectOverrideUnigram(
            values[best], ReadingGrid::Node::OverrideType::
                              kOverrideValueWithScoreFromTopUnigram)) {
      applied_[node.get()] = node;
      changed = true;
      ++counters_.fired;
    }
  }
  return changed;
}

}  // namespace iBopomofo
