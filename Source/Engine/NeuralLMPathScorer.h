// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// True neural PathScorer: char-level multi-layer LSTM LM (trained offline).
// scoreSentence returns sum of log10 P(char_t | history) via teacher-forced
// forward pass — NOT n-gram / table lookup.

#ifndef SRC_ENGINE_NEURALLMPATHSCORER_H_
#define SRC_ENGINE_NEURALLMPATHSCORER_H_

#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include "gramambular2/reading_grid.h"

namespace McBopomofo {

class NeuralLMPathScorer
    : public Formosa::Gramambular2::ReadingGrid::PathScorer {
 public:
  bool load(const std::string& path);
  [[nodiscard]] bool isLoaded() const { return loaded_; }
  [[nodiscard]] int embDim() const { return emb_; }
  [[nodiscard]] int hiddenDim() const { return hidden_; }
  [[nodiscard]] int layers() const { return layers_; }
  [[nodiscard]] int vocabSize() const { return vocab_; }
  [[nodiscard]] size_t parameterCount() const;

  // Sum of log10 next-char probabilities under the LSTM LM (higher = better).
  double scoreSentence(const std::vector<std::string>& words) override;

 private:
  bool loaded_ = false;
  int emb_ = 0;
  int hidden_ = 0;
  int layers_ = 0;
  int vocab_ = 0;
  int unk_id_ = 1;
  int bos_id_ = 2;
  int eos_id_ = 3;

  std::vector<std::string> itos_;
  std::unordered_map<std::string, int> stoi_;

  // Weights (row-major float32 as exported by train_char_lstm_lm.py)
  std::vector<float> emb_w_;          // [V, E]
  std::vector<std::vector<float>> w_ih_;  // per layer [4H, input]
  std::vector<std::vector<float>> w_hh_;  // per layer [4H, H]
  std::vector<std::vector<float>> b_ih_;
  std::vector<std::vector<float>> b_hh_;
  std::vector<float> fc_w_;  // [V, H]
  std::vector<float> fc_b_;  // [V]

  static std::vector<std::string> flattenChars(
      const std::vector<std::string>& words);
  void lstmStep(int layer, const float* x, const float* h_prev,
                const float* c_prev, float* h_out, float* c_out) const;
  void forwardLogits(const std::vector<int>& ids, std::vector<float>& logits,
                     std::vector<float>& h, std::vector<float>& c) const;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_NEURALLMPATHSCORER_H_
