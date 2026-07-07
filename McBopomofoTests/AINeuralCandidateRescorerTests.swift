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

@Suite("NeuralCandidateRescorer Tests")
struct AINeuralCandidateRescorerTests {

    private func makeContext(_ values: [(String, String)], buffer: String = "我在") -> AICandidateRerankContext {
        AICandidateRerankContext(
            preceding: "",
            composingBuffer: buffer,
            cursorIndex: buffer.count,
            candidates: values.map { AICandidateRerankEntry(value: $0.0, reading: $0.1) })
    }

    @Test("相異候選不足 2 個不打 server")
    func notEligibleWithSingleDistinctValue() {
        let context = makeContext([("在", "ㄗㄞˋ"), ("在", "ㄗㄞˋ")])
        #expect(!NeuralCandidateRescorer.eligibleForNeural(context))
    }

    @Test("同音相異候選 >=2 個才打 server")
    func eligibleWithTwoDistinctValues() {
        let context = makeContext([("在", "ㄗㄞˋ"), ("再", "ㄗㄞˋ")])
        #expect(NeuralCandidateRescorer.eligibleForNeural(context))
    }

    @Test("符號閘門:原 top-1 非符號時,符號候選不參與打分")
    func symbolCandidatesExcludedWhenTopIsText() {
        let context = makeContext([("在", "ㄗㄞˋ"), ("📁", ""), ("再", "ㄗㄞˋ")])
        let values = NeuralCandidateRescorer.scoringCandidates(in: context).map(\.value)
        #expect(values == ["在", "再"])
    }

    @Test("打分選最高者")
    func picksHighestScoringCandidate() async {
        let context = makeContext([("在", "ㄗㄞˋ"), ("再", "ㄗㄞˋ")])
        let best = await NeuralCandidateRescorer.neuralBestCandidate(
            context: context,
            scorer: { text in text.contains("再") ? -3.0 : -8.0 },
            budget: 5)
        #expect(best == "再")
    }

    @Test("同分時引擎原順序勝出")
    func enginOrderWinsOnTie() async {
        let context = makeContext([("在", "ㄗㄞˋ"), ("再", "ㄗㄞˋ")])
        let best = await NeuralCandidateRescorer.neuralBestCandidate(
            context: context, scorer: { _ in -5.0 }, budget: 5)
        #expect(best == "在")
    }

    @Test("任一候選打分失敗回 nil(呼叫端 fallback n-gram)")
    func anyNilScoreFallsBack() async {
        let context = makeContext([("在", "ㄗㄞˋ"), ("再", "ㄗㄞˋ")])
        let best = await NeuralCandidateRescorer.neuralBestCandidate(
            context: context,
            scorer: { text in text.contains("再") ? nil : -1.0 },
            budget: 5)
        #expect(best == nil)
    }

    @Test("非有限分數視為失敗")
    func nonFiniteScoreFallsBack() async {
        let context = makeContext([("在", "ㄗㄞˋ"), ("再", "ㄗㄞˋ")])
        let best = await NeuralCandidateRescorer.neuralBestCandidate(
            context: context,
            scorer: { _ in -Double.infinity },
            budget: 5)
        #expect(best == nil)
    }

    @Test("超出總預算回 nil")
    func budgetExceededFallsBack() async {
        let context = makeContext([("在", "ㄗㄞˋ"), ("再", "ㄗㄞˋ")])
        let best = await NeuralCandidateRescorer.neuralBestCandidate(
            context: context,
            scorer: { _ in
                try? await Task.sleep(nanoseconds: 500_000_000)
                return -1.0
            },
            budget: 0.05)
        #expect(best == nil)
    }

    @Test("neural 不可用時 rescore 走 n-gram fallback 仍回建議")
    func rescoreFallsBackToNgramWhenUnavailable() async {
        let rescorer = NeuralCandidateRescorer(
            scorer: { _ in
                Issue.record("neural 不可用時不應打 server")
                return nil
            },
            isNeuralAvailable: { false })
        let context = makeContext([("在", "ㄗㄞˋ"), ("再", "ㄗㄞˋ")])
        let outcome = await rescorer.rescore(context: context)
        guard case let .success(text) = outcome else {
            Issue.record("n-gram fallback 應回建議")
            return
        }
        #expect(["在", "再"].contains(text))
    }
}
