// New north-star harness: character-level homophone disambiguation.
//
// Shipping scorer config (default): contextual bigram λ=0.75 + v2c path rerank
// ν=0.75, N=10. No UserOverrideModel / personalization (clean measure).
//
// Usage:
//   newstar_homophone_eval <items.jsonl> <data.txt> <word-bigrams.tsv> \
//       <path-char-lstm.bin> [mode] [lambda] [nu]
//
// mode: shipping (default) | walk
//
// Reports weighted char accuracy by pair_id, split by tier and split.

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "ParticleRuleDisambiguator.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

using Formosa::Gramambular2::ReadingGrid;
using McBopomofo::CorpusBigramContextModel;
using McBopomofo::NeuralLMPathScorer;
using McBopomofo::ParselessLM;

namespace {

// --- UTF-8 helpers (codepoint as "char" for Chinese BMP; no grapheme clusters) ---

std::vector<std::string> utf8Chars(const std::string& s) {
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
    } else {
      ++i;
      continue;
    }
    if (i + len > s.size()) break;
    out.push_back(s.substr(i, len));
    i += len;
  }
  return out;
}

// --- Minimal JSON string/number/array field extractors (JSONL line-local) ---

std::string jsonUnescape(const std::string& s) {
  std::string o;
  o.reserve(s.size());
  for (size_t i = 0; i < s.size(); ++i) {
    if (s[i] == '\\' && i + 1 < s.size()) {
      char n = s[i + 1];
      if (n == '"' || n == '\\' || n == '/') {
        o.push_back(n);
        ++i;
      } else if (n == 'n') {
        o.push_back('\n');
        ++i;
      } else if (n == 't') {
        o.push_back('\t');
        ++i;
      } else {
        o.push_back(s[i]);
      }
    } else {
      o.push_back(s[i]);
    }
  }
  return o;
}

bool jsonStringField(const std::string& line, const std::string& key,
                     std::string* out) {
  const std::string pat = "\"" + key + "\"";
  size_t k = line.find(pat);
  if (k == std::string::npos) return false;
  size_t colon = line.find(':', k + pat.size());
  if (colon == std::string::npos) return false;
  size_t q1 = line.find('"', colon + 1);
  if (q1 == std::string::npos) return false;
  size_t q2 = q1 + 1;
  while (q2 < line.size()) {
    if (line[q2] == '"' && line[q2 - 1] != '\\') break;
    ++q2;
  }
  if (q2 >= line.size()) return false;
  *out = jsonUnescape(line.substr(q1 + 1, q2 - q1 - 1));
  return true;
}

bool jsonIntField(const std::string& line, const std::string& key, int* out) {
  const std::string pat = "\"" + key + "\"";
  size_t k = line.find(pat);
  if (k == std::string::npos) return false;
  size_t colon = line.find(':', k + pat.size());
  if (colon == std::string::npos) return false;
  size_t i = colon + 1;
  while (i < line.size() && (line[i] == ' ' || line[i] == '\t')) ++i;
  size_t j = i;
  if (j < line.size() && (line[j] == '-' || line[j] == '+')) ++j;
  while (j < line.size() && line[j] >= '0' && line[j] <= '9') ++j;
  if (j == i || (j == i + 1 && (line[i] == '-' || line[i] == '+'))) return false;
  *out = std::stoi(line.substr(i, j - i));
  return true;
}

bool jsonDoubleField(const std::string& line, const std::string& key,
                     double* out) {
  const std::string pat = "\"" + key + "\"";
  size_t k = line.find(pat);
  if (k == std::string::npos) return false;
  size_t colon = line.find(':', k + pat.size());
  if (colon == std::string::npos) return false;
  size_t i = colon + 1;
  while (i < line.size() && (line[i] == ' ' || line[i] == '\t')) ++i;
  size_t j = i;
  while (j < line.size() &&
         (std::isdigit(static_cast<unsigned char>(line[j])) || line[j] == '.' ||
          line[j] == '-' || line[j] == '+' || line[j] == 'e' ||
          line[j] == 'E')) {
    ++j;
  }
  if (j == i) return false;
  *out = std::stod(line.substr(i, j - i));
  return true;
}

