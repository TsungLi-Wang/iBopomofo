// Copyright (c) 2022 and onwards Lukhnos Liu.
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

#ifndef SRC_ENGINE_GRAMAMBULAR2_READING_GRID_H_
#define SRC_ENGINE_GRAMAMBULAR2_READING_GRID_H_

#include <array>
#include <cassert>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "language_model.h"

namespace Formosa::Gramambular2 {

// A grid for deriving the most likely hidden values from a series of
// observations. For our purpose, the observations are Bopomofo readings, and
// the hidden values are the actual Mandarin words. This can also be used for
// segmentation: in that case, the observations are Mandarin words, and the
// hidden values are the most likely groupings.
//
// While we use the terminology from hidden Markov model (HMM), the actual
// implementation is a much simpler Bayesian inference, since the underlying
// language model consists of only unigrams. Once we have put all plausible
// unigrams as nodes on the grid, a simple DAG shortest-path walk will give us
// the maximum likelihood estimation (MLE) for the hidden values.
class ReadingGrid {
 public:
  explicit ReadingGrid(std::shared_ptr<LanguageModel> lm)
      : lm_(std::move(lm)) {}

  void clear();

  [[nodiscard]] size_t length() const { return readings_.size(); }

  [[nodiscard]] size_t cursor() const { return cursor_; }

  void setCursor(size_t cursor);

  [[nodiscard]] std::string readingSeparator() const { return separator_; }

  void setReadingSeparator(const std::string& separator);

  bool insertReading(const std::string& reading);

  // Delete the reading before the cursor, like Backspace. Cursor will decrement
  // by one.
  bool deleteReadingBeforeCursor();

  // Delete the reading after the cursor, like Del. Cursor is unmoved.
  bool deleteReadingAfterCursor();

  static constexpr size_t kMaximumSpanLength = 8;
  static constexpr char kDefaultSeparator[] = "-";

  // A Node consists of a set of unigrams, a reading, and a spanning length.
  // The spanning length denotes the length of the node in the grid. The grid
  // is responsible for constructing its nodes. For Mandarin multi-character
  // phrases, the grid will join separate readings into a single combined
  // reading, and use that reading to retrieve the unigrams with that reading.
  // Node with two-character phrases (so two readings, or two syllables) will
  // then have a spanning length of 2.
  class Node {
   public:
    enum class OverrideType {
      kNone,
      // Override the node with a unigram value and a score such that the node
      // will almost always be favored by the walk.
      kOverrideValueWithHighScore,
      // Override the node with a unigram value but with the score of the
      // top unigram. For example, if the unigrams in the node are ("a", -1),
      // ("b", -2), ("c", -10), overriding using this type for "c" will cause
      // the node to return the value "c" with the score -1. This is used for
      // soft-override such as from a suggestion. The node with the override
      // value will very likely be favored by a walk, but it does not prevent
      // other nodes from prevailing, which would be the case if
      // kOverrideValueWithHighScore was used.
      kOverrideValueWithScoreFromTopUnigram
    };

    Node(std::string reading, size_t spanningLength,
         std::vector<LanguageModel::Unigram> unigrams)
        : reading_(std::move(reading)),
          spanningLength_(spanningLength),
          unigrams_(std::move(unigrams)),
          unigramIter_(unigrams_.begin()),
          overrideType_(OverrideType::kNone) {}

    [[nodiscard]] const std::string& reading() const { return reading_; }

    [[nodiscard]] size_t spanningLength() const { return spanningLength_; }

    [[nodiscard]] const std::vector<LanguageModel::Unigram>& unigrams() const {
      return unigrams_;
    }

    // Returns the top or overridden unigram.
    [[nodiscard]] LanguageModel::Unigram currentUnigram() const;

    [[nodiscard]] std::string value() const;

    [[nodiscard]] double score() const;

    [[nodiscard]] bool isOverridden() const;

    void reset();

    bool selectOverrideUnigram(const std::string& value, OverrideType type);

    // A sufficiently high score to cause the walk to go through an overriding
    // node. Although this can be 0, setting it to a positive value has the
    // desirable side effect that it reduces the competition of "free-floating"
    // multiple-character phrases. For example, if the user override for
    // reading "a b c" is "A B c", using the uppercase as the overriding node,
    // now the standalone c may have to compete with a phrase with reading "bc",
    // which in some pathological cases may actually cause the shortest path to
    // be A->bc, especially when A and B use the zero overriding score, as they
    // leave "c" alone to compete with "bc", and whether the path A-B is favored
    // now solely depends on that competition. A positive value favors the route
    // A->B, which gives "c" a better chance.
    static constexpr double kOverridingScore = 42;

   protected:
    const std::string reading_;
    const size_t spanningLength_;
    const std::vector<LanguageModel::Unigram> unigrams_;
    std::vector<LanguageModel::Unigram>::const_iterator unigramIter_;
    OverrideType overrideType_;
  };

  using NodePtr = std::shared_ptr<Node>;

  // Find, in a span at the cursor, the first node satisfying the predicate.
  // Returns std::nullopt if not found.
  std::optional<NodePtr> findInSpan(
      size_t cursor,
      const std::function<bool(const NodePtr&)>& predicate) const;

