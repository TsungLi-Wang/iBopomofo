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

bool ParticleRuleDisambiguator::load(std::istream& input) {
  std::string line;
  while (std::getline(input, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    if (line.empty() || line[0] == '#') {
      continue;
    }
    std::vector<std::string> f = SplitBy(line, '\t');
    if (f.size() != 2 || f[1].empty()) {
      continue;  // 壞行略過，不讓表檔毀損害輸入法起不來
    }
    if (f[0] == "READING") {
      reading_ = f[1];
    } else if (f[0] == "FROM") {
      from_ = f[1];
    } else if (f[0] == "TO") {
      to_ = f[1];
    } else if (f[0] == "HEAD") {
      heads_.insert(f[1]);
    } else if (f[0] == "TAIL") {
      tails_.insert(f[1]);
    } else if (f[0] == "NEVER") {
      neverWords_.insert(f[1]);
    } else if (f[0] == "NEVERHEAD") {
      neverHeads_.insert(f[1]);
    } else if (f[0] == "NOUN") {
      nouns_.insert(f[1]);
    }
  }
  loaded_ = !reading_.empty() && !from_.empty() && !to_.empty() && !empty();
  return loaded_;
}

bool ParticleRuleDisambiguator::load(const std::string& path) {
  std::ifstream ifs(path);
  if (!ifs.is_open()) {
    return false;
  }
  return load(ifs);
}

bool ParticleRuleDisambiguator::shouldFlip(
    const std::vector<std::string>& chars, size_t index) const {
  // 句首或句尾沒有前後文，不動。
  if (index == 0 || index + 1 >= chars.size()) {
    return false;
  }
  const std::string& left = chars[index - 1];
  const std::string& right = chars[index + 1];

  // 「真的／有的／似的／別的」這種固定詞絕對不碰。
  if (neverHeads_.count(left) || neverWords_.count(left + chars[index])) {
    return false;
  }
  if (!heads_.count(left)) {
    return false;
  }
  if (!tails_.count(right)) {
    return false;
  }
  // 右邊兩個字如果是名詞（下場／出路／過法／到府），不要動。
  if (index + 2 < chars.size()) {
    const std::string pair = right + chars[index + 2];
    if (nouns_.count(pair) ||
        (dictionaryLookup_ && dictionaryLookup_(pair))) {
      return false;
    }
  }
  return true;
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
  std::vector<std::string> chars;
  std::vector<size_t> ownerNode;
  std::vector<size_t> offsetInNode;
  const std::vector<ReadingGrid::NodePtr>& nodes = walk.nodes;
  for (size_t n = 0; n < nodes.size(); ++n) {
    std::vector<std::string> nodeChars = SplitChars(nodes[n]->value());
    for (size_t k = 0; k < nodeChars.size(); ++k) {
      chars.push_back(nodeChars[k]);
      ownerNode.push_back(n);
      offsetInNode.push_back(k);
    }
  }

  bool changed = false;
  for (size_t i = 0; i < chars.size(); ++i) {
    if (chars[i] != from_) {
      continue;
    }
    if (!shouldFlip(chars, i)) {
      continue;
    }

    const ReadingGrid::NodePtr& node = nodes[ownerNode[i]];

    // 絕不跟使用者或 UOM 搶。
    if (node->isOverridden() && !isAppliedByUs(node)) {
      continue;
    }

    // 目標字串：把節點裡那一個字換掉，其餘不動。
    std::vector<std::string> nodeChars = SplitChars(node->value());
    if (offsetInNode[i] >= nodeChars.size()) {
      continue;
    }
    nodeChars[offsetInNode[i]] = to_;
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
    }
  }
  return changed;
}

}  // namespace McBopomofo
