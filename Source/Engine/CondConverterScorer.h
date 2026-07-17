// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// Conditional conversion scorer: score P(word | left_context, reading).
// Trained offline (train_cond_converter.py); pure C++ forward.

#ifndef SRC_ENGINE_CONDCONVERTERSCORER_H_
#define SRC_ENGINE_CONDCONVERTERSCORER_H_

#include <string>
#include <unordered_map>
#include <vector>

namespace McBopomofo {

class CondConverterScorer {
 public:
  bool load(const std::string& path);
  [[nodiscard]] bool isLoaded() const { return loaded_; }
  [[nodiscard]] int embDim() const { return emb_; }
  [[nodiscard]] int hiddenDim() const { return hidden_; }
  [[nodiscard]] int layers() const { return layers_; }
  [[nodiscard]] int charVocab() const { return charVocab_; }
  [[nodiscard]] int readingVocab() const { return rdVocab_; }
  [[nodiscard]] size_t parameterCount() const;

  // log10 P(candidate chars | left_context, reading). Higher = better.
  // Empty / unloaded → 0. Does not invent text.
  double scoreCandidate(const std::string& leftContext,
                        const std::string& reading,
                        const std::string& candidate) const;

 private:
  bool loaded_ = false;
  int emb_ = 0;
  int hidden_ = 0;
  int layers_ = 0;
  int charVocab_ = 0;
  int rdVocab_ = 0;
  int unk_ = 1;
  int bos_ = 2;
  int eos_ = 3;

  std::vector<std::string> charItos_;
  std::unordered_map<std::string, int> charStoi_;
  std::vector<std::string> rdItos_;
  std::unordered_map<std::string, int> rdStoi_;

  std::vector<float> charEmb_;  // [Vc, E]
  std::vector<float> rdEmb_;    // [Vr, E]
  // LSTM weights per layer (ctx, rd, dec): w_ih, w_hh, b_ih, b_hh
  std::vector<std::vector<float>> ctxWih_, ctxWhh_, ctxBih_, ctxBhh_;
  std::vector<std::vector<float>> rdWih_, rdWhh_, rdBih_, rdBhh_;
  std::vector<std::vector<float>> decWih_, decWhh_, decBih_, decBhh_;
  std::vector<float> fuseW_, fuseB_, fuseCW_, fuseCB_;  // fuse: [H*L, 2H]
  std::vector<float> fcW_, fcB_;  // [Vc, H]

  static std::vector<std::string> utf8Chars(const std::string& s);
  static std::vector<std::string> splitReading(const std::string& rd);
  void lstmStep(const std::vector<float>& wih, const std::vector<float>& whh,
                const std::vector<float>& bih, const std::vector<float>& bhh,
                int inDim, const float* x, const float* hPrev, const float* cPrev,
                float* hOut, float* cOut) const;
};

}  // namespace McBopomofo

#endif  // SRC_ENGINE_CONDCONVERTERSCORER_H_
