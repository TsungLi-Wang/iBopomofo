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

// 這一份**只測安全契約**，不測「選得準不準」。
//
// 準不準要用兩份真實語料逐題配對量（scripts/node-expert-ab.sh），不是用
// gtest 的幾個例子；但下面這些是「不管模型多準都不准違反」的性質，而且它們
// 一旦壞掉不會報錯 —— 只會靜默地改人家的字。所以釘在測試裡。

#include "NodeHomophoneExpert.h"

#include <cstdio>
#include <fstream>
#include <map>
#include <memory>
#include <string>
#include <vector>

#include "CorpusBigramContextModel.h"
#include "gramambular2/reading_grid.h"
#include "gtest/gtest.h"

namespace iBopomofo {
namespace {

using Formosa::Gramambular2::ReadingGrid;

constexpr int kEmb = 2;
constexpr int kSylEmb = 2;
constexpr int kHid = 2;
constexpr int kCtxChars = 6;
constexpr int kCandChars = 4;
constexpr int kMaxCands = 24;

void WriteFloats(std::ofstream& out, const std::vector<float>& v) {
  out.write(reinterpret_cast<const char*>(v.data()),
            static_cast<std::streamsize>(v.size() * sizeof(float)));
}

void WriteTable(std::ofstream& out, const std::vector<std::string>& v) {
  for (const std::string& s : v) {
    int16_t len = static_cast<int16_t>(s.size());
    out.write(reinterpret_cast<const char*>(&len), 2);
    out.write(s.data(), len);
  }
}

// 造一顆玩具模型：分數只看候選的「是不是 walk 選的」那一格，而且係數為負。
// 也就是說 **它一定想把引擎現在選的字換掉** —— 正好拿來驗「該擋的有沒有擋住」。
// 分差固定約 0.072，所以 τ=0 會出手、τ=1 會棄權。
std::string WriteToyModel() {
  std::string path = std::string(std::tmpnam(nullptr)) + ".iznexp";
  std::ofstream out(path, std::ios::binary);
  const char magic[8] = {'I', 'Z', 'N', 'E', 'X', 'P', '1', '\0'};
  out.write(magic, 8);
  const std::vector<std::string> chars = {"<pad>", "<unk>", "作", "做",
                                          "的",    "得",    "很"};
  const std::vector<std::string> syls = {"<pad>", "<unk>", "ㄗㄨㄛˋ", "ㄉㄜ˙",
                                         "ㄏㄣˇ"};
  int32_t hdr[5] = {kEmb, kSylEmb, kHid, static_cast<int32_t>(chars.size()),
                    static_cast<int32_t>(syls.size())};
  int32_t dims[3] = {kCtxChars, kCandChars, kMaxCands};
  out.write(reinterpret_cast<const char*>(hdr), sizeof(hdr));
  out.write(reinterpret_cast<const char*>(dims), sizeof(dims));
  WriteTable(out, chars);
  WriteTable(out, syls);

  WriteFloats(out, std::vector<float>(chars.size() * kEmb, 0.f));
  WriteFloats(out, std::vector<float>(syls.size() * kSylEmb, 0.f));

  const size_t ctxIn = static_cast<size_t>(kEmb) * kCtxChars * 2 + kSylEmb + 1;
  WriteFloats(out, std::vector<float>(kHid * ctxIn, 0.f));   // ctx.0 W
  WriteFloats(out, std::vector<float>(kHid, 0.f));           // ctx.0 b
  WriteFloats(out, std::vector<float>(kHid * kHid, 0.f));    // ctx.2 W
  WriteFloats(out, std::vector<float>(kHid, 0.f));           // ctx.2 b

  const size_t candIn = static_cast<size_t>(kEmb) * kCandChars + 4;
  std::vector<float> cand0(kHid * candIn, 0.f);
  cand0[candIn - 1] = -1.f;  // 第 0 列只吃 is_walk_choice，係數 −1
  WriteFloats(out, cand0);
  WriteFloats(out, std::vector<float>(kHid, 0.f));
  std::vector<float> cand1(kHid * kHid, 0.f);
  cand1[0] = 1.f;  // 直通第 0 維
  WriteFloats(out, cand1);
  WriteFloats(out, std::vector<float>(kHid, 0.f));

  std::vector<float> head0(kHid * 2 * kHid, 0.f);
  head0[kHid] = 1.f;  // joined 的第 hid 格 = 候選向量第 0 維
  WriteFloats(out, head0);
  WriteFloats(out, std::vector<float>(kHid, 0.f));
  std::vector<float> head1(kHid, 0.f);
  head1[0] = 1.f;
  WriteFloats(out, head1);
  WriteFloats(out, std::vector<float>(1, 0.f));
  out.close();
  return path;
}

// ㄗㄨㄛˋ 有兩個候選（作勝出），ㄉㄜ˙ 也有兩個（的勝出）。
class TinyLM : public Formosa::Gramambular2::LanguageModel {
 public:
  TinyLM() {
    db_["ㄗㄨㄛˋ"].emplace_back("作", -1.0);
    db_["ㄗㄨㄛˋ"].emplace_back("做", -3.0);
    db_["ㄉㄜ˙"].emplace_back("的", -1.0);
    db_["ㄉㄜ˙"].emplace_back("得", -6.0);
    db_["ㄏㄣˇ"].emplace_back("很", -1.0);
  }
  std::vector<Unigram> getUnigrams(const std::string& key) override {
    auto f = db_.find(key);
    return f == db_.end() ? std::vector<Unigram>() : f->second;
  }
  bool hasUnigrams(const std::string& key) override {
    return db_.find(key) != db_.end();
  }

