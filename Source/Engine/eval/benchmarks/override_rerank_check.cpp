// Verifies the trust invariant: a hard user override (kOverrideValueWithHighScore)
// is NEVER overturned by the neural n-best rerank. The override adds +42 to the
// path's walk score; the rerank term ν·neural is bounded (log10 sentence probs),
// so no reranked path that drops the override can win. We prove it two ways with
// the REAL shipped scorer (v2c int8, ν=0.75, N=10):
//   (1) every walkNBest(10) path keeps the overridden value → rerank has no
//       alternative to pick (unconditional, scorer-independent);
//   (2) the final reranked walk keeps the overridden value.
//
// Usage: override_rerank_check <sentences> <data> <bigrams> <lambda> <lstm.bin> <nu>

#include <chrono>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "NeuralLMPathScorer.h"
#include "ParselessLM.h"
#include "gramambular2/reading_grid.h"

#include "../benchmark_gate.h"

using Formosa::Gramambular2::ReadingGrid;
using McBopomofo::CorpusBigramContextModel;
using McBopomofo::NeuralLMPathScorer;
using McBopomofo::ParselessLM;

namespace {
std::vector<std::string> splitSyllables(const std::string& r) {
  std::vector<std::string> out;
  size_t s = 0;
  for (size_t i = 0; i < r.size(); ++i) {
    if (r[i] == '-') { if (i > s) out.push_back(r.substr(s, i - s)); s = i + 1; }
  }
  if (s < r.size()) out.push_back(r.substr(s));
  return out;
}
ReadingGrid makeGrid(ParselessLM* lm) {
  ReadingGrid g(std::shared_ptr<Formosa::Gramambular2::LanguageModel>(
      lm, [](Formosa::Gramambular2::LanguageModel*) {}));
  g.setReadingSeparator("-");
  return g;
}
bool feed(ReadingGrid& g, const std::string& r) {
  for (const auto& syl : splitSyllables(r)) {
    g.setCursor(g.length());
    if (!g.insertReading(syl)) return false;
  }
  return true;
}
std::string joined(const ReadingGrid::WalkResult& w) {
  std::string s;
  for (size_t i = 0; i < w.nodes.size(); ++i) s += w.chosenValueAt(i);
  return s;
}
std::string valueAtLocation(const ReadingGrid::WalkResult& w, size_t loc) {
  size_t pos = 0;
  for (size_t i = 0; i < w.nodes.size(); ++i) {
    size_t span = w.nodes[i]->spanningLength();
    if (loc >= pos && loc < pos + span) return w.chosenValueAt(i);
    pos += span;
  }
  return "";
}
struct Case { std::string readings, expected; };
std::vector<Case> loadCases(const std::string& p) {
  std::ifstream in(p); std::vector<Case> c; std::string line;
  while (std::getline(in, line)) {
    if (line.empty() || line[0] == '#') continue;
    size_t t = line.find('\t');
    if (t != std::string::npos) c.push_back({line.substr(0, t), line.substr(t + 1)});
  }
  return c;
}
}  // namespace

