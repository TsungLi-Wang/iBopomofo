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

#include "ParticleRuleDisambiguator.h"

#include <fstream>
#include <iterator>
#include <sstream>
#include <utility>

namespace McBopomofo {

using Formosa::Gramambular2::ReadingGrid;

namespace {

// 把 UTF-8 字串切成一個一個字。
std::vector<std::string> SplitChars(const std::string& s) {
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
    if (i + len > s.size()) {
      break;
    }
    out.push_back(s.substr(i, len));
    i += len;
  }
  return out;
}

std::vector<std::string> SplitBy(const std::string& s, char delim) {
  std::vector<std::string> out;
  std::stringstream ss(s);
  std::string item;
  while (std::getline(ss, item, delim)) {
    out.push_back(item);
  }
  return out;
}

}  // namespace

namespace {

// 舊格式（只有的／得那組）的暫存。載完之後會合成一條通用規則，
// 這樣引擎只留一套判斷路徑 —— 兩套邏輯遲早會漂掉。
struct LegacyTable {
  std::string reading, from, to;
  std::vector<std::string> heads, tails, nevers, neverHeads, nouns;
  bool any() const { return !heads.empty() || !tails.empty(); }
};

}  // namespace

std::unordered_set<std::string>* ParticleRuleDisambiguator::listNamed(
    const std::string& name) {
  auto it = lists_.find(name);
  if (it != lists_.end()) {
    return it->second.get();
  }
  auto inserted = lists_.emplace(
      name, std::make_unique<std::unordered_set<std::string>>());
  return inserted.first->second.get();
}

bool ParticleRuleDisambiguator::parseCondition(const std::string& text,
                                               Condition* out) {
  std::string body = text;
  out->negated = false;
  if (!body.empty() && body[0] == '!') {
    out->negated = true;
    body = body.substr(1);
  }
  if (body == "END") {
    out->slot = Condition::Slot::kAtEnd;
    return true;
  }
  if (body == "NOTEND") {
    out->slot = Condition::Slot::kAtEnd;
    out->negated = !out->negated;
    return true;
  }
  if (body == "START") {
    out->slot = Condition::Slot::kAtStart;
    return true;
  }
  if (body == "NOTSTART") {
    out->slot = Condition::Slot::kAtStart;
    out->negated = !out->negated;
    return true;
  }
  size_t eq = body.find('=');
  if (eq == std::string::npos) {
    return false;
  }
  const std::string slot = body.substr(0, eq);
  const std::string name = body.substr(eq + 1);
  if (slot == "L1") {
    out->slot = Condition::Slot::kL1;
  } else if (slot == "L2") {
    out->slot = Condition::Slot::kL2;
  } else if (slot == "L3") {
    out->slot = Condition::Slot::kL3;
  } else if (slot == "R3") {
    out->slot = Condition::Slot::kR3;
  } else if (slot == "R1") {
    out->slot = Condition::Slot::kR1;
  } else if (slot == "R2") {
    out->slot = Condition::Slot::kR2;
  } else if (slot == "LW2") {
    out->slot = Condition::Slot::kLW2;
  } else if (slot == "RW2") {
    out->slot = Condition::Slot::kRW2;
  } else if (slot == "L1T") {
    out->slot = Condition::Slot::kL1T;
  } else if (slot == "TR1") {
    out->slot = Condition::Slot::kTR1;
  } else {
    return false;
  }
  if (name == "@DICT") {
    out->useDictionary = true;
    out->list = nullptr;
  } else {
    out->useDictionary = false;
    out->list = listNamed(name);
  }
  return true;
}