 private:
  std::map<std::string, std::vector<Unigram>> db_;
};

ReadingGrid MakeGrid(const std::vector<const char*>& readings) {
  ReadingGrid grid(std::make_shared<TinyLM>());
  grid.setReadingSeparator("-");
  for (const char* r : readings) {
    grid.setCursor(grid.length());
    EXPECT_TRUE(grid.insertReading(r));
  }
  return grid;
}

std::string Joined(const ReadingGrid::WalkResult& w) {
  std::string s;
  for (size_t i = 0; i < w.nodes.size(); ++i) s += w.chosenValueAt(i);
  return s;
}

class NodeExpertFixture : public ::testing::Test {
 protected:
  void SetUp() override {
    path_ = WriteToyModel();
    ASSERT_TRUE(expert_.load(path_));
    expert_.setContextModel(&cm_);
  }
  void TearDown() override { std::remove(path_.c_str()); }

  std::string path_;
  NodeHomophoneExpert expert_;
  CorpusBigramContextModel cm_;  // 空表：PMI 一律 0，特徵仍然餵得出來
};

TEST_F(NodeExpertFixture, LoadsToyModel) {
  EXPECT_TRUE(expert_.isLoaded());
  EXPECT_GT(expert_.parameterCount(), 0u);
  // 預設白名單只有作做坐座那個讀音。
  EXPECT_EQ(expert_.fireReadings().size(), 1u);
  EXPECT_EQ(expert_.fireReadings().count("ㄗㄨㄛˋ"), 1u);
}

TEST_F(NodeExpertFixture, FiresOnWhitelistedReading) {
  ReadingGrid grid = MakeGrid({"ㄗㄨㄛˋ"});
  auto w = grid.walk();
  ASSERT_EQ(Joined(w), "作");
  expert_.setTau(0.0);
  EXPECT_TRUE(expert_.rescoreWalk(w));
  EXPECT_EQ(Joined(grid.walk()), "做");
  EXPECT_EQ(expert_.counters().fired, 1);
}

// 棄權是預設行為，不是失敗以後補的補丁。
TEST_F(NodeExpertFixture, AbstainsWhenMarginBelowTau) {
  ReadingGrid grid = MakeGrid({"ㄗㄨㄛˋ"});
  auto w = grid.walk();
  expert_.setTau(1.0);
  EXPECT_FALSE(expert_.rescoreWalk(w));
  EXPECT_EQ(Joined(grid.walk()), "作");
  EXPECT_EQ(expert_.counters().fired, 0);
  EXPECT_EQ(expert_.counters().abstained_tau, 1);
}

// 白名單以外的讀音一律不碰，就算模型很想改。
TEST_F(NodeExpertFixture, DoesNotFireOutsideWhitelist) {
  ReadingGrid grid = MakeGrid({"ㄉㄜ˙"});
  auto w = grid.walk();
  expert_.setTau(0.0);
  EXPECT_FALSE(expert_.rescoreWalk(w));
  EXPECT_EQ(Joined(grid.walk()), "的");
  EXPECT_EQ(expert_.counters().considered, 0);
}

// ㄉㄜ˙ 是硬擋：**就算有人把它加進白名單也不准出手**。
// PTT 上「該寫得」有很大比例寫成「的」，那組神經路線已死（dead-ends D）。
TEST_F(NodeExpertFixture, NeverFiresOnDeEvenIfWhitelisted) {
  expert_.setFireReadings({"ㄉㄜ˙", "ㄗㄨㄛˋ"});
  ReadingGrid grid = MakeGrid({"ㄉㄜ˙"});
  auto w = grid.walk();
  expert_.setTau(0.0);
  EXPECT_FALSE(expert_.rescoreWalk(w));
  EXPECT_EQ(Joined(grid.walk()), "的");
  EXPECT_EQ(expert_.counters().considered, 0);
}

// 使用者手選過的節點永不被蓋（0007 第三條）。
TEST_F(NodeExpertFixture, NeverOverridesUserChoice) {
  ReadingGrid grid = MakeGrid({"ㄗㄨㄛˋ"});
  auto w0 = grid.walk();
  ASSERT_TRUE(w0.nodes[0]->selectOverrideUnigram(
      "作", ReadingGrid::Node::OverrideType::kOverrideValueWithHighScore));
  auto w = grid.walk();
  ASSERT_EQ(Joined(w), "作");
  expert_.setTau(0.0);
  EXPECT_FALSE(expert_.rescoreWalk(w));
  EXPECT_EQ(Joined(grid.walk()), "作");
  EXPECT_EQ(expert_.counters().skipped_user_override, 1);
}

// 沒有 context model 就餵不出跟訓練同一套特徵 → 寧可什麼都不做。
TEST_F(NodeExpertFixture, DoesNothingWithoutContextModel) {
  expert_.setContextModel(nullptr);
  ReadingGrid grid = MakeGrid({"ㄗㄨㄛˋ"});
  auto w = grid.walk();
  expert_.setTau(0.0);
  EXPECT_FALSE(expert_.rescoreWalk(w));
  EXPECT_EQ(Joined(grid.walk()), "作");
}

// 沒載模型的專家是完全惰性的（出貨預設就是這個狀態）。
TEST(NodeHomophoneExpertTest, UnloadedIsInert) {
  NodeHomophoneExpert expert;
  CorpusBigramContextModel cm;
  expert.setContextModel(&cm);
  EXPECT_FALSE(expert.isLoaded());
  ReadingGrid grid = MakeGrid({"ㄗㄨㄛˋ"});
  auto w = grid.walk();
  EXPECT_FALSE(expert.rescoreWalk(w));
  EXPECT_EQ(Joined(grid.walk()), "作");
}

TEST(NodeHomophoneExpertTest, RejectsWrongMagic) {
  NodeHomophoneExpert expert;
  std::string path = std::string(std::tmpnam(nullptr)) + ".bad";
  {
    std::ofstream out(path, std::ios::binary);
    // 故意寫路徑層的 magic：那是單向堆疊 LSTM，架構對不上，
    // 「換副檔名接得上」是假的。
    out << "LWLSTM8";
    out.put('\0');
  }
  EXPECT_FALSE(expert.load(path));
  std::remove(path.c_str());
}

}  // namespace
}  // namespace iBopomofo