bool jsonStringArrayField(const std::string& line, const std::string& key,
                          std::vector<std::string>* out) {
  out->clear();
  const std::string pat = "\"" + key + "\"";
  size_t k = line.find(pat);
  if (k == std::string::npos) return false;
  size_t lb = line.find('[', k + pat.size());
  if (lb == std::string::npos) return false;
  size_t rb = line.find(']', lb + 1);
  if (rb == std::string::npos) return false;
  std::string body = line.substr(lb + 1, rb - lb - 1);
  size_t i = 0;
  while (i < body.size()) {
    while (i < body.size() && (body[i] == ' ' || body[i] == ',' || body[i] == '\t'))
      ++i;
    if (i >= body.size()) break;
    if (body[i] != '"') return false;
    size_t q1 = i;
    size_t q2 = q1 + 1;
    while (q2 < body.size()) {
      if (body[q2] == '"' && body[q2 - 1] != '\\') break;
      ++q2;
    }
    if (q2 >= body.size()) return false;
    out->push_back(jsonUnescape(body.substr(q1 + 1, q2 - q1 - 1)));
    i = q2 + 1;
  }
  return true;
}

// --- Engine feed ---

std::vector<std::string> splitSyllables(const std::string& readings) {
  std::vector<std::string> result;
  // Accept both '-' and space as separators; collapse whitespace.
  std::string norm;
  for (char c : readings) {
    if (c == ' ' || c == '\t') {
      if (!norm.empty() && norm.back() != '-') norm.push_back('-');
    } else {
      norm.push_back(c);
    }
  }
  while (!norm.empty() && norm.back() == '-') norm.pop_back();
  size_t start = 0;
  for (size_t i = 0; i < norm.size(); ++i) {
    if (norm[i] == '-') {
      if (i > start) result.push_back(norm.substr(start, i - start));
      start = i + 1;
    }
  }
  if (start < norm.size()) result.push_back(norm.substr(start));
  return result;
}

ReadingGrid makeGrid(ParselessLM* lm) {
  ReadingGrid grid(std::shared_ptr<Formosa::Gramambular2::LanguageModel>(
      lm, [](Formosa::Gramambular2::LanguageModel*) {}));
  grid.setReadingSeparator("-");
  return grid;
}

bool feed(ReadingGrid& grid, const std::string& readings) {
  for (const auto& syl : splitSyllables(readings)) {
    if (syl.empty()) continue;
    grid.setCursor(grid.length());
    if (!grid.insertReading(syl)) return false;
  }
  return true;
}

std::string joined(const ReadingGrid::WalkResult& w) {
  std::string s;
  for (size_t i = 0; i < w.nodes.size(); ++i) s += w.chosenValueAt(i);
  return s;
}

bool charHasReading(ParselessLM& lm, const std::string& ch,
                    const std::string& reading) {
  auto found = lm.getReadings(ch);
  for (const auto& fr : found) {
    // FoundReading has .reading field — check API
    if (fr.reading == reading) return true;
  }
  // Also accept if any unigram under that reading equals ch
  auto unigrams = lm.getUnigrams(reading);
  for (const auto& u : unigrams) {
    if (u.value() == ch) return true;
  }
  return false;
}

struct Item {
  std::string sentence_id;
  std::string sentence;
  int target_index = -1;
  std::string target_char;
  std::vector<std::string> wrong_chars;
  std::string reading;
  std::string pair_id;
  int n_way = 0;
  double weight = 1.0;
  std::string tier;   // single | multi
  std::string split;  // train | heldout
  std::string domain;
  std::string full_reading;
  std::string source;
  size_t line_no = 0;
};

struct Reject {
  size_t line_no = 0;
  std::string sentence_id;
  std::string reason;
};