bool ParticleRuleDisambiguator::load(std::istream& input) {
  LegacyTable legacy;
  std::string line;
  while (std::getline(input, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    if (line.empty() || line[0] == '#') {
      continue;
    }
    std::vector<std::string> f = SplitBy(line, '\t');
    if (f.size() < 2 || f[1].empty()) {
      continue;  // 壞行略過，不讓表檔毀損害輸入法起不來
    }
    // ── 舊格式 ──
    if (f[0] == "READING" && f.size() == 2) {
      legacy.reading = f[1];
    } else if (f[0] == "FROM") {
      legacy.from = f[1];
    } else if (f[0] == "TO") {
      legacy.to = f[1];
    } else if (f[0] == "HEAD") {
      legacy.heads.push_back(f[1]);
    } else if (f[0] == "TAIL") {
      legacy.tails.push_back(f[1]);
    } else if (f[0] == "NEVER") {
      legacy.nevers.push_back(f[1]);
    } else if (f[0] == "NEVERHEAD") {
      legacy.neverHeads.push_back(f[1]);
    } else if (f[0] == "NOUN") {
      legacy.nouns.push_back(f[1]);
      // ── 新格式 ──
    } else if (f[0] == "LIST" && f.size() >= 3 && !f[2].empty()) {
      listNamed(f[1])->insert(f[2]);
    } else if (f[0] == "RULE" && f.size() >= 5) {
      Rule rule;
      rule.name = f[1];
      rule.from = f[2];
      rule.to = f[3];
      if (rule.from.empty() || rule.to.empty() || rule.from == rule.to) {
        continue;
      }
      bool ok = true;
      for (const std::string& part : SplitBy(f[4], ';')) {
        if (part.empty()) {
          continue;
        }
        Condition cond;
        if (!parseCondition(part, &cond)) {
          ok = false;
          break;
        }
        rule.conditions.push_back(cond);
      }
      if (ok && !rule.conditions.empty()) {
        rules_.push_back(std::move(rule));
      }
    }
  }

  // 舊格式 → 一條通用規則。條件與原本 shouldFlip 逐項對應：
  //   左邊是動詞 且 右邊是結果補語 且 左邊不是「我你他真有」
  //   且 左1+目標不是「真的／有的」 且 右邊兩字不是名詞、也不是詞庫收的詞
  if (legacy.any() && !legacy.from.empty() && !legacy.to.empty()) {
    const std::string tag = "_legacy_" + legacy.from + legacy.to + "_";
    for (const std::string& v : legacy.heads) listNamed(tag + "HEAD")->insert(v);
    for (const std::string& v : legacy.tails) listNamed(tag + "TAIL")->insert(v);
    for (const std::string& v : legacy.nevers) listNamed(tag + "NEVER")->insert(v);
    for (const std::string& v : legacy.neverHeads)
      listNamed(tag + "NEVERHEAD")->insert(v);
    for (const std::string& v : legacy.nouns) listNamed(tag + "NOUN")->insert(v);

    Rule rule;
    rule.name = legacy.from + "→" + legacy.to;
    rule.from = legacy.from;
    rule.to = legacy.to;
    const char* conds[] = {"NOTSTART", "NOTEND", nullptr};
    for (int i = 0; conds[i] != nullptr; ++i) {
      Condition c;
      if (parseCondition(conds[i], &c)) rule.conditions.push_back(c);
    }
    const std::string more[] = {
        "L1=" + tag + "HEAD",      "R1=" + tag + "TAIL",
        "!L1=" + tag + "NEVERHEAD", "!L1T=" + tag + "NEVER",
        "!RW2=" + tag + "NOUN",    "!RW2=@DICT"};
    for (const std::string& m : more) {
      Condition c;
      if (parseCondition(m, &c)) rule.conditions.push_back(c);
    }
    rules_.push_back(std::move(rule));
  }

  loaded_ = !rules_.empty();
  return loaded_;
}

bool ParticleRuleDisambiguator::load(const std::string& path) {
  std::ifstream ifs(path);
  if (!ifs.is_open()) {
    return false;
  }
  return load(ifs);
}

bool ParticleRuleDisambiguator::conditionHolds(
    const Condition& cond, const std::vector<std::string>& chars,
    size_t i) const {
  const size_t n = chars.size();
  bool got = false;
  switch (cond.slot) {
    case Condition::Slot::kAtEnd:
      got = (i + 1 == n);
      return cond.negated ? !got : got;
    case Condition::Slot::kAtStart:
      got = (i == 0);
      return cond.negated ? !got : got;
    default:
      break;
  }

  std::string value;
  bool have = false;
  switch (cond.slot) {
    case Condition::Slot::kL1:
      if (i >= 1) { value = chars[i - 1]; have = true; }
      break;
    case Condition::Slot::kL2:
      if (i >= 2) { value = chars[i - 2]; have = true; }
      break;
    case Condition::Slot::kR1:
      if (i + 1 < n) { value = chars[i + 1]; have = true; }
      break;
    case Condition::Slot::kR2:
      if (i + 2 < n) { value = chars[i + 2]; have = true; }
      break;
    case Condition::Slot::kL3:
      if (i >= 3) { value = chars[i - 3]; have = true; }
      break;
    case Condition::Slot::kR3:
      if (i + 3 < n) { value = chars[i + 3]; have = true; }
      break;
    case Condition::Slot::kLW2:
      if (i >= 2) { value = chars[i - 2] + chars[i - 1]; have = true; }
      break;
    case Condition::Slot::kRW2:
      if (i + 2 < n) { value = chars[i + 1] + chars[i + 2]; have = true; }
      break;
    case Condition::Slot::kL1T:
      if (i >= 1) { value = chars[i - 1] + chars[i]; have = true; }
      break;
    case Condition::Slot::kTR1:
      if (i + 1 < n) { value = chars[i] + chars[i + 1]; have = true; }
      break;
    default:
      break;
  }

  if (have) {
    got = cond.useDictionary
              ? (dictionaryLookup_ && dictionaryLookup_(value))
              : (cond.list != nullptr && cond.list->count(value) > 0);
  }
  return cond.negated ? !got : got;
}

std::string ParticleRuleDisambiguator::replacementFor(
    const std::vector<std::string>& chars, size_t index) const {
  if (index >= chars.size()) {
    return std::string();
  }
  for (const Rule& rule : rules_) {
    if (rule.from != chars[index]) {
      continue;
    }
    bool all = true;
    for (const Condition& cond : rule.conditions) {
      if (!conditionHolds(cond, chars, index)) {
        all = false;
        break;
      }
    }
    if (all) {
      return rule.to;
    }
  }
  return std::string();
}

bool ParticleRuleDisambiguator::shouldFlip(
    const std::vector<std::string>& chars, size_t index) const {
  return !replacementFor(chars, index).empty();
}

std::string ParticleRuleDisambiguator::ruleNameFor(
    const std::vector<std::string>& chars, size_t index) const {
  for (const Rule& rule : rules_) {
    if (rule.from != chars[index]) continue;
    bool all = true;
    for (const Condition& c : rule.conditions) {
      if (!conditionHolds(c, chars, index)) { all = false; break; }
    }
    if (all) return rule.name;
  }
  return std::string();
}

bool ParticleRuleDisambiguator::rescoreWalk(const ReadingGrid::WalkResult& walk) {
  if (empty()) {
    return false;
  }

  // 清掉 grid 已經不持有的節點。
  for (auto it = applied_.begin(); it != applied_.end();) {
    it = it->second.expired() ? applied_.erase(it) : std::next(it);
  }

  // 把整條路徑攤平成字元序列，同時記住每個字屬於哪個節點的第幾個字。
  //
  // ⚠️ 一定要用 walk.chosenValueAt(n)，不能用 nodes[n]->value()。
  // chosenValueAt 的優先序是「節點覆寫 > 情境模型 DP 選的 > value()（最高頻）」，
  // value() 是最低優先序的那一個。開了情境 walk 或神經重排之後，DP 常常選的
  // 不是最高頻候選 —— 這時 value() 給的字跟使用者實際看到的不一樣，
  // 規則就會拿錯的文字去比對條件、或以為不必出手。
  //
  // 2026-08-10 實測：這個 bug 讓規則層在封存集少修約三成
  //（模擬器說會修 75 題，真引擎只修了 53 題）。v2.15.0 出貨的「的／得」規則
  // 也一直讀到錯的文字。
  std::vector<std::string> chars;
  std::vector<size_t> ownerNode;
  std::vector<size_t> offsetInNode;
  const std::vector<ReadingGrid::NodePtr>& nodes = walk.nodes;
  for (size_t n = 0; n < nodes.size(); ++n) {
    std::vector<std::string> nodeChars = SplitChars(walk.chosenValueAt(n));
    for (size_t k = 0; k < nodeChars.size(); ++k) {
      chars.push_back(nodeChars[k]);
      ownerNode.push_back(n);
      offsetInNode.push_back(k);
    }
  }

  bool changed = false;
  for (size_t i = 0; i < chars.size(); ++i) {
    // 規則自己會比對「引擎選了哪個字」，沒有規則出手就回空字串。
    const std::string replacement = replacementFor(chars, i);
    if (replacement.empty()) {
      continue;
    }

    const ReadingGrid::NodePtr& node = nodes[ownerNode[i]];

    // 絕不跟使用者或 UOM 搶。
    if (node->isOverridden() && !isAppliedByUs(node)) {
      continue;
    }

    // 目標字串：把節點裡那一個字換掉，其餘不動。
    // 同樣要用 chosenValueAt —— 拿 value() 組出來的字串會跟節點目前的選擇
    // 不一致，selectOverrideUnigram 找不到那個候選就靜默失敗。
    std::vector<std::string> nodeChars =
        SplitChars(walk.chosenValueAt(ownerNode[i]));
    if (offsetInNode[i] >= nodeChars.size()) {
      continue;
    }
    nodeChars[offsetInNode[i]] = replacement;
    std::string target;
    for (const std::string& c : nodeChars) {
      target += c;
    }

    // selectOverrideUnigram 只有在該候選真的存在於節點裡才會成功，
    // 所以引擎層的保證不變：字是被重新挑選，不是被生成出來的。
    if (node->selectOverrideUnigram(
            target,
            ReadingGrid::Node::OverrideType::
                kOverrideValueWithScoreFromTopUnigram)) {
      applied_[node.get()] = node;
      changed = true;
      if (trace_ != nullptr) {
        trace_->record(i, replacement, DecisionTrace::Layer::kGrammarRule,
                       ruleNameFor(chars, i));
      }
    }
  }
  return changed;
}

}  // namespace McBopomofo