  struct WalkResult {
    std::vector<NodePtr> nodes;
    std::vector<size_t> selectedUnigramIndices;  // parallel to nodes; index into node->unigrams() for the chosen one when using ContextModel
    size_t totalReadings = 0;
    size_t vertices = 0;
    size_t edges = 0;
    uint64_t elapsedMicroseconds = 0;

    // Convenient method for finding the node at the cursor. Returns
    // nodes.cend() if the value of cursor argument doesn't make sense. An
    // optional ourCursorPastNode argument can be used to obtain the cursor
    // position that is right past the node at cursor, and will be only be set
    // if it's not nullptr and the returned iterator is not nodes.cend().
    std::vector<NodePtr>::const_iterator findNodeAt(
        size_t cursor, size_t* outCursorPastNode = nullptr) const;

    std::vector<std::string> valuesAsStrings() const;
    std::vector<std::string> readingsAsStrings() const;

    // Returns the chosen value for the i-th node on the path.
    // Priority: node override (user / post-walk neural) > ContextModel DP
    // selectedUnigramIndices > node->value() (top unigram / fast path).
    std::string chosenValueAt(size_t i) const;

    // n-gram + RNN hybrid path selection: re-pick an existing unigram on a path
    // node by updating selectedUnigramIndices only (does not mutate node
    // override state, does not re-walk, never invents text). Initializes
    // selectedUnigramIndices from current node values if empty so it also
    // works after a fast-path (unigram-only) walk. Returns false if `value`
    // is not among that node's unigrams.
    bool reselectUnigramValue(size_t nodeIndex, const std::string& value);

    // Cumulative walk DP score of the chosen path (ContextModel path only;
    // 0 on fast path). Used by n-best + PathScorer fusion.
    double walkScore = 0.0;
  };

  // Optional sentence-level path scorer for n-best rerank (Mozc-style).
  // nullptr → no rerank; walk() bit-identical to pre-rerank behavior.
  class PathScorer {
   public:
    virtual ~PathScorer() = default;
    // TEST-ORACLE ONLY for shipping scorers. Product walk() never calls this
    // (it always uses scoreNBest). Kept so tests can assert batch vs sequential
    // equality. Do not call from KeyHandler / product rerank path.
    virtual double scoreSentence(const std::vector<std::string>& words) = 0;
    // Product n-best scoring entry. Shipping NeuralLMPathScorer overrides this
    // with trie+BLAS. Default falls back to looping scoreSentence (eval-only
    // scorers without a batch path).
    virtual std::vector<double> scoreNBest(
        const std::vector<std::vector<std::string>>& paths) {
      std::vector<double> out;
      out.reserve(paths.size());
      for (const auto& p : paths) out.push_back(scoreSentence(p));
      return out;
    }
  };

  // One complete lattice path with walk DP score (before PathScorer fusion).
  struct RankedPath {
    std::vector<NodePtr> nodes;
    std::vector<size_t> selectedUnigramIndices;
    std::vector<std::string> words;
    double walkScore = 0.0;
    double pathScore = 0.0;  // walkScore + nu * pathScorer (after fusion)
  };

  WalkResult walk();

  // Extract top-N complete paths under the current ContextModel (requires
  // contextModel_ != nullptr). Rank 0 must match walk() top-1 words when
  // PathScorer is not applied. Empty if no context model / empty grid.
  std::vector<RankedPath> walkNBest(size_t n);

  void setPathScorer(PathScorer* scorer) { pathScorer_ = scorer; }
  void setPathRerankNu(double nu) { pathRerankNu_ = nu; }

  // 同音候選的頻率先驗壓縮係數：讀音 → alpha（1.0 = 完全採信頻率＝原行為，
  // 0.0 = 同音候選之間不比頻率、只由 PathScorer 的上下文判斷決定）。
  //
  // 為什麼需要：語言模型只看字詞常不常用，而同音字之間的頻率差可以到幾十
  // 上百倍（「的」比「得」常見約 180 倍）。只要兩個字都合法，高頻字永遠贏，
  // 上下文訊號蓋不過去 —— 實測「該打得的句子」引擎只選對 6.6%。
  //
  // 這一層在 n-best 融合時，把「非最高頻候選要付的頻率代價」按 alpha 折扣，
  // 讓 PathScorer 的判斷浮得出來。只影響同一節點內的候選比較，不影響斷詞。
  //
  // 逐讀音設定而非全域，因為各組性質不同（2026-08-10 實測）：
  //   ㄗㄞˋ 在/再、ㄉㄜ˙ 的/得、ㄗㄨㄛˋ 作/做/坐/座 → alpha 0.0 明顯較好
  //   ㄅㄚ  吧/八/巴 → alpha 1.0（維持原樣）較好，因為「吧」的高頻是真實的
  //                    語言規律（句尾語氣詞），壓掉它反而丟失正確訊號
  // 傳 nullptr 或空表 → 完全不改變原行為。
  void setConfusionAlphas(const std::map<std::string, double>* alphas) {
    confusionAlphas_ = alphas;
  }
  void setPathRerankNBest(size_t n) { pathRerankNBest_ = n == 0 ? 1 : n; }
  [[nodiscard]] PathScorer* pathScorer() const { return pathScorer_; }
  [[nodiscard]] double pathRerankNu() const { return pathRerankNu_; }

