// Copyright (c) 2026 and onwards The McBopomofo Authors.

#include "CondConverterScorer.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>

namespace McBopomofo {

namespace {

inline float sigmoid(float x) {
  if (x > 20.f) return 1.f;
  if (x < -20.f) return 0.f;
  return 1.f / (1.f + std::exp(-x));
}

bool readExact(std::ifstream& in, void* dst, size_t n) {
  in.read(reinterpret_cast<char*>(dst), static_cast<std::streamsize>(n));
  return static_cast<size_t>(in.gcount()) == n;
}

bool readVocab(std::ifstream& in, int n, std::vector<std::string>& itos,
               std::unordered_map<std::string, int>& stoi) {
  itos.assign(static_cast<size_t>(n), "");
  stoi.clear();
  for (int i = 0; i < n; ++i) {
    int16_t len = 0;
    if (!readExact(in, &len, 2) || len < 0) return false;
    std::string s(static_cast<size_t>(len), '\0');
    if (len > 0 && !readExact(in, s.data(), static_cast<size_t>(len))) {
      return false;
    }
    itos[static_cast<size_t>(i)] = s;
    if (!s.empty()) stoi[s] = i;
  }
  return true;
}

bool readF(std::ifstream& in, std::vector<float>& v, size_t n) {
  v.resize(n);
  return readExact(in, v.data(), n * sizeof(float));
}

}  // namespace

std::vector<std::string> CondConverterScorer::utf8Chars(const std::string& s) {
  std::vector<std::string> chars;
  size_t i = 0;
  while (i < s.size()) {
    unsigned char c = static_cast<unsigned char>(s[i]);
    size_t len = 1;
    if ((c & 0x80) == 0)
      len = 1;
    else if ((c & 0xE0) == 0xC0)
      len = 2;
    else if ((c & 0xF0) == 0xE0)
      len = 3;
    else if ((c & 0xF8) == 0xF0)
      len = 4;
    if (i + len > s.size()) len = 1;
    chars.push_back(s.substr(i, len));
    i += len;
  }
  return chars;
}

std::vector<std::string> CondConverterScorer::splitReading(
    const std::string& rd) {
  std::vector<std::string> out;
  size_t start = 0;
  for (size_t i = 0; i < rd.size(); ++i) {
    if (rd[i] == '-') {
      if (i > start) out.push_back(rd.substr(start, i - start));
      start = i + 1;
    }
  }
  if (start < rd.size()) out.push_back(rd.substr(start));
  return out;
}

void CondConverterScorer::lstmStep(const std::vector<float>& wih,
                                   const std::vector<float>& whh,
                                   const std::vector<float>& bih,
                                   const std::vector<float>& bhh, int inDim,
                                   const float* x, const float* hPrev,
                                   const float* cPrev, float* hOut,
                                   float* cOut) const {
  const int H = hidden_;
  std::vector<float> gates(static_cast<size_t>(4 * H), 0.f);
  for (int g = 0; g < 4 * H; ++g) {
    float s = bih[static_cast<size_t>(g)] + bhh[static_cast<size_t>(g)];
    for (int j = 0; j < inDim; ++j) {
      s += wih[static_cast<size_t>(g) * static_cast<size_t>(inDim) +
               static_cast<size_t>(j)] *
           x[j];
    }
    for (int j = 0; j < H; ++j) {
      s += whh[static_cast<size_t>(g) * static_cast<size_t>(H) +
               static_cast<size_t>(j)] *
           hPrev[j];
    }
    gates[static_cast<size_t>(g)] = s;
  }
  for (int j = 0; j < H; ++j) {
    float i_g = sigmoid(gates[static_cast<size_t>(j)]);
    float f_g = sigmoid(gates[static_cast<size_t>(H + j)]);
    float g_g = std::tanh(gates[static_cast<size_t>(2 * H + j)]);
    float o_g = sigmoid(gates[static_cast<size_t>(3 * H + j)]);
    float c = f_g * cPrev[j] + i_g * g_g;
    float h = o_g * std::tanh(c);
    cOut[j] = c;
    hOut[j] = h;
  }
}

bool CondConverterScorer::load(const std::string& path) {
  loaded_ = false;
  std::ifstream in(path, std::ios::binary);
  if (!in) return false;
  char magic[8];
  if (!readExact(in, magic, 8) || std::memcmp(magic, "LWCONV1\0", 8) != 0) {
    return false;
  }
  if (!readExact(in, &emb_, 4) || !readExact(in, &hidden_, 4) ||
      !readExact(in, &layers_, 4) || !readExact(in, &charVocab_, 4) ||
      !readExact(in, &rdVocab_, 4)) {
    return false;
  }
  if (emb_ <= 0 || hidden_ <= 0 || layers_ <= 0 || layers_ > 4 ||
      charVocab_ <= 4 || rdVocab_ <= 4) {
    return false;
  }
  if (!readVocab(in, charVocab_, charItos_, charStoi_) ||
      !readVocab(in, rdVocab_, rdItos_, rdStoi_)) {
    return false;
  }
  unk_ = charStoi_.count("<unk>") ? charStoi_["<unk>"] : 1;
  bos_ = charStoi_.count("<s>") ? charStoi_["<s>"] : 2;
  eos_ = charStoi_.count("</s>") ? charStoi_["</s>"] : 3;

  const int E = emb_;
  const int H = hidden_;
  const int L = layers_;
  const size_t Vc = static_cast<size_t>(charVocab_);
  const size_t Vr = static_cast<size_t>(rdVocab_);

  if (!readF(in, charEmb_, Vc * static_cast<size_t>(E)) ||
      !readF(in, rdEmb_, Vr * static_cast<size_t>(E))) {
    return false;
  }

  auto loadLstm = [&](std::vector<std::vector<float>>& wih,
                      std::vector<std::vector<float>>& whh,
                      std::vector<std::vector<float>>& bih,
                      std::vector<std::vector<float>>& bhh,
                      int firstIn) -> bool {
    wih.assign(static_cast<size_t>(L), {});
    whh.assign(static_cast<size_t>(L), {});
    bih.assign(static_cast<size_t>(L), {});
    bhh.assign(static_cast<size_t>(L), {});
    for (int li = 0; li < L; ++li) {
      int inDim = (li == 0) ? firstIn : H;
      size_t wihN = static_cast<size_t>(4 * H) * static_cast<size_t>(inDim);
      size_t whhN = static_cast<size_t>(4 * H) * static_cast<size_t>(H);
      size_t bN = static_cast<size_t>(4 * H);
      if (!readF(in, wih[static_cast<size_t>(li)], wihN) ||
          !readF(in, whh[static_cast<size_t>(li)], whhN) ||
          !readF(in, bih[static_cast<size_t>(li)], bN) ||
          !readF(in, bhh[static_cast<size_t>(li)], bN)) {
        return false;
      }
    }
    return true;
  };

  if (!loadLstm(ctxWih_, ctxWhh_, ctxBih_, ctxBhh_, E)) return false;
  if (!loadLstm(rdWih_, rdWhh_, rdBih_, rdBhh_, E)) return false;

  // fuse: [H*L, 2H]
  size_t fuseOut = static_cast<size_t>(H * L);
  size_t fuseIn = static_cast<size_t>(2 * H);
  if (!readF(in, fuseW_, fuseOut * fuseIn) || !readF(in, fuseB_, fuseOut) ||
      !readF(in, fuseCW_, fuseOut * fuseIn) || !readF(in, fuseCB_, fuseOut)) {
    return false;
  }
  if (!loadLstm(decWih_, decWhh_, decBih_, decBhh_, E)) return false;
  if (!readF(in, fcW_, Vc * static_cast<size_t>(H)) ||
      !readF(in, fcB_, Vc)) {
    return false;
  }

  loaded_ = true;
  return true;
}

size_t CondConverterScorer::parameterCount() const {
  if (!loaded_) return 0;
  size_t n = charEmb_.size() + rdEmb_.size() + fuseW_.size() + fuseB_.size() +
             fuseCW_.size() + fuseCB_.size() + fcW_.size() + fcB_.size();
  auto addL = [&](const std::vector<std::vector<float>>& a) {
    for (const auto& v : a) n += v.size();
  };
  addL(ctxWih_);
  addL(ctxWhh_);
  addL(ctxBih_);
  addL(ctxBhh_);
  addL(rdWih_);
  addL(rdWhh_);
  addL(rdBih_);
  addL(rdBhh_);
  addL(decWih_);
  addL(decWhh_);
  addL(decBih_);
  addL(decBhh_);
  return n;
}

double CondConverterScorer::scoreCandidate(const std::string& leftContext,
                                           const std::string& reading,
                                           const std::string& candidate) const {
  if (!loaded_ || candidate.empty() || reading.empty()) return 0.0;

  const int E = emb_;
  const int H = hidden_;
  const int L = layers_;

  auto runEncoder = [&](const std::vector<std::string>& toks,
                        const std::unordered_map<std::string, int>& stoi,
                        const std::vector<float>& emb,
                        const std::vector<std::vector<float>>& wih,
                        const std::vector<std::vector<float>>& whh,
                        const std::vector<std::vector<float>>& bih,
                        const std::vector<std::vector<float>>& bhh,
                        std::vector<float>& hLast) {
    std::vector<float> h(static_cast<size_t>(L * H), 0.f);
    std::vector<float> c(static_cast<size_t>(L * H), 0.f);
    std::vector<float> nh(static_cast<size_t>(H)), nc(static_cast<size_t>(H));
    if (toks.empty()) {
      hLast.assign(static_cast<size_t>(H), 0.f);
      return;
    }
    const int vsize = static_cast<int>(emb.size() / static_cast<size_t>(E));
    for (const auto& t : toks) {
      auto it = stoi.find(t);
      int id = (it == stoi.end()) ? 1 : it->second;  // 1 = <unk> in both vocabs
      if (id < 0 || id >= vsize) id = (vsize > 1) ? 1 : 0;
      const float* x = emb.data() + static_cast<size_t>(id) * static_cast<size_t>(E);
      std::vector<float> cur(x, x + E);
      for (int li = 0; li < L; ++li) {
        float* hp = h.data() + static_cast<size_t>(li * H);
        float* cp = c.data() + static_cast<size_t>(li * H);
        int inDim = (li == 0) ? E : H;
        lstmStep(wih[static_cast<size_t>(li)], whh[static_cast<size_t>(li)],
                 bih[static_cast<size_t>(li)], bhh[static_cast<size_t>(li)],
                 inDim, cur.data(), hp, cp, nh.data(), nc.data());
        std::copy(nh.begin(), nh.end(), hp);
        std::copy(nc.begin(), nc.end(), cp);
        cur.assign(nh.begin(), nh.end());
      }
    }
    // top layer h
    hLast.assign(h.begin() + static_cast<size_t>((L - 1) * H),
                 h.begin() + static_cast<size_t>(L * H));
  };

  // Context: last 16 chars
  auto lchars = utf8Chars(leftContext);
  if (lchars.size() > 16) {
    lchars.erase(lchars.begin(), lchars.end() - 16);
  }
  std::vector<float> hCtx, hRd;
  runEncoder(lchars, charStoi_, charEmb_, ctxWih_, ctxWhh_, ctxBih_, ctxBhh_,
             hCtx);
  auto rtoks = splitReading(reading);
  runEncoder(rtoks, rdStoi_, rdEmb_, rdWih_, rdWhh_, rdBih_, rdBhh_, hRd);

  // fuse → h0, c0 for all layers [L,H]
  std::vector<float> cat(static_cast<size_t>(2 * H));
  for (int j = 0; j < H; ++j) {
    cat[static_cast<size_t>(j)] = hCtx[static_cast<size_t>(j)];
    cat[static_cast<size_t>(H + j)] = hRd[static_cast<size_t>(j)];
  }
  std::vector<float> h0(static_cast<size_t>(L * H));
  std::vector<float> c0(static_cast<size_t>(L * H));
  // fuseW is [H*L, 2H] row-major
  for (int o = 0; o < L * H; ++o) {
    float s = fuseB_[static_cast<size_t>(o)];
    float sc = fuseCB_[static_cast<size_t>(o)];
    for (int j = 0; j < 2 * H; ++j) {
      float w = fuseW_[static_cast<size_t>(o) * static_cast<size_t>(2 * H) +
                       static_cast<size_t>(j)];
      float wc = fuseCW_[static_cast<size_t>(o) * static_cast<size_t>(2 * H) +
                         static_cast<size_t>(j)];
      s += w * cat[static_cast<size_t>(j)];
      sc += wc * cat[static_cast<size_t>(j)];
    }
    h0[static_cast<size_t>(o)] = std::tanh(s);
    c0[static_cast<size_t>(o)] = std::tanh(sc);
  }

  // Decode: teacher force BOS + cand chars, score cand + EOS
  auto cchars = utf8Chars(candidate);
  std::vector<int> ids;
  ids.push_back(bos_);
  for (const auto& ch : cchars) {
    auto it = charStoi_.find(ch);
    ids.push_back(it == charStoi_.end() ? unk_ : it->second);
  }
  ids.push_back(eos_);

  std::vector<float> h = h0;
  std::vector<float> c = c0;
  std::vector<float> nh(static_cast<size_t>(H)), nc(static_cast<size_t>(H));
  std::vector<float> logits(static_cast<size_t>(charVocab_));
  double log10e = 1.0 / std::log(10.0);
  double sumLog10 = 0.0;
  int scored = 0;

  for (size_t t = 0; t + 1 < ids.size(); ++t) {
    int id = ids[t];
    if (id < 0 || id >= charVocab_) id = unk_;
    const float* x =
        charEmb_.data() + static_cast<size_t>(id) * static_cast<size_t>(E);
    std::vector<float> cur(x, x + E);
    for (int li = 0; li < L; ++li) {
      float* hp = h.data() + static_cast<size_t>(li * H);
      float* cp = c.data() + static_cast<size_t>(li * H);
      int inDim = (li == 0) ? E : H;
      lstmStep(decWih_[static_cast<size_t>(li)], decWhh_[static_cast<size_t>(li)],
               decBih_[static_cast<size_t>(li)], decBhh_[static_cast<size_t>(li)],
               inDim, cur.data(), hp, cp, nh.data(), nc.data());
      std::copy(nh.begin(), nh.end(), hp);
      std::copy(nc.begin(), nc.end(), cp);
      cur.assign(nh.begin(), nh.end());
    }
    const float* ht = h.data() + static_cast<size_t>((L - 1) * H);
    float maxv = -1e30f;
    for (int v = 0; v < charVocab_; ++v) {
      float s = fcB_[static_cast<size_t>(v)];
      const float* w =
          fcW_.data() + static_cast<size_t>(v) * static_cast<size_t>(H);
      for (int j = 0; j < H; ++j) s += w[j] * ht[j];
      logits[static_cast<size_t>(v)] = s;
      if (s > maxv) maxv = s;
    }
    double sumExp = 0.0;
    for (int v = 0; v < charVocab_; ++v) {
      sumExp +=
          std::exp(static_cast<double>(logits[static_cast<size_t>(v)] - maxv));
    }
    int target = ids[t + 1];
    if (target < 0 || target >= charVocab_) target = unk_;
    double logp =
        static_cast<double>(logits[static_cast<size_t>(target)] - maxv) -
        std::log(sumExp);
    sumLog10 += logp * log10e;
    ++scored;
  }
  return scored > 0 ? sumLog10 : 0.0;
}

}  // namespace McBopomofo
