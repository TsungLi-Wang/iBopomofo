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

#include "NodeHomophoneScorer.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>

namespace iBopomofo {

namespace {

constexpr char kMagic[8] = {'I', 'Z', 'N', 'O', 'D', 'E', '1', '\0'};
constexpr int kPad = 0;
constexpr int kUnk = 1;

inline float sigmoid(float x) {
  if (x > 20.f) return 1.f;
  if (x < -20.f) return 0.f;
  return 1.f / (1.f + std::exp(-x));
}

// 與 torch.nn.GELU() 預設（精確版，erf）一致。
inline float gelu(float x) {
  return 0.5f * x * (1.f + std::erf(x * 0.70710678118654752f));
}

bool readExact(std::ifstream& in, void* dst, size_t n) {
  in.read(reinterpret_cast<char*>(dst), static_cast<std::streamsize>(n));
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

// 節點的 reading 是各字讀音以 "-" 相連（ReadingGrid 的慣例）。
std::vector<std::string> splitReading(const std::string& reading) {
  std::vector<std::string> out;
  size_t start = 0;
  while (true) {
    size_t hit = reading.find('-', start);
    if (hit == std::string::npos) {
      out.push_back(reading.substr(start));
      break;
    }
    out.push_back(reading.substr(start, hit - start));
    start = hit + 1;
  }
  return out;
}

}  // namespace

bool NodeHomophoneScorer::load(const std::string& path) {
  loaded_ = false;
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;

  char magic[8];
  if (!readExact(in, magic, 8)) return false;
  // 刻意不接受 LWLSTM：那是路徑層的單向堆疊 LSTM，架構對不上，
  // 換副檔名接得上是假的（docs/decisions/0008 第四節）。
  if (std::memcmp(magic, kMagic, 8) != 0) return false;

  int32_t hdr[7];
  if (!readExact(in, hdr, sizeof(hdr))) return false;
  emb_ = hdr[0];
  hidden_ = hdr[1];
  layers_ = hdr[2];
  readEmb_ = hdr[3];
  merge_ = hdr[4];
  nChar_ = hdr[5];
  nReading_ = hdr[6];
  if (emb_ <= 0 || hidden_ <= 0 || layers_ <= 0 || readEmb_ <= 0 ||
      merge_ <= 0 || nChar_ <= 2 || nReading_ <= 0) {
    return false;
  }

  auto readTable = [&](std::vector<std::string>* v,
                       std::unordered_map<std::string, int>* m,
                       int n) -> bool {
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
  if (!readTable(&itos_, &stoi_, nChar_)) return false;
  if (!readTable(&readings_, &rtoi_, nReading_)) return false;

  cand_.assign(static_cast<size_t>(nReading_), {});
  for (int i = 0; i < nReading_; ++i) {
    int16_t count = 0;
    if (!readExact(in, &count, 2) || count < 0) return false;
    std::vector<int32_t> ids(static_cast<size_t>(count));
    if (count > 0 &&
        !readExact(in, ids.data(), static_cast<size_t>(count) * 4)) {
      return false;
    }
    cand_[static_cast<size_t>(i)].assign(ids.begin(), ids.end());
  }

  if (!readFloats(in, &charEmb_, static_cast<size_t>(nChar_) * emb_)) {
    return false;
  }
  if (!readFloats(in, &readEmbW_, static_cast<size_t>(nReading_) * readEmb_)) {
    return false;
  }
  for (int dir = 0; dir < 2; ++dir) {
    wIh_[dir].assign(static_cast<size_t>(layers_), {});
    wHh_[dir].assign(static_cast<size_t>(layers_), {});
    bIh_[dir].assign(static_cast<size_t>(layers_), {});
    bHh_[dir].assign(static_cast<size_t>(layers_), {});
    for (int li = 0; li < layers_; ++li) {
      const size_t i = static_cast<size_t>(li);
      const int inDim = (li == 0) ? emb_ : hidden_;
      const size_t g = static_cast<size_t>(4 * hidden_);
      if (!readFloats(in, &wIh_[dir][i], g * static_cast<size_t>(inDim)) ||
          !readFloats(in, &wHh_[dir][i], g * static_cast<size_t>(hidden_)) ||
          !readFloats(in, &bIh_[dir][i], g) ||
          !readFloats(in, &bHh_[dir][i], g)) {
        return false;
      }
    }
  }
  const size_t mergeIn = static_cast<size_t>(2 * hidden_ + readEmb_);
  if (!readFloats(in, &m0W_, static_cast<size_t>(merge_) * mergeIn) ||
      !readFloats(in, &m0B_, static_cast<size_t>(merge_)) ||
      !readFloats(in, &m1W_,
                  static_cast<size_t>(merge_) * static_cast<size_t>(merge_)) ||
      !readFloats(in, &m1B_, static_cast<size_t>(merge_)) ||
      !readFloats(in, &outW_,
                  static_cast<size_t>(nChar_) * static_cast<size_t>(merge_)) ||
      !readFloats(in, &outB_, static_cast<size_t>(nChar_))) {
    return false;
  }

  loaded_ = true;
  return true;
}

size_t NodeHomophoneScorer::parameterCount() const {
  size_t n = charEmb_.size() + readEmbW_.size() + m0W_.size() + m0B_.size() +
             m1W_.size() + m1B_.size() + outW_.size() + outB_.size();
  for (int dir = 0; dir < 2; ++dir) {
    for (int li = 0; li < layers_; ++li) {
      const size_t i = static_cast<size_t>(li);
      n += wIh_[dir][i].size() + wHh_[dir][i].size() + bIh_[dir][i].size() +
           bHh_[dir][i].size();
    }
  }
  return n;
}

void NodeHomophoneScorer::lstmStep(int dir, int layer, const float* x,
                                   const float* hPrev, const float* cPrev,
                                   float* hOut, float* cOut) const {
  const int H = hidden_;
  const int inDim = (layer == 0) ? emb_ : hidden_;
  const size_t li = static_cast<size_t>(layer);
  const std::vector<float>& Wih = wIh_[dir][li];
  const std::vector<float>& Whh = wHh_[dir][li];
  const std::vector<float>& bih = bIh_[dir][li];
  const std::vector<float>& bhh = bHh_[dir][li];

  std::vector<float> gates(static_cast<size_t>(4 * H));
  for (int g = 0; g < 4 * H; ++g) {
    float s = bih[static_cast<size_t>(g)] + bhh[static_cast<size_t>(g)];
    const float* wRow = &Wih[static_cast<size_t>(g) * inDim];
    for (int j = 0; j < inDim; ++j) s += wRow[j] * x[j];
    const float* hRow = &Whh[static_cast<size_t>(g) * H];
    for (int j = 0; j < H; ++j) s += hRow[j] * hPrev[j];
    gates[static_cast<size_t>(g)] = s;
  }
  // 閘序 i,f,g,o —— 與 PyTorch 及 NeuralLMPathScorer::lstmStep 一致。
  for (int j = 0; j < H; ++j) {
    const float ig = sigmoid(gates[static_cast<size_t>(j)]);
    const float fg = sigmoid(gates[static_cast<size_t>(H + j)]);
    const float gg = std::tanh(gates[static_cast<size_t>(2 * H + j)]);
    const float og = sigmoid(gates[static_cast<size_t>(3 * H + j)]);
    const float c = fg * cPrev[j] + ig * gg;
    cOut[j] = c;
    hOut[j] = og * std::tanh(c);
  }
}

void NodeHomophoneScorer::runSide(int dir, const std::vector<int>& ids,
                                  std::vector<float>* out) const {
  const int H = hidden_;
  const int L = layers_;
  std::vector<float> h(static_cast<size_t>(L * H), 0.f);
  std::vector<float> c(static_cast<size_t>(L * H), 0.f);
  std::vector<float> x(static_cast<size_t>(std::max(emb_, H)));
  std::vector<float> hNew(static_cast<size_t>(H));
  std::vector<float> cNew(static_cast<size_t>(H));

  for (int id : ids) {
    const float* e = &charEmb_[static_cast<size_t>(id) * emb_];
    std::copy(e, e + emb_, x.begin());
    for (int li = 0; li < L; ++li) {
      float* hl = &h[static_cast<size_t>(li * H)];
      float* cl = &c[static_cast<size_t>(li * H)];
      lstmStep(dir, li, x.data(), hl, cl, hNew.data(), cNew.data());
      std::copy(hNew.begin(), hNew.end(), hl);
      std::copy(cNew.begin(), cNew.end(), cl);
      std::copy(hNew.begin(), hNew.end(), x.begin());
    }
  }
  out->assign(h.begin() + static_cast<long>((L - 1) * H),
              h.begin() + static_cast<long>(L * H));
}

void NodeHomophoneScorer::hiddenState(const std::vector<int>& leftIds,
                                      const std::vector<int>& rightIds,
                                      int readingId,
                                      std::vector<float>* out) const {
  std::vector<float> hl;
  std::vector<float> hr;
  runSide(0, leftIds, &hl);
  // 右文逆讀 —— 兩邊的 LSTM 都停在目標字旁邊（與訓練端 right.flip(1) 一致）。
  std::vector<int> flipped(rightIds.rbegin(), rightIds.rend());
  runSide(1, flipped, &hr);

  const size_t mergeIn = static_cast<size_t>(2 * hidden_ + readEmb_);
  std::vector<float> cat(mergeIn);
  std::copy(hl.begin(), hl.end(), cat.begin());
  std::copy(hr.begin(), hr.end(), cat.begin() + hidden_);
  const float* re = &readEmbW_[static_cast<size_t>(readingId) * readEmb_];
  std::copy(re, re + readEmb_, cat.begin() + 2 * hidden_);

  std::vector<float> mid(static_cast<size_t>(merge_));
  for (int i = 0; i < merge_; ++i) {
    float s = m0B_[static_cast<size_t>(i)];
    const float* row = &m0W_[static_cast<size_t>(i) * mergeIn];
    for (size_t j = 0; j < mergeIn; ++j) s += row[j] * cat[j];
    mid[static_cast<size_t>(i)] = gelu(s);
  }
  // 推論不套 dropout（nn.Dropout 在 eval 模式是恆等），所以 merge.1→merge.3
  // 中間那層什麼都不做，直接算第二個 Linear。
  out->assign(static_cast<size_t>(merge_), 0.f);
  for (int i = 0; i < merge_; ++i) {
    float s = m1B_[static_cast<size_t>(i)];
    const float* row = &m1W_[static_cast<size_t>(i) * merge_];
    for (int j = 0; j < merge_; ++j) s += row[j] * mid[static_cast<size_t>(j)];
    (*out)[static_cast<size_t>(i)] = s;
  }
}

size_t NodeHomophoneScorer::candidateCountForReading(
    const std::string& reading) const {
  auto it = rtoi_.find(reading);
  if (it == rtoi_.end()) return 0;
  return cand_[static_cast<size_t>(it->second)].size();
}

std::vector<std::pair<std::string, float>>
NodeHomophoneScorer::scoreCandidates(
    const std::vector<std::string>& leftChars,
    const std::vector<std::string>& rightChars, const std::string& reading,
    const std::vector<std::string>& candidates) const {
  std::vector<std::pair<std::string, float>> result;
  if (!loaded_ || candidates.empty()) return result;
  auto rit = rtoi_.find(reading);
  if (rit == rtoi_.end()) return result;

  // 左文取尾 kWindow、右文取頭 kWindow，**不足一律補 PAD 到滿 kWindow**。
  //
  // ⚠️ 補 PAD 不是可有可無的細節。padding_idx=0 只保證那一格的 embedding 是
  // 零向量，**LSTM 還是會吃掉那一步**（偏置讓零輸入照樣改變 h）。訓練端餵的
  // 永遠是滿 kWindow，這裡少餵幾步就跟訓練不同分 —— 而且不會報錯，只會讓
  // A/B 數字全是假的。scripts/node-scorer-parity.sh 就是在守這一條。
  std::vector<int> leftIds(kWindow, kPad);
  size_t lstart = leftChars.size() > kWindow ? leftChars.size() - kWindow : 0;
  size_t slot = kWindow - (leftChars.size() - lstart);
  for (size_t i = lstart; i < leftChars.size(); ++i, ++slot) {
    auto it = stoi_.find(leftChars[i]);
    leftIds[slot] = (it == stoi_.end() ? kUnk : it->second);
  }
  std::vector<int> rightIds(kWindow, kPad);
  for (size_t i = 0; i < rightChars.size() && i < kWindow; ++i) {
    auto it = stoi_.find(rightChars[i]);
    rightIds[i] = (it == stoi_.end() ? kUnk : it->second);
  }

  std::vector<float> h;
  hiddenState(leftIds, rightIds, rit->second, &h);

  std::vector<float> logits;
  logits.reserve(candidates.size());
  for (const std::string& cch : candidates) {
    auto it = stoi_.find(cch);
    if (it == stoi_.end()) {
      logits.push_back(-std::numeric_limits<float>::infinity());
      continue;
    }
    const float* row = &outW_[static_cast<size_t>(it->second) * merge_];
    float s = outB_[static_cast<size_t>(it->second)];
    for (int j = 0; j < merge_; ++j) s += row[j] * h[static_cast<size_t>(j)];
    logits.push_back(s);
  }
  // log-softmax，限制在傳進來的候選集合上（受限 softmax，與訓練端相同）。
  float mx = -std::numeric_limits<float>::infinity();
  for (float v : logits) mx = std::max(mx, v);
  if (!std::isfinite(mx)) return result;
  float sum = 0.f;
  for (float v : logits) sum += std::exp(v - mx);
  const float logZ = mx + std::log(sum);
  for (size_t i = 0; i < candidates.size(); ++i) {
    result.emplace_back(candidates[i], logits[i] - logZ);
  }
  return result;
}

bool NodeHomophoneScorer::isAppliedByUs(
    const ReadingGrid::NodePtr& node) const {
  auto it = applied_.find(node.get());
  if (it == applied_.end()) return false;
  return !it->second.expired();
}

bool NodeHomophoneScorer::rescoreWalk(const ReadingGrid::WalkResult& walk) {
  if (!loaded_) return false;

  for (auto it = applied_.begin(); it != applied_.end();) {
    it = it->second.expired() ? applied_.erase(it) : std::next(it);
  }

  // ⚠️ 一定要用 walk.chosenValueAt(n)，不能用 nodes[n]->value()。
  // 開了情境 walk 或神經重排之後 DP 常常不選最高頻候選，value() 給的字
  // 跟使用者實際看到的不一樣（ParticleRuleDisambiguator 踩過，少修約三成）。
  std::vector<std::string> chars;
  std::vector<std::string> charReadings;
  std::vector<size_t> ownerNode;
  std::vector<size_t> offsetInNode;
  const std::vector<ReadingGrid::NodePtr>& nodes = walk.nodes;
  for (size_t n = 0; n < nodes.size(); ++n) {
    std::vector<std::string> nodeChars = splitUtf8(walk.chosenValueAt(n));
    std::vector<std::string> nodeReadings = splitReading(nodes[n]->reading());
    for (size_t k = 0; k < nodeChars.size(); ++k) {
      chars.push_back(nodeChars[k]);
      charReadings.push_back(k < nodeReadings.size() ? nodeReadings[k]
                                                     : std::string());
      ownerNode.push_back(n);
      offsetInNode.push_back(k);
    }
  }

  bool changed = false;
  for (size_t i = 0; i < chars.size(); ++i) {
    const std::string& reading = charReadings[i];
    if (reading.empty()) continue;
    auto rit = rtoi_.find(reading);
    if (rit == rtoi_.end()) continue;
    const std::vector<int>& ids = cand_[static_cast<size_t>(rit->second)];
    if (ids.size() < 2) continue;  // 沒得選，不是這顆模型的題

    const ReadingGrid::NodePtr& node = nodes[ownerNode[i]];
    // 絕不跟使用者或 UOM 搶。
    if (node->isOverridden() && !isAppliedByUs(node)) continue;

    std::vector<std::string> nodeChars = splitUtf8(walk.chosenValueAt(ownerNode[i]));
    if (offsetInNode[i] >= nodeChars.size()) continue;

    // 只考慮「換上去之後節點真的有這個候選」的字 —— 拿不到的候選不該參與
    // 打分，否則模型會把機率押在一個永遠選不到的字上而白白棄權。
    std::vector<std::string> usable;
    std::vector<std::string> targets;
    for (int id : ids) {
      const std::string& cch = itos_[static_cast<size_t>(id)];
      std::vector<std::string> trial = nodeChars;
      trial[offsetInNode[i]] = cch;
      std::string joined;
      for (const std::string& t : trial) joined += t;
      bool present = (cch == chars[i]);
      if (!present) {
        for (const auto& u : node->unigrams()) {
          if (u.value() == joined) {
            present = true;
            break;
          }
        }
      }
      if (present) {
        usable.push_back(cch);
        targets.push_back(joined);
      }
    }
    if (usable.size() < 2) continue;

    std::vector<std::string> left(chars.begin(),
                                  chars.begin() + static_cast<long>(i));
    std::vector<std::string> right(chars.begin() + static_cast<long>(i + 1),
                                   chars.end());
    auto scored = scoreCandidates(left, right, reading, usable);
    if (scored.empty()) continue;

    size_t bestIdx = 0;
    float bestScore = -std::numeric_limits<float>::infinity();
    float currentScore = -std::numeric_limits<float>::infinity();
    for (size_t k = 0; k < scored.size(); ++k) {
      if (scored[k].second > bestScore) {
        bestScore = scored[k].second;
        bestIdx = k;
      }
      if (scored[k].first == chars[i]) currentScore = scored[k].second;
    }
    if (scored[bestIdx].first == chars[i]) continue;
    // 棄權＝不 override。沒有把握就什麼都不做。
    if (!(bestScore - currentScore > margin_)) continue;

    if (node->selectOverrideUnigram(
            targets[bestIdx],
            ReadingGrid::Node::OverrideType::
                kOverrideValueWithScoreFromTopUnigram)) {
      applied_[node.get()] = node;
      changed = true;
      // 改完就把攤平的字元序列同步回來。ParticleRuleDisambiguator 沒做這件事
      // （它一棒子只出手幾次，差別看不出來），但這顆模型會沿著整句一路出手 ——
      // 不同步的話後面每個位置都拿舊的左文去打分。
      std::vector<std::string> updated = splitUtf8(walk.chosenValueAt(ownerNode[i]));
      for (size_t k = 0; k < chars.size(); ++k) {
        if (ownerNode[k] == ownerNode[i] && offsetInNode[k] < updated.size()) {
          chars[k] = updated[offsetInNode[k]];
        }
      }
    }
  }
  return changed;
}

}  // namespace iBopomofo