bool parseItem(const std::string& line, size_t line_no, Item* it,
               std::string* err) {
  it->line_no = line_no;
  if (!jsonStringField(line, "sentence_id", &it->sentence_id) ||
      !jsonStringField(line, "sentence", &it->sentence) ||
      !jsonIntField(line, "target_index", &it->target_index) ||
      !jsonStringField(line, "target_char", &it->target_char) ||
      !jsonStringArrayField(line, "wrong_chars", &it->wrong_chars) ||
      !jsonStringField(line, "reading", &it->reading) ||
      !jsonStringField(line, "pair_id", &it->pair_id) ||
      !jsonIntField(line, "n_way", &it->n_way) ||
      !jsonDoubleField(line, "weight", &it->weight) ||
      !jsonStringField(line, "tier", &it->tier) ||
      !jsonStringField(line, "split", &it->split) ||
      !jsonStringField(line, "full_reading", &it->full_reading)) {
    *err = "missing_required_field";
    return false;
  }
  jsonStringField(line, "domain", &it->domain);
  jsonStringField(line, "source", &it->source);
  if (it->tier != "single" && it->tier != "multi") {
    *err = "bad_tier";
    return false;
  }
  if (it->split != "train" && it->split != "heldout") {
    *err = "bad_split";
    return false;
  }
  return true;
}

bool validateItem(ParselessLM& lm, const Item& it, std::string* reason) {
  auto chars = utf8Chars(it.sentence);
  if (it.target_index < 0 ||
      static_cast<size_t>(it.target_index) >= chars.size()) {
    *reason = "target_index_oob";
    return false;
  }
  if (chars[static_cast<size_t>(it.target_index)] != it.target_char) {
    *reason = "sentence_target_mismatch";
    return false;
  }
  int occ = 0;
  for (const auto& c : chars) {
    if (c == it.target_char) ++occ;
  }
  if (occ != 1) {
    *reason = "target_char_not_unique_in_sentence";
    return false;
  }
  if (it.n_way != 1 + static_cast<int>(it.wrong_chars.size())) {
    *reason = "n_way_mismatch";
    return false;
  }
  if (!charHasReading(lm, it.target_char, it.reading)) {
    *reason = "target_char_reading_mismatch";
    return false;
  }
  for (const auto& w : it.wrong_chars) {
    if (!charHasReading(lm, w, it.reading)) {
      *reason = "wrong_char_reading_mismatch:" + w;
      return false;
    }
  }
  auto syls = splitSyllables(it.full_reading);
  if (syls.size() != chars.size()) {
    *reason = "full_reading_len_mismatch";
    return false;
  }
  return true;
}

struct PairAgg {
  std::string pair_id;
  int n_way = 0;
  int items = 0;
  int correct = 0;
  double weight = 0.0;  // last-seen / representative weight for the pair
};

struct GroupAgg {
  int items = 0;
  int correct = 0;
  // pair_id -> agg
  std::map<std::string, PairAgg> pairs;
  // multi: sentence_id -> (targets total, targets correct)
  std::map<std::string, std::pair<int, int>> multi_sent;
};

void addResult(GroupAgg* g, const Item& it, bool ok) {
  ++g->items;
  if (ok) ++g->correct;
  auto& p = g->pairs[it.pair_id];
  p.pair_id = it.pair_id;
  p.n_way = it.n_way;
  p.weight = it.weight;
  ++p.items;
  if (ok) ++p.correct;
  if (it.tier == "multi") {
    auto& ms = g->multi_sent[it.sentence_id];
    ++ms.first;
    if (ok) ++ms.second;
  }
}

