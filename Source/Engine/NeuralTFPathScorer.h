// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// Char-level decoder-only Transformer PathScorer (eval harness).
// scoreSentence = sum log10 P(char_t | history) under causal TF LM.

#ifndef SRC_ENGINE_NEURALTFPATHSCORER_H_
#define SRC_ENGINE_NEURALTFPATHSCORER_H_

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "gramambular2/reading_grid.h"

namespace McBopomofo {

class NeuralTFPathScorer
    : public Formosa::Gramambular2::ReadingGrid::PathScorer {
 public:
  bool load(const std::string& path);
  [[nodiscard]] bool isLoaded() const { return loaded_; }
  [[nodiscard]] int dModel() const { return dModel_; }
  [[nodiscard]] int nHead() const { return nHead_; }
  [[nodiscard]] int nLayer() const { return nLayer_; }
  [[nodiscard]] int ffn() const { return ffn_; }
  [[nodiscard]] int maxCtx() const { return maxCtx_; }
  [[nodiscard]] int vocabSize() const { return vocab_; }
  [[nodiscard]] size_t parameterCount() const;

  double scoreSentence(const std::vector<std::string>& words) override;

 private:
  bool loaded_ = false;
  int dModel_ = 0;
  int nHead_ = 0;
  int nLayer_ = 0;
  int ffn_ = 0;
  int maxCtx_ = 0;
  int vocab_ = 0;
  int unk_id_ = 1;
  int bos_id_ = 2;
  int eos_id_ = 3;

  std::vector<std::string> itos_;
  std::unordered_map<std::string, int> stoi_;

  std::vector<float> emb_;   // [V, D]
  std::vector<float> pos_;   // [max_ctx, D]

  struct Layer {
    std::vector<float> ln1_w, ln1_b;
    std::vector<float> Wq, Wk, Wv, Wo;  // [D, D] each (row-major out×in as PyTorch)
    std::vector<float> bq, bk, bv, bo;
    std::vector<float> ln2_w, ln2_b;
    std::vector<float> W1;  // [D, FFN] for x@W1
    std::vector<float> b1;  // [FFN]
    std::vector<float> W2;  // [FFN, D]
    std::vector<float> b2;  // [D]
  };
  std::vector<Layer> layers_;
  std::vector<float> ln_f_w_, ln_f_b_;
  std::vector<float> lm_w_;  // [V, D]
  std::vector<float> lm_b_;  // [V]

  static std::vector<std::string> flattenChars(
      const std::vector<std::string>& words);
  static void layerNorm(const float* x, const float* w, const float* b, int D,
                        float* out);
  static void gelu(float* x, int n);
  void attnBlock(const Layer& L, const float* x, int T, float* y) const;
  void ffnBlock(const Layer& L, const float* x, int T, float* y) const;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_NEURALTFPATHSCORER_H_
