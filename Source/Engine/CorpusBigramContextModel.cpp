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

#include "CorpusBigramContextModel.h"

#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <string>

namespace McBopomofo {

namespace {

// std::stod throws on malformed input, and load() may run during input-method
// startup, so a single corrupt line must not take down the engine. Requires
// the whole field to parse as a finite double.
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

bool CorpusBigramContextModel::load(const std::string& path) {
  std::ifstream input(path);
  if (!input) {
    return false;
  }
  return load(input);
}

bool CorpusBigramContextModel::load(std::istream& input) {
  table_.clear();
  count_ = 0;

  std::string line;
  while (std::getline(input, line)) {
    if (!line.empty() && line.back() == '\r') {
      line.pop_back();
    }
    if (line.empty() || line[0] == '#') {
      continue;
    }
    size_t firstTab = line.find('\t');
    if (firstTab == std::string::npos) {
      continue;
    }
    size_t secondTab = line.find('\t', firstTab + 1);
    if (secondTab == std::string::npos) {
      continue;
    }
    std::string prev = line.substr(0, firstTab);
    std::string word = line.substr(firstTab + 1, secondTab - firstTab - 1);
    std::string pmiField = line.substr(secondTab + 1);
    // Tolerate a trailing tab-separated column if a future table adds one.
    size_t extraTab = pmiField.find('\t');
    if (extraTab != std::string::npos) {
      pmiField = pmiField.substr(0, extraTab);
    }
    double pmi = 0.0;
    if (prev.empty() || word.empty() || !ParseDouble(pmiField, &pmi)) {
      continue;
    }
    table_[prev][word] = pmi;
    ++count_;
  }
  return count_ > 0;
}

double CorpusBigramContextModel::score(const std::string& prevWord,
                                       const std::string& word, double& state) {
  // Bigram history for DP recombination: hypotheses ending in the same word
  // share a state and are merged (higher score wins). Casting the hash to a
  // double keeps distinct words well apart (>> the 1e-8 merge tolerance).
  state = static_cast<double>(std::hash<std::string>{}(word) & 0xFFFFFFFFULL);

  if (prevWord.empty() || lambda_ == 0.0) {
    return 0.0;
  }
  auto it = table_.find(prevWord);
  if (it == table_.end()) {
    return 0.0;
  }
  auto jt = it->second.find(word);
  if (jt == it->second.end()) {
    return 0.0;
  }
  return lambda_ * jt->second;
}

}  // namespace McBopomofo