void printGroup(const std::string& title, const GroupAgg& g) {
  std::cout << "\n=== " << title << " ===\n";
  if (g.items == 0) {
    std::cout << "(no items)\n";
    return;
  }
  double raw = 100.0 * static_cast<double>(g.correct) / g.items;
  double wSum = 0.0;
  double wAcc = 0.0;
  std::vector<PairAgg> rows;
  for (const auto& kv : g.pairs) rows.push_back(kv.second);
  // worst-first by raw_acc then pair_id
  std::sort(rows.begin(), rows.end(), [](const PairAgg& a, const PairAgg& b) {
    double aa = a.items ? static_cast<double>(a.correct) / a.items : 0;
    double bb = b.items ? static_cast<double>(b.correct) / b.items : 0;
    if (aa != bb) return aa < bb;
    return a.pair_id < b.pair_id;
  });
  for (const auto& p : rows) {
    double acc = p.items ? static_cast<double>(p.correct) / p.items : 0;
    wSum += p.weight;
    wAcc += p.weight * acc;
  }
  double weighted = wSum > 0 ? 100.0 * wAcc / wSum : 0.0;
  std::cout << "headline_weighted_char_acc " << weighted << "%\n";
  std::cout << "headline_unweighted_char_acc " << raw << "%  (" << g.correct
            << "/" << g.items << ")\n";
  std::cout << "pair_id | n_way | items | correct | raw_acc | weight | w_contrib\n";
  for (const auto& p : rows) {
    double acc = p.items ? static_cast<double>(p.correct) / p.items : 0;
    double contrib = (wSum > 0) ? (p.weight * acc / wSum) * 100.0 : 0;
    std::cout << p.pair_id << " | " << p.n_way << " | " << p.items << " | "
              << p.correct << " | " << (100.0 * acc) << "% | " << p.weight
              << " | " << contrib << "%\n";
  }
  if (!g.multi_sent.empty()) {
    int fullOk = 0;
    for (const auto& kv : g.multi_sent) {
      if (kv.second.first > 0 && kv.second.first == kv.second.second) ++fullOk;
    }
    std::cout << "multi_full_sentence_all_targets_ok " << fullOk << "/"
              << g.multi_sent.size() << "\n";
  }
}

}  // namespace

