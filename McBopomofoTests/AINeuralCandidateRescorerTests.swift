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

import Foundation
import Testing

@testable import McBopomofo

// .serialized because these tests mutate the shared EnableGlobalNeuralRerank
// preference; without it, parallel execution races on the global key (a test
// that sets the preference false can observe true set by a concurrent test).
@Suite("NeuralCandidateRescorer Tests", .serialized)
struct AINeuralCandidateRescorerTests {

    /// buffer = 我的手機,focus span = 的(cursorIndex 2),右文 = 手機(2 字)。
    private func contextWithRightContext(
        _ values: [(String, String)]
    ) -> AICandidateRerankContext {
        AICandidateRerankContext(
            preceding: "", composingBuffer: "我的手機", cursorIndex: 2,
            candidates: values.map { AICandidateRerankEntry(value: $0.0, reading: $0.1) })
    }

    /// buffer = 我的,focus span = 的 在句尾,右文 = 0 字。
    private func contextWithoutRightContext(
        _ values: [(String, String)]
    ) -> AICandidateRerankContext {
        AICandidateRerankContext(
            preceding: "", composingBuffer: "我的", cursorIndex: 2,
            candidates: values.map { AICandidateRerankEntry(value: $0.0, reading: $0.1) })
    }

    private let dedede = [("的", "ㄉㄜ˙"), ("得", "ㄉㄜ˙"), ("地", "ㄉㄜ˙")]

    private func successValue(_ outcome: Result<String, AICorrectionError>) -> String? {
        if case let .success(text) = outcome { return text }
        return nil
    }

    // MARK: - focusSplit

    @Test("focusSplit 沿 focus span 切出左右文")
    func focusSplitSplitsAroundSpan() {
        let context = contextWithRightContext(dedede)
        let split = AICandidateNGramScorer.focusSplit(context: context)
        #expect(split?.left == "我")
        #expect(split?.right == "手機")
    }

    @Test("focusSplit 於句尾 span 右文為空")
    func focusSplitAtEndHasEmptyRight() {
        let context = contextWithoutRightContext(dedede)
        let split = AICandidateNGramScorer.focusSplit(context: context)
        #expect(split?.left == "我")
        #expect(split?.right == "")
    }

    // MARK: - 純邏輯閘門

    @Test("相異候選不足 2 個不打 server")
    func notEligibleWithSingleDistinctValue() {
        let context = contextWithRightContext([("的", "ㄉㄜ˙"), ("的", "ㄉㄜ˙")])
        #expect(!NeuralCandidateRescorer.eligibleForNeural(context))
    }

    @Test("符號閘門:原 top-1 非符號時,符號候選不參與打分")
    func symbolCandidatesExcludedWhenTopIsText() {
        let context = contextWithRightContext([("的", "ㄉㄜ˙"), ("📁", ""), ("得", "ㄉㄜ˙")])
        let values = NeuralCandidateRescorer.scoringCandidates(in: context).map(\.value)
        #expect(values == ["的", "得"])
    }

    // MARK: - decide(margin 決策)

    @Test("分差過 margin 才翻")
    func decideFlipsOnlyBeyondMargin() {
        let scores = ["的": -10.0, "得": -8.5]
        #expect(AISentenceScorer.decide(scores: scores, current: "的", margin: 1.0) == "得")
        #expect(AISentenceScorer.decide(scores: scores, current: "的", margin: 2.0) == "的")
    }

    @Test("current 沒有分數視為打分不完整,維持 current")
    func decideKeepsCurrentWhenScoreMissing() {
        #expect(AISentenceScorer.decide(scores: ["得": -1.0], current: "的", margin: 1.0) == "的")
    }

    @Test("同分維持 current")
    func decideKeepsCurrentOnTie() {
        let scores = ["的": -5.0, "得": -5.0]
        #expect(AISentenceScorer.decide(scores: scores, current: "的", margin: 0.0) == "的")
    }

    // MARK: - rescore 分流

    @Test("右文不足時懸置:回引擎 top,不打 server")
    func suspendsWithoutRightContext() async {
        setNeuralPreference(true)
        defer { restoreNeuralPreference() }
        let rescorer = NeuralCandidateRescorer(
            scorer: { _, _, _, _ in
                Issue.record("右文不足不應打 server")
                return nil
            },
            isServerReady: { true })
        let outcome = await rescorer.rescore(context: contextWithoutRightContext(dedede))
        #expect(successValue(outcome) == "的")
    }

    @Test("server 未就緒時懸置:回引擎 top,不退 n-gram")
    func suspendsWhenServerNotReady() async {
        setNeuralPreference(true)
        defer { restoreNeuralPreference() }
        let rescorer = NeuralCandidateRescorer(
            scorer: { _, _, _, _ in
                Issue.record("server 未就緒不應打分")
                return nil
            },
            isServerReady: { false })
        let outcome = await rescorer.rescore(context: contextWithRightContext(dedede))
        #expect(successValue(outcome) == "的")
    }

    @Test("右文足夠時打分並依 margin 翻案")
    func rescoresWithRightContext() async {
        setNeuralPreference(true)
        defer { restoreNeuralPreference() }
        let rescorer = NeuralCandidateRescorer(
            scorer: { left, alternatives, right, _ in
                #expect(left == "我")
                #expect(right == "手機")
                #expect(alternatives.contains("的") && alternatives.contains("得"))
                return ["的": -12.0, "得": -20.0, "地": -3.0]
            },
            isServerReady: { true })
        let outcome = await rescorer.rescore(context: contextWithRightContext(dedede))
        #expect(successValue(outcome) == "地")
    }

    @Test("打分失敗時懸置:維持引擎排序")
    func suspendsOnScoringFailure() async {
        setNeuralPreference(true)
        defer { restoreNeuralPreference() }
        let rescorer = NeuralCandidateRescorer(
            scorer: { _, _, _, _ in nil },
            isServerReady: { true })
        let outcome = await rescorer.rescore(context: contextWithRightContext(dedede))
        #expect(successValue(outcome) == "的")
    }

    @Test("偏好關閉時走既有 n-gram,不打 server")
    func fallsBackToNgramWhenDisabled() async {
        setNeuralPreference(false)
        defer { restoreNeuralPreference() }
        let rescorer = NeuralCandidateRescorer(
            scorer: { _, _, _, _ in
                Issue.record("偏好關閉不應打 server")
                return nil
            },
            isServerReady: { true })
        let outcome = await rescorer.rescore(context: contextWithRightContext(dedede))
        guard case let .success(text) = outcome else {
            Issue.record("n-gram fallback 應回建議")
            return
        }
        #expect(["的", "得", "地"].contains(text))
    }

    // MARK: - UserDefaults snapshot(照 PreferencesTests 慣例)

    private static let key = "EnableGlobalNeuralRerank"
    private static let saved = UserDefaults.standard.object(forKey: key)

    private func setNeuralPreference(_ value: Bool) {
        UserDefaults.standard.set(value, forKey: Self.key)
    }

    private func restoreNeuralPreference() {
        if let saved = Self.saved {
            UserDefaults.standard.set(saved, forKey: Self.key)
        } else {
            UserDefaults.standard.removeObject(forKey: Self.key)
        }
    }
}
