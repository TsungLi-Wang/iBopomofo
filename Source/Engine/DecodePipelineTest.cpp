// DecodePipeline 的測試。
//
// 這些測試看起來很簡單，但它們釘住的是**跨層的相依關係** —— 那些關係原本
// 只存在於 KeyHandler 裡五個散落的 if，沒有任何地方寫下來，也沒有任何測試守著。
#include "DecodePipeline.h"

#include "gtest/gtest.h"

namespace McBopomofo {
namespace {

TEST(DecodePipelineTest, PlainBopomofoTurnsEverythingOff) {
  // 純注音模式的契約：使用者選這個模式就是**不要任何智慧介入**。
  DecodePipeline p = DecodePipeline::plainBopomofo();
  EXPECT_TRUE(p.isPlain());
  EXPECT_FALSE(p.contextModel);
  EXPECT_FALSE(p.neuralRerank);
  EXPECT_FALSE(p.confusionAlphas);
  EXPECT_FALSE(p.grammarRules);
  EXPECT_EQ(p.describe(), "pipeline[unigram-only]");
}

TEST(DecodePipelineTest, DescribeListsActiveLayers) {
  DecodePipeline p;
  p.contextModel = true;
  p.neuralRerank = true;
  p.rerankNu = 0.75;
  p.confusionAlphas = true;
  p.grammarRules = true;
  const std::string d = p.describe();
  EXPECT_NE(d.find("context"), std::string::npos);
  EXPECT_NE(d.find("rerank"), std::string::npos);
  EXPECT_NE(d.find("alphas"), std::string::npos);
  EXPECT_NE(d.find("rules"), std::string::npos);
  EXPECT_NE(d.find("nu=0.75"), std::string::npos);
  EXPECT_FALSE(p.isPlain());
}

TEST(DecodePipelineTest, AlphasAloneStillCountsAsNonPlain) {
  // 頻率壓縮沒有重排就不會生效（它只在 N-best 融合那段動作），
  // 但組態上仍然算「有開東西」—— 這個區別要明確，
  // 否則會誤以為「開了 alphas 卻沒效果」是 bug。
  DecodePipeline p;
  p.confusionAlphas = true;
  EXPECT_FALSE(p.isPlain());
  EXPECT_FALSE(p.neuralRerank);   // 提醒：此時 alphas 實際上不會生效
}

TEST(DecodePipelineTest, DefaultIsPlain) {
  EXPECT_TRUE(DecodePipeline().isPlain());
}

}  // namespace
}  // namespace McBopomofo
