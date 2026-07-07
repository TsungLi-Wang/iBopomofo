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

#include "ConfusionPairDisambiguator.h"

#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <vector>

#include "UTF8Helper.h"

namespace McBopomofo {

using Formosa::Gramambular2::ReadingGrid;

namespace {

constexpr char kBeginToken[] = "^";
constexpr char kEndToken[] = "$";
constexpr char kDigitToken[] = "#D";
constexpr char kAlphaToken[] = "#A";
constexpr char kOtherToken[] = "#O";

uint32_t DecodeUTF8CodePoint(const std::string& s) {
  if (s.empty()) {
    return 0;
  }
  const auto* bytes = reinterpret_cast<const unsigned char*>(s.data());
  unsigned char c = bytes[0];
  if ((c & 0x80) == 0) {
    return c;
  }
  if ((c & 0xE0) == 0xC0 && s.size() >= 2) {
    return ((c & 0x1FU) << 6) | (bytes[1] & 0x3FU);
  }
  if ((c & 0xF0) == 0xE0 && s.size() >= 3) {
    return ((c & 0x0FU) << 12) | ((bytes[1] & 0x3FU) << 6) | (bytes[2] & 0x3FU);
  }
  if ((c & 0xF8) == 0xF0 && s.size() >= 4) {
    return ((c & 0x07U) << 18) | ((bytes[1] & 0x3FU) << 12) |
           ((bytes[2] & 0x3FU) << 6) | (bytes[3] & 0x3FU);
  }
  return 0;
}

std::vector<std::string> SplitTabs(const std::string& s) {
  std::vector<std::string> out;
  std::string current;
  for (char c : s) {
    if (c == '\t') {
      out.push_back(current);
      current.clear();
    } else {
      current.push_back(c);
    }
  }
  out.push_back(current);
  return out;
}

double Lookup(const std::unordered_map<std::string, double>& table,
              const std::string& token) {
  auto it = table.find(token);
  return it == table.end() ? 0.0 : it->second;
}

// std::stod throws on malformed input, and load() runs during KeyHandler
// init, so a single corrupt line in the table must not take down the IME.
// Requires the whole field to parse as a finite double.
bool ParseDouble(const std::string& s, double* out) {
  if (s.empty()) {
    return false;
  }
  errno = 0;
  char* end = nullptr;
  double value = strtod(s.c_str(), &end);
  if (end != s.c_str() + s.size() || errno == ERANGE || !std::isfinite(value)) {
    return false;
  }
  *out = value;
  return true;
}

}  // namespace

// Must stay in sync with normalize_token() in build_confusion_pair_table.py.
std::string ConfusionPairDisambiguator::NormalizeContextToken(
    const std::string& utf8Char) {
  if (utf8Char.empty()) {
    return kOtherToken;
  }
  uint32_t cp = DecodeUTF8CodePoint(utf8Char);
  bool isCJK = (cp >= 0x4E00 && cp <= 0x9FFF) ||
               (cp >= 0x3400 && cp <= 0x4DBF) ||
               (cp >= 0xF900 && cp <= 0xFAFF);
  if (isCJK) {
    return utf8Char;
  }
  static const std::string kKeptPunctuation = "，。！？、；：…—（）「」『』,.!?;:()";
  if (kKeptPunctuation.find(utf8Char) != std::string::npos) {
    return utf8Char;
  }
  if ((cp >= '0' && cp <= '9') || (cp >= 0xFF10 && cp <= 0xFF19)) {
    return kDigitToken;
  }
  if ((cp >= 'A' && cp <= 'Z') || (cp >= 'a' && cp <= 'z')) {
    return kAlphaToken;
  }
  return kOtherToken;
}

bool ConfusionPairDisambiguator::load(const std::string& path) {
  std::ifstream input(path);
  if (!input.good()) {
    return false;
  }
  return load(input);
}

bool ConfusionPairDisambiguator::load(std::istream& input) {
  pairs_.clear();
  applied_.clear();

  Pair* current = nullptr;
  std::string line;
  while (std::getline(input, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    if (line.empty() || line[0] == '#') {
      continue;
    }
    std::vector<std::string> fields = SplitTabs(line);
    const std::string& kind = fields[0];
    if (kind == "PAIR" && fields.size() == 4) {
      Pair pair;
      pair.reading = fields[1];
      pair.defaultValue = fields[2];
      pair.altValue = fields[3];
      current = &pairs_[pair.reading];
      *current = std::move(pair);
      continue;
    }
    if (current == nullptr) {
      continue;
    }
    double value = 0;
    if (kind == "PRIOR" && fields.size() == 2 &&
        ParseDouble(fields[1], &value)) {
      current->prior = value;
    } else if (kind == "THRESHOLD" && fields.size() == 2 &&
               ParseDouble(fields[1], &value)) {
      current->threshold = value;
    } else if (kind == "L" && fields.size() == 3 &&
               ParseDouble(fields[2], &value)) {
      current->left[fields[1]] = value;
    } else if (kind == "R" && fields.size() == 3 &&
               ParseDouble(fields[2], &value)) {
      current->right[fields[1]] = value;
    } else if (kind == "LB" && fields.size() == 3 &&
               ParseDouble(fields[2], &value)) {
      current->leftBigram[fields[1]] = value;
    } else if (kind == "RB" && fields.size() == 3 &&
               ParseDouble(fields[2], &value)) {
      current->rightBigram[fields[1]] = value;
    }
  }
  return isLoaded();
}

void ConfusionPairDisambiguator::reset() { applied_.clear(); }

bool ConfusionPairDisambiguator::isAppliedByUs(
    const ReadingGrid::NodePtr& node) {
  auto it = applied_.find(node.get());
  if (it == applied_.end()) {
    return false;
  }
  // Guard against a stale entry whose address has been reused by a new node.
  if (it->second.lock() != node) {
    applied_.erase(it);
    return false;
  }
  return true;
}

namespace {

std::vector<std::string> SplitReading(const std::string& reading) {
  std::vector<std::string> out;
  std::string current;
  for (char c : reading) {
    if (c == ReadingGrid::kDefaultSeparator[0]) {
      out.push_back(current);
      current.clear();
    } else {
      current.push_back(c);
    }
  }
  out.push_back(current);
  return out;
}

std::string JoinChars(const std::vector<std::string>& chars) {
  std::string out;
  for (const std::string& c : chars) {
    out += c;
  }
  return out;
}

}  // namespace

bool ConfusionPairDisambiguator::rescoreWalk(
    const ReadingGrid::WalkResult& walkResult) {
  if (pairs_.empty()) {
    return false;
  }

  // Drop entries for nodes the grid no longer holds.
  for (auto it = applied_.begin(); it != applied_.end();) {
    it = it->second.expired() ? applied_.erase(it) : std::next(it);
  }

  bool changed = false;
  const std::vector<ReadingGrid::NodePtr>& nodes = walkResult.nodes;

  // Flat character sequence of the whole walked path, so context (including
  // bigrams) can cross node boundaries. flat[nodeOffset[i] + k] is character
  // k of node i; kept in sync when a flip changes a node's value.
  std::vector<std::string> flat;
  std::vector<size_t> nodeOffset(nodes.size(), 0);
  for (size_t i = 0; i < nodes.size(); ++i) {
    nodeOffset[i] = flat.size();
    std::vector<std::string> nodeChars = Split(nodes[i]->value());
    flat.insert(flat.end(), nodeChars.begin(), nodeChars.end());
  }

  for (size_t i = 0; i < nodes.size(); ++i) {
    const ReadingGrid::NodePtr& node = nodes[i];

    // Never fight the user or the user override model.
    bool appliedByUs = isAppliedByUs(node);
    if (node->isOverridden() && !appliedByUs) {
      continue;
    }

    // A node is eligible when one of its syllables carries a confusion pair:
    // a span-1 ㄗㄞˋ node (在/再), but also a multi-syllable dictionary node
    // that has a "twin" unigram differing only at that character (the real
    // dictionary contains both 我在 and 我再, and the unigram walk always
    // favors the frequent one).
    std::vector<std::string> syllables = SplitReading(node->reading());
    std::vector<std::string> chars = Split(node->value());
    if (chars.size() != syllables.size()) {
      // Symbol/emoji or annotation nodes; not our business.
      continue;
    }

    for (size_t k = 0; k < syllables.size(); ++k) {
      auto pairIt = pairs_.find(syllables[k]);
      if (pairIt == pairs_.end()) {
        continue;
      }
      const Pair& pair = pairIt->second;

      chars = Split(node->value());  // re-read in case an earlier k flipped
      const std::string& currentChar = chars[k];
      if (currentChar != pair.defaultValue && currentChar != pair.altValue) {
        continue;
      }

      // Context from the flat path sequence. Bigrams may include one
      // boundary token and exist only when there is at least one real
      // neighbor character on that side; must stay in sync with
      // context_tokens() in build_confusion_pair_table.py.
      const size_t p = nodeOffset[i] + k;
      std::string leftToken =
          p > 0 ? NormalizeContextToken(flat[p - 1]) : kBeginToken;
      std::string rightToken = p + 1 < flat.size()
                                   ? NormalizeContextToken(flat[p + 1])
                                   : kEndToken;

      // Bigram evidence first, single-character backoff otherwise.
      double leftTerm = Lookup(pair.left, leftToken);
      if (p >= 1) {
        std::string left2 =
            p >= 2 ? NormalizeContextToken(flat[p - 2]) : kBeginToken;
        auto it = pair.leftBigram.find(left2 + leftToken);
        if (it != pair.leftBigram.end()) {
          leftTerm = it->second;
        }
      }
      double rightTerm = Lookup(pair.right, rightToken);
      if (p + 1 < flat.size()) {
        std::string right2 = p + 2 < flat.size()
                                 ? NormalizeContextToken(flat[p + 2])
                                 : kEndToken;
        auto it = pair.rightBigram.find(rightToken + right2);
        if (it != pair.rightBigram.end()) {
          rightTerm = it->second;
        }
      }

      double score = leftTerm + rightTerm + pair.prior;
      const std::string& targetChar =
          score > pair.threshold ? pair.altValue : pair.defaultValue;
      if (targetChar == currentChar) {
        continue;
      }

      std::vector<std::string> targetChars = chars;
      targetChars[k] = targetChar;
      std::string targetValue = JoinChars(targetChars);

      // If the target is what the engine would pick on its own, retract our
      // override instead of stacking a new one.
      if (appliedByUs && !node->unigrams().empty() &&
          node->unigrams()[0].value() == targetValue) {
        node->reset();
        applied_.erase(node.get());
        appliedByUs = false;
        changed = true;
        flat[p] = Split(node->value())[k];
        continue;
      }

      // selectOverrideUnigram only succeeds when the twin value actually
      // exists among the node's unigrams, which keeps the engine-level
      // guarantee: text is re-picked, never generated.
      if (node->selectOverrideUnigram(
              targetValue,
              ReadingGrid::Node::OverrideType::
                  kOverrideValueWithScoreFromTopUnigram)) {
        applied_[node.get()] = node;
        appliedByUs = true;
        changed = true;
        flat[p] = targetChar;
      }
    }
  }
  return changed;
}

}  // namespace McBopomofo