  struct Candidate {
    Candidate(std::string r, std::string v, std::string rv = "")
        : reading(std::move(r)), value(std::move(v)), rawValue(std::move(rv)) {}
    const std::string reading;
    const std::string value;
    const std::string rawValue;
  };

  // Returns all candidate values at the location. If spans are not empty and
  // loc is at the end of the spans, (loc - 1) is used, so that the caller does
  // not have to care about this boundary condition.
  std::vector<Candidate> candidatesAt(size_t loc);

  // Adds weight to the node with the unigram that has the designated candidate
  // value and applies the desired override type, essentially resulting in user
  // override. An overridden node would influence the grid walk to favor walking
  // through it.
  bool overrideCandidate(size_t loc, const Candidate& candidate,
                         Node::OverrideType overrideType =
                             Node::OverrideType::kOverrideValueWithHighScore);

  // Same as the method above, but since the string candidate value is used, if
  // there are multiple nodes (of different spanning length) that have the same
  // unigram value, it's not guaranteed which node will be selected.
  bool overrideCandidate(size_t loc, const std::string& candidate,
                         Node::OverrideType overrideType =
                             Node::OverrideType::kOverrideValueWithHighScore);

  // A span is a collection of nodes that share the same starting location.
  class Span {
   public:
    void clear();
    void add(const NodePtr& node);
    void removeNodesOfOrLongerThan(size_t length);
    [[nodiscard]] const NodePtr& nodeOf(size_t length) const;
    [[nodiscard]] size_t maxLength() const { return maxLength_; }

   protected:
    std::array<NodePtr, kMaximumSpanLength> nodes_;
    size_t maxLength_ = 0;
  };

  // A language model wrapper that always returns score-ranked unigrams.
  class ScoreRankedLanguageModel : public LanguageModel {
   public:
    explicit ScoreRankedLanguageModel(std::shared_ptr<LanguageModel> lm)
        : lm_(std::move(lm)) {
      assert(lm_ != nullptr);
    }
    std::vector<Unigram> getUnigrams(const std::string& reading) override;
    bool hasUnigrams(const std::string& reading) override;

   protected:
    std::shared_ptr<LanguageModel> lm_;
  };

  // ContextModel for bigram (or higher) transitions inside walk.
  // When set, walk will use it to score transitions between chosen unigrams.
  class ContextModel {
   public:
    virtual ~ContextModel() = default;
    // Return log prob of the word given previous state, and update out state.
    virtual double score(const std::string& prevWord, const std::string& word,
                         double& state) = 0;
    // Reading-aware scoring for personalization (prev + target reading + word).
    // Default ignores reading and delegates to score().
    virtual double scoreWithReading(const std::string& prevWord,
                                    const std::string& reading,
                                    const std::string& word, double& state) {
      (void)reading;
      return score(prevWord, word, state);
    }
    virtual double beginState() = 0;
  };

  void setContextModel(ContextModel* cm) { contextModel_ = cm; }

  [[nodiscard]] const std::vector<Span>& spans() const { return spans_; }

  [[nodiscard]] const std::vector<std::string>& readings() const {
    return readings_;
  }

 protected:
  size_t cursor_ = 0;
  std::string separator_ = kDefaultSeparator;
  std::vector<std::string> readings_;
  std::vector<Span> spans_;
  ScoreRankedLanguageModel lm_;
  ContextModel* contextModel_ = nullptr;
  PathScorer* pathScorer_ = nullptr;
  double pathRerankNu_ = 0.0;
  const std::map<std::string, double>* confusionAlphas_ = nullptr;
  size_t pathRerankNBest_ = 10;
  // Per-state hypothesis beam for n-best (exact top-1 preserved as best hyp).
  static constexpr size_t kNBestHypK = 8;

  // Internal methods for maintaining the grid.

  void expandGridAt(size_t loc);
  void shrinkGridAt(size_t loc);
  void removeAffectedNodes(size_t loc);
  void insert(size_t loc, const NodePtr& node);
  std::string combineReading(std::vector<std::string>::const_iterator begin,
                             std::vector<std::string>::const_iterator end);
  bool hasNodeAt(size_t loc, size_t readingLen, const std::string& reading);
  void update();

  // Internal implementation of overrideCandidate, with an optional reading.
  bool overrideCandidate(size_t loc, const std::string* reading,
                         const std::string& value,
                         Node::OverrideType overrideType);

  struct NodeInSpan {
    NodePtr node;
    size_t spanIndex = 0;
  };

  // Find all nodes that overlap with the location. The return value is a list
  // of nodes along with their starting location in the grid.
  std::vector<NodeInSpan> overlappingNodesAt(size_t loc) const;
};

}  // namespace Formosa::Gramambular2

#endif  // SRC_ENGINE_GRAMAMBULAR2_READING_GRID_H_
