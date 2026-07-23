// Convert a fp32 char-LSTM (LWLSTM1) to weight-only int8 (LWLSTM8).
//
// Per-output-row symmetric int8: for each row, scale = maxabs(row)/127,
// q = clamp(lround(w/scale), -127, 127). Dequant = q*scale. This is exactly
// the round-trip validated in rerank_opt.cpp (v2c tw538 387 → 387, lossless),
// so the engine's int8 loader (same dequant) reproduces the fp32 result.
//
// LWLSTM8 layout (mirrors LWLSTM1 tensor order):
//   magic "LWLSTM8\0", int32 emb,hidden,layers,vocab, vocab strings (i16 len+bytes)
//   emb:  int8[V*E]  + f32 scale[V]
//   per layer: wih int8[4H*in]+f32 scale[4H]; whh int8[4H*H]+f32 scale[4H];
//              bih f32[4H]; bhh f32[4H]
//   fc_w: int8[V*H] + f32 scale[V];  fc_b f32[V]
//
// Usage: quantize_lstm_int8 <in.bin LWLSTM1> <out.bin LWLSTM8>

#include <cmath>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <vector>

namespace {
bool rd(std::ifstream& in, void* p, size_t n) {
  in.read(reinterpret_cast<char*>(p), static_cast<std::streamsize>(n));
  return static_cast<size_t>(in.gcount()) == n;
}
std::vector<float> readF(std::ifstream& in, size_t n) {
  std::vector<float> v(n);
  rd(in, v.data(), n * sizeof(float));
  return v;
}
// Quantize a [rows,cols] row-major tensor → int8 body + per-row f32 scales,
// write both to out. Also returns the dequantized error (max abs) for logging.
double writeRowInt8(std::ofstream& out, const std::vector<float>& w, int rows,
                    int cols) {
  std::vector<int8_t> q(static_cast<size_t>(rows) * cols);
  std::vector<float> scale(rows);
  double maxErr = 0.0;
  for (int r = 0; r < rows; ++r) {
    const float* row = w.data() + static_cast<size_t>(r) * cols;
    float amax = 1e-9f;
    for (int j = 0; j < cols; ++j) amax = std::max(amax, std::fabs(row[j]));
    float s = amax / 127.0f;
    scale[r] = s;
    for (int j = 0; j < cols; ++j) {
      int v = static_cast<int>(std::lround(row[j] / s));
      v = std::max(-127, std::min(127, v));
      q[static_cast<size_t>(r) * cols + j] = static_cast<int8_t>(v);
      maxErr = std::max(maxErr, std::fabs(static_cast<double>(v) * s - row[j]));
    }
  }
  out.write(reinterpret_cast<char*>(q.data()),
            static_cast<std::streamsize>(q.size()));
  out.write(reinterpret_cast<char*>(scale.data()),
            static_cast<std::streamsize>(scale.size() * sizeof(float)));
  return maxErr;
}
}  // namespace

int main(int argc, char** argv) {
  if (argc < 3) {
    std::cerr << "Usage: quantize_lstm_int8 <in LWLSTM1> <out LWLSTM8>\n";
    return 1;
  }
  std::ifstream in(argv[1], std::ios::binary);
  if (!in) { std::cerr << "open in fail\n"; return 1; }
  char magic[8];
  if (!rd(in, magic, 8) || std::memcmp(magic, "LWLSTM1\0", 8) != 0) {
    std::cerr << "bad input magic (expected LWLSTM1)\n";
    return 1;
  }
  int E, H, L, V;
  rd(in, &E, 4); rd(in, &H, 4); rd(in, &L, 4); rd(in, &V, 4);
  std::cout << "in: emb=" << E << " hidden=" << H << " layers=" << L
            << " vocab=" << V << "\n";
  // vocab strings
  std::vector<std::string> vocab(V);
  for (int i = 0; i < V; ++i) {
    int16_t len = 0; rd(in, &len, 2);
    std::string s(len > 0 ? static_cast<size_t>(len) : 0, '\0');
    if (len > 0) rd(in, s.data(), len);
    vocab[i] = s;
  }
  auto emb = readF(in, static_cast<size_t>(V) * E);
  std::vector<std::vector<float>> wih(L), whh(L), bih(L), bhh(L);
  for (int l = 0; l < L; ++l) {
    int inDim = (l == 0) ? E : H;
    wih[l] = readF(in, static_cast<size_t>(4 * H) * inDim);
    whh[l] = readF(in, static_cast<size_t>(4 * H) * H);
    bih[l] = readF(in, 4 * H);
    bhh[l] = readF(in, 4 * H);
  }
  auto fc_w = readF(in, static_cast<size_t>(V) * H);
  auto fc_b = readF(in, V);
  if (!in) { std::cerr << "read body fail\n"; return 1; }

  std::ofstream out(argv[2], std::ios::binary);
  if (!out) { std::cerr << "open out fail\n"; return 1; }
  out.write("LWLSTM8\0", 8);
  out.write(reinterpret_cast<char*>(&E), 4);
  out.write(reinterpret_cast<char*>(&H), 4);
  out.write(reinterpret_cast<char*>(&L), 4);
  out.write(reinterpret_cast<char*>(&V), 4);
  for (int i = 0; i < V; ++i) {
    int16_t len = static_cast<int16_t>(vocab[i].size());
    out.write(reinterpret_cast<char*>(&len), 2);
    if (len > 0) out.write(vocab[i].data(), len);
  }
  double me = 0;
  me = std::max(me, writeRowInt8(out, emb, V, E));
  for (int l = 0; l < L; ++l) {
    int inDim = (l == 0) ? E : H;
    me = std::max(me, writeRowInt8(out, wih[l], 4 * H, inDim));
    me = std::max(me, writeRowInt8(out, whh[l], 4 * H, H));
    out.write(reinterpret_cast<char*>(bih[l].data()), 4 * H * sizeof(float));
    out.write(reinterpret_cast<char*>(bhh[l].data()), 4 * H * sizeof(float));
  }
  me = std::max(me, writeRowInt8(out, fc_w, V, H));
  out.write(reinterpret_cast<char*>(fc_b.data()), V * sizeof(float));
  out.flush();
  std::cout << "wrote " << argv[2] << " (max per-weight dequant err " << me
            << ")\n";
  return 0;
}
