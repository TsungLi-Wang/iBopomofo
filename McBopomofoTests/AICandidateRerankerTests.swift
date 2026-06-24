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

@Suite("AICandidateReranker Tests")
struct AICandidateRerankerTests {

    @Test("rerankPrompt 會帶入前文、組字與候選")
    func rerankPromptEmbedsContext() {
        let prompt = AICorrectionPrompt.rerankPrompt(context: .init(
            preceding: "水果店",
            composingBuffer: "我在去買",
            candidates: ["我在去買", "我再去買"]))

        #expect(prompt.contains("前文:水果店"))
        #expect(prompt.contains("目前組字:我在去買"))
        #expect(prompt.contains("候選:我在去買|我再去買"))
        #expect(prompt.contains("<<<R>>>"))
        #expect(prompt.contains("<<<E>>>"))
    }

    @Test("extractRerankSuggestion 抓出標記內容")
    func extractRerankSuggestionBetweenMarkers() {
        #expect(AICorrectionPrompt.extractRerankSuggestion(from: "<<<R>>>我再去買<<<E>>>") == "我再去買")
        #expect(AICorrectionPrompt.extractRerankSuggestion(from: "<<<R>>> 知道 <<<E>>>") == "知道")
    }

    @Test("extractRerankSuggestion 清理模型常見前綴")
    func extractRerankSuggestionCleansLabels() {
        #expect(AICorrectionPrompt.extractRerankSuggestion(from: "AI建議:怎麼") == "怎麼")
        #expect(AICorrectionPrompt.extractRerankSuggestion(from: "建議：知道") == "知道")
    }

    @Test("extractRerankSuggestion 空結果回傳 nil")
    func extractRerankSuggestionReturnsNilForEmptyResult() {
        #expect(AICorrectionPrompt.extractRerankSuggestion(from: "<<<R>>>   <<<E>>>") == nil)
        #expect(AICorrectionPrompt.extractRerankSuggestion(from: "「」") == nil)
    }

    @Test("shouldTrigger 會尊重新偏好設定")
    func shouldTriggerRespectsPreference() {
        let original = Preferences.enableAICandidateRerank
        Preferences.enableAICandidateRerank = false
        defer { Preferences.enableAICandidateRerank = original }

        let context = AICandidateRerankContext(
            preceding: "水果店", composingBuffer: "我在去買", candidates: ["我在去買"])
        #expect(AICandidateReranker.shouldTrigger(for: context) == false)
    }

    @Test("reorderedCandidates 會把命中的 AI 建議移到第一位")
    func reorderedCandidatesMovesMatchedSuggestionToFront() {
        let original = [
            InputState.Candidate(reading: "ㄗㄞˋ", value: "在", displayText: "在", rawValue: "在"),
            InputState.Candidate(reading: "ㄗㄞˋ", value: "再", displayText: "再", rawValue: "再"),
            InputState.Candidate(reading: "ㄗㄞˋ", value: "載", displayText: "載", rawValue: "載"),
        ]

        let reordered = AICandidateReranker.reorderedCandidates(
            suggestion: "再", candidates: original)
        #expect(reordered?.map(\.value) == ["再", "在", "載"])
    }

    @Test("reorderedCandidates 未命中候選時回傳 nil")
    func reorderedCandidatesReturnsNilForOutOfListSuggestion() {
        let original = [
            InputState.Candidate(reading: "ㄇㄜ˙", value: "麼", displayText: "麼", rawValue: "麼")
        ]

        #expect(AICandidateReranker.reorderedCandidates(suggestion: "怎麼", candidates: original) == nil)
    }
}
