// Copyright (c) 2022 and onwards The McBopomofo Authors.
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

import Testing

@testable import McBopomofo

@Suite("AICorrectionPrompt Tests")
struct AICorrectionPromptTests {

    // MARK: - taggedPrompt

    @Test("taggedPrompt 會把 guess 與 preceding 帶入模板")
    func taggedPromptEmbedsArguments() {
        let prompt = AICorrectionPrompt.taggedPrompt(guess: "我在去買", preceding: "等一下")
        #expect(prompt.contains("待修正:我在去買"))
        #expect(prompt.contains("前文(僅供語意參考,不要輸出):等一下"))
        // 應交代輸出標記，讓解析端能抓到結果。
        #expect(prompt.contains("<<<R>>>"))
        #expect(prompt.contains("<<<E>>>"))
    }

    @Test("taggedPrompt 接受空前文")
    func taggedPromptAllowsEmptyPreceding() {
        let prompt = AICorrectionPrompt.taggedPrompt(guess: "怎摸", preceding: "")
        #expect(prompt.contains("待修正:怎摸"))
    }

    // MARK: - extractTaggedResult

    @Test("extractTaggedResult 抓出標記之間的內容並去除空白")
    func extractTaggedResultBetweenMarkers() {
        #expect(AICorrectionPrompt.extractTaggedResult(from: "<<<R>>>我再去買<<<E>>>") == "我再去買")
        #expect(
            AICorrectionPrompt.extractTaggedResult(from: "前綴\n<<<R>>>  我再去買  <<<E>>>\n後綴")
                == "我再去買")
    }

    @Test("extractTaggedResult 在標記間為空時回傳 nil")
    func extractTaggedResultEmptyBetweenMarkers() {
        #expect(AICorrectionPrompt.extractTaggedResult(from: "<<<R>>>   <<<E>>>") == nil)
    }

    @Test("extractTaggedResult 無標記時退回最後一個非空行")
    func extractTaggedResultFallbackToLastLine() {
        #expect(AICorrectionPrompt.extractTaggedResult(from: "第一行\n  我知道  \n") == "我知道")
        #expect(AICorrectionPrompt.extractTaggedResult(from: "單行結果") == "單行結果")
    }

    // MARK: - cleanLocalResult

    @Test("cleanLocalResult 去除外層引號與標點")
    func cleanLocalResultStripsQuotesAndPunctuation() {
        #expect(AICorrectionPrompt.cleanLocalResult("「我再去買」") == "我再去買")
        #expect(AICorrectionPrompt.cleanLocalResult("我知道。") == "我知道")
        #expect(AICorrectionPrompt.cleanLocalResult("\"知道\"") == "知道")
    }

    @Test("cleanLocalResult 切掉模型回填的標籤，只留標籤後內容")
    func cleanLocalResultStripsLabels() {
        #expect(AICorrectionPrompt.cleanLocalResult("待修正：我再去買") == "我再去買")
        #expect(AICorrectionPrompt.cleanLocalResult("前文：你好 待修正：我再去買") == "我再去買")
    }

    @Test("cleanLocalResult 對空白或全被剝光的輸入回傳 nil")
    func cleanLocalResultReturnsNilWhenEmpty() {
        #expect(AICorrectionPrompt.cleanLocalResult("    ") == nil)
        #expect(AICorrectionPrompt.cleanLocalResult("「」") == nil)
    }

    @Test("cleanLocalResult 已乾淨的句子原樣保留")
    func cleanLocalResultKeepsCleanSentence() {
        #expect(AICorrectionPrompt.cleanLocalResult("你好嗎") == "你好嗎")
    }
}
