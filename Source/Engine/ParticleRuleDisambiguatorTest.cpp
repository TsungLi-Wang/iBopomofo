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

#include "ParticleRuleDisambiguator.h"

#include <sstream>
#include <string>
#include <vector>

#include <map>
#include <memory>

#include "gtest/gtest.h"
#include "gramambular2/reading_grid.h"

namespace McBopomofo {
namespace {

constexpr char kTable[] =
    "READING\tㄉㄜ˙\n"
    "FROM\t的\n"
    "TO\t得\n"
    "HEAD\t看\n"
    "HEAD\t養\n"
    "HEAD\t打\n"
    "HEAD\t唱\n"
    "HEAD\t省\n"
    "TAIL\t懂\n"
    "TAIL\t起\n"
    "TAIL\t過\n"
    "NEVER\t真的\n"
    "NEVERHEAD\t我\n"
    "NOUN\t過法\n";

ParticleRuleDisambiguator MakeDisambiguator() {
  ParticleRuleDisambiguator d;
  std::istringstream iss(kTable);
  EXPECT_TRUE(d.load(iss));
  return d;
}

std::vector<std::string> Chars(std::initializer_list<const char*> l) {
  return std::vector<std::string>(l.begin(), l.end());
}

// ── rescoreWalk 的測試用語言模型 ──
// 只需要「看／的／得／懂」這幾個字，分數讓 walk 預設會選出「看的懂」，
// 這樣規則才有東西可以改。
class TinyLM : public Formosa::Gramambular2::LanguageModel {
 public:
  TinyLM() {
    // Unigram(值, 分數) —— 讀音是 map 的 key，不進 Unigram。
    db_["ㄎㄢˋ"].emplace_back("看", -1.0);
    db_["ㄉㄜ˙"].emplace_back("的", -1.0);   // 詞頻讓「的」勝出
    db_["ㄉㄜ˙"].emplace_back("得", -6.0);
    db_["ㄉㄨㄥˇ"].emplace_back("懂", -1.0);
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

Formosa::Gramambular2::ReadingGrid MakeGrid() {
  Formosa::Gramambular2::ReadingGrid grid(std::make_shared<TinyLM>());
  grid.setReadingSeparator("-");
  for (const char* r : {"ㄎㄢˋ", "ㄉㄜ˙", "ㄉㄨㄥˇ"}) {
    grid.setCursor(grid.length());
    EXPECT_TRUE(grid.insertReading(r));
  }
  return grid;
}

std::string Joined(const Formosa::Gramambular2::ReadingGrid::WalkResult& w) {
  std::string s;
  for (size_t i = 0; i < w.nodes.size(); ++i) s += w.chosenValueAt(i);
  return s;
}

TEST(ParticleRuleDisambiguatorTest, LoadsTable) {
  ParticleRuleDisambiguator d = MakeDisambiguator();
  EXPECT_TRUE(d.isLoaded());
  EXPECT_FALSE(d.empty());
}

TEST(ParticleRuleDisambiguatorTest, BadTableDoesNotLoad) {
  ParticleRuleDisambiguator d;
  std::istringstream iss("# 只有註解\nGARBAGE\nHEAD\n");
  EXPECT_FALSE(d.load(iss));
  EXPECT_FALSE(d.isLoaded());
}

// 動詞 + 的 + 結果補語 → 改成得
TEST(ParticleRuleDisambiguatorTest, FlipsVerbPlusResultComplement) {
  ParticleRuleDisambiguator d = MakeDisambiguator();
  EXPECT_TRUE(d.shouldFlip(Chars({"看", "的", "懂"}), 1));
  EXPECT_TRUE(d.shouldFlip(Chars({"養", "的", "起"}), 1));
  EXPECT_TRUE(d.shouldFlip(Chars({"打", "的", "過"}), 1));
}

// 右邊不是補語 → 不動（唱的歌）
TEST(ParticleRuleDisambiguatorTest, KeepsAttributiveDe) {
  ParticleRuleDisambiguator d = MakeDisambiguator();
  EXPECT_FALSE(d.shouldFlip(Chars({"唱", "的", "歌"}), 1));
}

// 左邊不是動詞 → 不動（我的書）
TEST(ParticleRuleDisambiguatorTest, KeepsPronounPossessive) {
  ParticleRuleDisambiguator d = MakeDisambiguator();
  EXPECT_FALSE(d.shouldFlip(Chars({"我", "的", "書"}), 1));
}

// 固定詞絕不碰（真的）
TEST(ParticleRuleDisambiguatorTest, NeverTouchesFixedWords) {
  ParticleRuleDisambiguator d = MakeDisambiguator();
  EXPECT_FALSE(d.shouldFlip(Chars({"真", "的", "懂"}), 1));
}

// 右邊兩字是名詞 → 不動（省錢的過法，「過法」是名詞不是補語）
TEST(ParticleRuleDisambiguatorTest, NounGuardBlocksFlip) {
  ParticleRuleDisambiguator d = MakeDisambiguator();
  EXPECT_FALSE(d.shouldFlip(Chars({"省", "的", "過", "法"}), 1));
  // 同樣的左右字，但後面不構成名詞 → 照常改
  EXPECT_TRUE(d.shouldFlip(Chars({"省", "的", "過", "頭"}), 1));
}

// 句首句尾沒有前後文 → 不動
TEST(ParticleRuleDisambiguatorTest, IgnoresBoundaries) {
  ParticleRuleDisambiguator d = MakeDisambiguator();
  EXPECT_FALSE(d.shouldFlip(Chars({"的", "懂"}), 0));
  EXPECT_FALSE(d.shouldFlip(Chars({"看", "的"}), 1));
}

// 注入的詞庫查詢也要能擋
TEST(ParticleRuleDisambiguatorTest, DictionaryLookupBlocksFlip) {
  ParticleRuleDisambiguator d = MakeDisambiguator();
  d.setDictionaryLookup(
      [](const std::string& w) { return w == "過頭"; });
  EXPECT_FALSE(d.shouldFlip(Chars({"省", "的", "過", "頭"}), 1));
}

// ── rescoreWalk：整條路徑上實際改字 ──
// 這幾個測試補的是先前完全沒有涵蓋的部分。之前 9 個測試全部只測 shouldFlip
// （純粹的字串判斷），而「會不會跟使用者搶」「改字有沒有真的生效」都在
// rescoreWalk 裡 —— 那才是會傷到使用者的地方。

TEST(ParticleRuleDisambiguatorTest, RescoreWalkFlipsOnPath) {
  ParticleRuleDisambiguator d = MakeDisambiguator();
  auto grid = MakeGrid();
  auto walk = grid.walk();
  ASSERT_EQ(Joined(walk), "看的懂");   // 詞頻讓「的」勝出
  EXPECT_TRUE(d.rescoreWalk(walk));
  EXPECT_EQ(Joined(walk), "看得懂");   // 規則把它改成「得」
}

TEST(ParticleRuleDisambiguatorTest, RescoreWalkNeverOverridesUserChoice) {
  // 使用者手動選了「的」→ 規則不准改回去。
  // 這是最惱人的一類 bug：使用者剛選完，字又自己跳掉。
  ParticleRuleDisambiguator d = MakeDisambiguator();
  auto grid = MakeGrid();
  grid.setCursor(2);
  ASSERT_TRUE(grid.overrideCandidate(1, "的"));
  auto walk = grid.walk();
  ASSERT_EQ(Joined(walk), "看的懂");
  EXPECT_FALSE(d.rescoreWalk(walk));
  EXPECT_EQ(Joined(walk), "看的懂");   // 維持使用者的選擇
}

TEST(ParticleRuleDisambiguatorTest, RescoreWalkIsIdempotent) {
  // 同一條路徑跑兩次，第二次不該再回報「有改動」——
  // 否則呼叫端會以為狀態一直在變。
  ParticleRuleDisambiguator d = MakeDisambiguator();
  auto grid = MakeGrid();
  auto walk = grid.walk();
  EXPECT_TRUE(d.rescoreWalk(walk));
  EXPECT_EQ(Joined(walk), "看得懂");
  d.rescoreWalk(walk);
  EXPECT_EQ(Joined(walk), "看得懂");
}

TEST(ParticleRuleDisambiguatorTest, EmptyTableLeavesWalkAlone) {
  ParticleRuleDisambiguator d;   // 沒載入任何規則
  auto grid = MakeGrid();
  auto walk = grid.walk();
  const std::string before = Joined(walk);
  EXPECT_FALSE(d.rescoreWalk(walk));
  EXPECT_EQ(Joined(walk), before);
}

}  // namespace
}  // namespace McBopomofo
