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

#include "gtest/gtest.h"

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

}  // namespace
}  // namespace McBopomofo
