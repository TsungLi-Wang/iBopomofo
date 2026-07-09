// Copyright (c) 2026 and onwards The McBopomofo Authors.

#include "CharNGramPathScorer.h"

#include <algorithm>
#include <cmath>
#include <fstream>
#include <sstream>

namespace McBopomofo {

namespace {
constexpr char kSep = '\x1f';
}  // namespace

bool CharNGramPathScorer::load(const std::string& path) {
  uni_.clear();
  bi_.clear();
  tri_.clear();
  biLeft_.clear();
  triLeft_.clear();
  totalUni_ = 0;
  vocab_ = 1;
  loaded_ = false;

  std::ifstream in(path);
  if (!in) return false;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#') continue;
    std::istringstream iss(line);
    int order = 0;
    std::string key;
    double count = 0;
    if (!(iss >> order)) continue;
    // key may contain spaces? we use \x1f; read rest until last tab
    size_t t1 = line.find('\t');
    if (t1 == std::string::npos) continue;
    size_t t2 = line.find('\t', t1 + 1);
    if (t2 == std::string::npos) continue;
    key = line.substr(t1 + 1, t2 - t1 - 1);
    try {
      count = std::stod(line.substr(t2 + 1));
    } catch (...) {
      continue;
    }
    if (order == 1) {
      uni_[key] = count;
      totalUni_ += count;
    } else if (order == 2) {
      bi_[key] = count;
      size_t p = key.find(kSep);
      if (p != std::string::npos) {
        biLeft_[key.substr(0, p)] += count;
      }
    } else if (order == 3) {
      tri_[key] = count;
      size_t p1 = key.find(kSep);
      size_t p2 = key.find(kSep, p1 == std::string::npos ? 0 : p1 + 1);
      if (p1 != std::string::npos && p2 != std::string::npos) {
        triLeft_[key.substr(0, p2)] += count;
      }
    }
  }
  vocab_ = std::max<size_t>(1, uni_.size());
  loaded_ = totalUni_ > 0;
  return loaded_;
}

std::vector<std::string> CharNGramPathScorer::flattenChars(
    const std::vector<std::string>& words) {
  std::vector<std::string> chars;
  chars.emplace_back("<s>");
  for (const auto& w : words) {
    // UTF-8 iterate codepoints simply by bytes for CJK (3-byte) and ASCII
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
  chars.emplace_back("</s>");
  return chars;
}

double CharNGramPathScorer::logP(const std::string& a, const std::string& b,
                                 const std::string& c) const {
  // trigram with backoff to bigram/unigram; log10
  std::string tkey = a + kSep + b + kSep + c;
  std::string tleft = a + kSep + b;
  auto tit = tri_.find(tkey);
  auto tlit = triLeft_.find(tleft);
  if (tit != tri_.end() && tlit != triLeft_.end() && tlit->second > 0) {
    return std::log10((tit->second + kAlpha) /
                      (tlit->second + kAlpha * static_cast<double>(vocab_)));
  }
  std::string bkey = b + kSep + c;
  auto bit = bi_.find(bkey);
  auto blit = biLeft_.find(b);
  if (bit != bi_.end() && blit != biLeft_.end() && blit->second > 0) {
    return std::log10((bit->second + kAlpha) /
                      (blit->second + kAlpha * static_cast<double>(vocab_)));
  }
  auto uit = uni_.find(c);
  double uc = uit == uni_.end() ? 0.0 : uit->second;
  return std::log10((uc + kAlpha) /
                    (totalUni_ + kAlpha * static_cast<double>(vocab_)));
}

double CharNGramPathScorer::scoreSentence(
    const std::vector<std::string>& words) {
  if (!loaded_ || words.empty()) return 0.0;
  auto chars = flattenChars(words);
  if (chars.size() < 3) return 0.0;
  double s = 0.0;
  for (size_t i = 2; i < chars.size(); ++i) {
    s += logP(chars[i - 2], chars[i - 1], chars[i]);
  }
  return s;
}

}  // namespace McBopomofo