int main(int argc, char** argv) {
  if (argc < 7) { std::cerr << "usage: ... sentences data bigrams lambda lstm nu\n"; return 1; }
  McBopomofoEval::AbortUnlessTw538(argv[1]);
  auto cases = loadCases(argv[1]);
  ParselessLM lm; if (!lm.open(argv[2])) { std::cerr << "data\n"; return 1; }
  CorpusBigramContextModel cm; if (!cm.load(argv[3])) { std::cerr << "bg\n"; return 1; }
  cm.setLambda(std::stod(argv[4]));
  NeuralLMPathScorer lstm; if (!lstm.load(argv[5])) { std::cerr << "lstm\n"; return 1; }
  double nu = std::stod(argv[6]);
  std::cout << "override_rerank_check: scorer loaded=" << lstm.isLoaded()
            << " params=" << lstm.parameterCount() << " nu=" << nu << "\n";

  int tested = 0, nbestKept = 0, finalKept = 0, changedByRerank = 0;
  // Test on cases where rerank actually moves the answer (draft != reranked),
  // then pin the RERANKED-away node with a hard override and confirm it sticks.
  for (const auto& c : cases) {
    auto syls = splitSyllables(c.readings);
    if (syls.size() < 3) continue;

    // draft (walk ON, no rerank)
    std::string draft;
    { ReadingGrid g = makeGrid(&lm); if (!feed(g, c.readings)) continue;
      g.setContextModel(&cm); draft = joined(g.walk()); }
    // reranked
    std::string reranked;
    { ReadingGrid g = makeGrid(&lm); if (!feed(g, c.readings)) continue;
      g.setContextModel(&cm); g.setPathScorer(&lstm); g.setPathRerankNu(nu);
      g.setPathRerankNBest(10); reranked = joined(g.walk()); }
    if (draft == reranked) continue;  // want cases the rerank changed
    ++changedByRerank;
    if (changedByRerank > 40) break;  // enough samples

    // find first syllable position where reranked != draft; hard-override it
    // back to the DRAFT char (i.e. force the user's hand against the rerank).
    ReadingGrid gd = makeGrid(&lm); feed(gd, c.readings); gd.setContextModel(&cm);
    auto dW = gd.walk();
    size_t loc = 0; bool found = false;
    {
      ReadingGrid gr = makeGrid(&lm); feed(gr, c.readings); gr.setContextModel(&cm);
      gr.setPathScorer(&lstm); gr.setPathRerankNu(nu); gr.setPathRerankNBest(10);
      auto rW = gr.walk();
      for (size_t p = 0; p < syls.size(); ++p) {
        if (valueAtLocation(dW, p) != valueAtLocation(rW, p)) { loc = p; found = true; break; }
      }
    }
    if (!found) continue;
    std::string forced = valueAtLocation(dW, loc);
    if (forced.empty()) continue;

    // apply hard override at loc, then rerank
    ReadingGrid g = makeGrid(&lm); feed(g, c.readings); g.setContextModel(&cm);
    ReadingGrid::Candidate cand(syls[loc], forced);
    if (!g.overrideCandidate(
            loc, cand, ReadingGrid::Node::OverrideType::kOverrideValueWithHighScore))
      continue;
    ++tested;

    // (1) all walkNBest paths keep the override at loc?
    auto nb = g.walkNBest(10);
    bool allKeep = !nb.empty();
    for (const auto& rp : nb) {
      size_t pos = 0; std::string v;
      for (size_t i = 0; i < rp.nodes.size(); ++i) {
        size_t span = rp.nodes[i]->spanningLength();
        if (loc >= pos && loc < pos + span) { v = rp.words[i]; break; }
        pos += span;
      }
      if (v != forced) { allKeep = false; break; }
    }
    if (allKeep) ++nbestKept;

    // (2) final reranked walk keeps the override at loc?
    g.setPathScorer(&lstm); g.setPathRerankNu(nu); g.setPathRerankNBest(10);
    auto fw = g.walk();
    if (valueAtLocation(fw, loc) == forced) ++finalKept;
    else std::cout << "  VIOLATION readings=" << c.readings << " loc=" << loc
                   << " forced=" << forced << " got=" << valueAtLocation(fw, loc)
                   << "\n";
  }
  std::cout << "RERANK_CHANGED_CASES sampled " << changedByRerank << "\n";
  std::cout << "OVERRIDE_TESTED " << tested << "\n";
  std::cout << "NBEST_ALL_KEEP_OVERRIDE " << nbestKept << "/" << tested << "\n";
  std::cout << "FINAL_KEEPS_OVERRIDE " << finalKept << "/" << tested << "\n";
  std::cout << (tested > 0 && finalKept == tested
                    ? "PASS: hard override survives rerank in every tested case\n"
                    : "FAIL: override overturned by rerank\n");
  return (tested > 0 && finalKept == tested) ? 0 : 1;
}