int main(int argc, char** argv) {
  if (argc < 5) {
    std::cerr
        << "Usage: newstar_homophone_eval <items.jsonl> <data.txt> "
           "<word-bigrams.tsv> <path-char-lstm.bin> [mode] [lambda] [nu]\n"
        << "  mode: shipping (default) | walk\n"
        << "  default lambda=0.75 nu=0.75 (shipping)\n";
    return 1;
  }
  const std::string itemsPath = argv[1];
  const std::string dataPath = argv[2];
  const std::string bigramPath = argv[3];
  const std::string lstmPath = argv[4];
  std::string mode = argc > 5 ? argv[5] : "shipping";
  double lambda = argc > 6 ? std::stod(argv[6]) : 0.75;
  double nu = argc > 7 ? std::stod(argv[7]) : 0.75;
  // 第 8 個參數：confusion-alphas.tsv（路線 A 的頻率壓縮表）。不給就不套用，
  // 行為與加這個參數之前完全一致 —— 對照組要能證明「沒開＝原版」。
  const std::string alphasPath = argc > 8 ? argv[8] : "";
  // 第 9 個參數：逐題結果輸出路徑。兩次跑出來的檔案拿去比對，才知道
  // 「淨進步 N 題」底下是幾題改對、幾題改錯 —— 沒有這個就只能猜顯著性，
  // 而淨值一樣可以是「+50/-9」也可以是「+300/-259」，意義天差地遠。
  const std::string dumpPath = argc > 9 ? argv[9] : "";
  // 第 10 個參數：文法規則表（ParticleRuleDisambiguator）。不給就不掛，
  // 行為與加這段之前逐位相同 —— 對照組要能證明「沒開＝原版」。
  const std::string rulesPath = argc > 10 ? argv[10] : "";

  ParselessLM lm;
  if (!lm.open(dataPath.c_str())) {
    std::cerr << "FATAL: cannot open data.txt: " << dataPath << "\n";
    return 1;
  }
  CorpusBigramContextModel cm;
  if (!cm.load(bigramPath.c_str())) {
    std::cerr << "FATAL: cannot load bigrams: " << bigramPath << "\n";
    return 1;
  }
  cm.setLambda(lambda);

  NeuralLMPathScorer neuralScorer;
  bool hasScorer = neuralScorer.load(lstmPath.c_str());
  if (mode == "shipping" && !hasScorer) {
    std::cerr << "FATAL: shipping mode requires LSTM load: " << lstmPath << "\n";
    return 1;
  }
  std::map<std::string, double> confusionAlphas;
  if (!alphasPath.empty()) {
    std::ifstream af(alphasPath);
    if (!af) {
      std::cerr << "FATAL: cannot open alphas: " << alphasPath << "\n";
      return 1;
    }
    std::string aline;
    while (std::getline(af, aline)) {
      if (aline.empty() || aline[0] == '#') continue;
      size_t tab = aline.find('\t');
      if (tab == std::string::npos) continue;
      std::string reading = aline.substr(0, tab);
      std::string val = aline.substr(tab + 1);
      while (!reading.empty() && (reading.back() == '\r' || reading.back() == ' '))
        reading.pop_back();
      if (reading.empty()) continue;
      confusionAlphas[reading] = std::stod(val);
    }
  }

  McBopomofo::ParticleRuleDisambiguator particleRule;
  if (!rulesPath.empty()) {
    if (!particleRule.load(rulesPath)) {
      std::cerr << "FATAL: cannot load rules: " << rulesPath << "\n";
      return 1;
    }
    // 詞庫查詢：規則用它擋「右邊兩字本身就成詞」的誤判。
    particleRule.setDictionaryLookup(
        [&lm](const std::string& w) { return !lm.getReadings(w).empty(); });
  }

  std::cout << "NEWSTAR mode=" << mode << " lambda=" << lambda << " nu=" << nu
            << " path_scorer_loaded=" << (hasScorer ? 1 : 0)
            << " confusion_alphas=" << confusionAlphas.size()
            << " grammar_rules=" << particleRule.ruleCount()
            << " uom=off\n";

  std::ifstream in(itemsPath);
  if (!in) {
    std::cerr << "FATAL: cannot open items: " << itemsPath << "\n";
    return 1;
  }

  std::vector<Item> items;
  std::vector<Reject> rejects;
  std::string line;
  size_t line_no = 0;
  while (std::getline(in, line)) {
    ++line_no;
    if (line.empty() || line[0] == '#') continue;
    Item it;
    std::string err;
    if (!parseItem(line, line_no, &it, &err)) {
      rejects.push_back({line_no, "", "parse:" + err});
      continue;
    }
    std::string reason;
    if (!validateItem(lm, it, &reason)) {
      rejects.push_back({line_no, it.sentence_id, reason});
      continue;
    }
    items.push_back(std::move(it));
  }

  std::cout << "ITEMS_LOADED " << items.size() << " REJECTED " << rejects.size()
            << " LINES_READ " << line_no << "\n";
  if (!rejects.empty()) {
    std::cout << "--- rejected items (excluded from score) ---\n";
    // Cap stdout spam; full list goes to <dumpPath>.rejects.tsv when dump set.
    const size_t kMaxStdoutRejects = 50;
    for (size_t ri = 0; ri < rejects.size() && ri < kMaxStdoutRejects; ++ri) {
      const auto& r = rejects[ri];
      std::cout << "REJECT line=" << r.line_no << " id=" << r.sentence_id
                << " reason=" << r.reason << "\n";
    }
    if (rejects.size() > kMaxStdoutRejects) {
      std::cout << "REJECT … (" << (rejects.size() - kMaxStdoutRejects)
                << " more; see dump.rejects.tsv if dump path set)\n";
    }
    if (!dumpPath.empty()) {
      std::ofstream rj(dumpPath + ".rejects.tsv");
      if (rj) {
        rj << "line_no\tsentence_id\treason\n";
        for (const auto& r : rejects) {
          rj << r.line_no << "\t" << r.sentence_id << "\t" << r.reason << "\n";
        }
      }
    }
  }

  // Groups: tier|split
  std::map<std::string, GroupAgg> groups;
  std::ofstream dump;
  if (!dumpPath.empty()) {
    dump.open(dumpPath);
    if (!dump) {
      std::cerr << "FATAL: cannot write dump: " << dumpPath << "\n";
      return 1;
    }
    dump << "sentence_id\tpair_id\tsplit\tcorrect\toutput\tsegments\n";
  }
  int feedFail = 0;
  for (const auto& it : items) {
    ReadingGrid g = makeGrid(&lm);
    if (!feed(g, it.full_reading)) {
      ++feedFail;
      rejects.push_back({it.line_no, it.sentence_id, "feed_readings_failed"});
      continue;
    }
    g.setContextModel(&cm);
    if (mode == "shipping" && hasScorer && nu > 0.0) {
      g.setPathScorer(&neuralScorer);
      g.setPathRerankNu(nu);
      g.setPathRerankNBest(10);
    } else {
      g.setPathScorer(nullptr);
      g.setPathRerankNu(0.0);
    }
    // 路線 A 只在 N-best 融合那一段生效，所以沒有 path scorer 時它什麼也不做。
    if (!confusionAlphas.empty()) {
      g.setConfusionAlphas(&confusionAlphas);
    }
    // No UOM / personalization attached (clean measure).
    auto w = g.walk();
    if (particleRule.ruleCount() > 0) {
      particleRule.reset();
      particleRule.rescoreWalk(w);
    }
    std::string out = joined(w);
    auto outChars = utf8Chars(out);
    bool ok = false;
    if (static_cast<size_t>(it.target_index) < outChars.size()) {
      ok = (outChars[static_cast<size_t>(it.target_index)] == it.target_char);
    }
    std::string key = it.tier + "|" + it.split;
    addResult(&groups[key], it, ok);
    if (dump) {
      // 斷詞結果（節點以 | 分隔）。規則要用它擋「跨詞邊界的假搭配」——
      // 「可以|有」裡的「以有」不是一個搭配，拿它當條件會製造誤判。
      // 這一招出自陳勇志等（2009），那篇靠斷詞把 Micro Precision
      // 從 91.3% 推到 95.5%，是他們單一改動裡效果最大的。
      std::string segs;
      for (size_t si = 0; si < w.nodes.size(); ++si) {
        if (si) segs += "|";
        segs += w.chosenValueAt(si);
      }
      dump << it.sentence_id << "\t" << it.pair_id << "\t" << it.split << "\t"
           << (ok ? 1 : 0) << "\t" << out << "\t" << segs << "\n";
    }
  }
  if (feedFail) {
    std::cout << "FEED_FAIL " << feedFail << "\n";
  }

  // Print in stable order: single train, single heldout, multi train, multi heldout
  const char* order[] = {"single|train", "single|heldout", "multi|train",
                         "multi|heldout"};
  for (const char* k : order) {
    auto it = groups.find(k);
    if (it == groups.end()) {
      GroupAgg empty;
      printGroup(std::string(k), empty);
    } else {
      printGroup(it->first, it->second);
    }
  }

  // One-line summary for future comparison
  auto pct = [](const GroupAgg& g) -> double {
    if (g.items == 0) return -1.0;
    double wSum = 0, wAcc = 0;
    for (const auto& kv : g.pairs) {
      double acc =
          kv.second.items
              ? static_cast<double>(kv.second.correct) / kv.second.items
              : 0;
      wSum += kv.second.weight;
      wAcc += kv.second.weight * acc;
    }
    return wSum > 0 ? 100.0 * wAcc / wSum : 0.0;
  };
  double st = groups.count("single|train") ? pct(groups["single|train"]) : -1;
  double sh =
      groups.count("single|heldout") ? pct(groups["single|heldout"]) : -1;
  std::cout << "\nNEWSTAR single train weighted="
            << (st < 0 ? "NA" : (std::to_string(st) + "%"))
            << " heldout=" << (sh < 0 ? "NA" : (std::to_string(sh) + "%"))
            << "\n";
  return 0;
}
