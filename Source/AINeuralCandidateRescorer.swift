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

/// L1 神經候選重排(候選窗路徑)。設計見 docs/l1-neural-rerank-integration.md 第 8 節。
///
/// 核心語義:
/// - focus span 之後右文 >= 2 字才由神經斷言排序(整句打分的優勢全部來自右文;
///   右文為空時與 local scoring 數學等價,神經沒有新資訊)。
/// - 右文不足 = **懸置**:維持引擎排序(回引擎 top,套用端視為 no-op),把決策
///   留給延遲全局重審層(使用者繼續打字、右文出現後在 buffer 內隱形修正)。
///   不退 n-gram —— n-gram 同樣只有左文,重排一樣是瞎猜。
/// - 打分用 AISentenceScorer(鏈式法則 + logit_bias 探針,真整句機率);margin
///   超過門檻才翻,否則維持引擎序。
/// - 偏好關閉時走既有 n-gram(現狀行為,不受本功能影響)。
struct NeuralCandidateRescorer: CandidateRescorer {

    typealias AlternativesScorer = @Sendable (
        _ left: String, _ alternatives: [String], _ right: String, _ deadline: Date
    ) async -> [String: Double]?

    /// 右文至少幾個字才由神經斷言(gate;不足=懸置)。
    static let rightContextMinChars = 2
    /// 打分窗口:focus 左右各取幾個字(鏈式打分成本與窗口成正比)。
    static let leftWindowChars = 6
    static let rightWindowChars = 3
    /// 翻案 margin:最高分比引擎 top 高出此值才重排(sim 掃描:1.0 時引擎本來
    /// 對的零誤翻、錯的仍大多救回)。
    static let decisionMargin = 1.0
    /// 全部候選打分的總預算;逾時=懸置。
    static let totalBudget: TimeInterval = 0.9

    private let fallback = NgramCandidateRescorer()
    private let scorer: AlternativesScorer
    private let isServerReady: @Sendable () -> Bool

    init(
        scorer: @escaping AlternativesScorer = { left, alternatives, right, deadline in
            await AISentenceScorer.shared.scoreAlternatives(
                left: left, alternatives: alternatives, right: right, deadline: deadline)
        },
        isServerReady: @escaping @Sendable () -> Bool = { LlamaServerManager.shared.isReady }
    ) {
        self.scorer = scorer
        self.isServerReady = isServerReady
    }

    // MARK: - CandidateRescorer

    func shouldRescore(_ context: AICandidateRerankContext) -> Bool {
        // 觸發閘門完全沿用既有 collision 偵測;neural/n-gram/懸置在 rescore 內分流。
        fallback.shouldRescore(context)
    }

    func rescore(context: AICandidateRerankContext) async -> Result<String, AICorrectionError> {
        guard Preferences.enableGlobalNeuralRerank else {
            // 功能關閉:維持既有 n-gram 行為,與本功能加入前完全相同。
            return await fallback.rescore(context: context)
        }
        guard let engineTop = context.candidates.first?.value else {
            return .failure(.malformedResponse(backend: AICorrectionBackendName.local))
        }
        // 以下所有「不打」的情況都回引擎 top(懸置=維持引擎序,不是退 n-gram)。
        guard isServerReady() else { return .success(engineTop) }
        guard let split = AICandidateNGramScorer.focusSplit(context: context),
            split.right.count >= Self.rightContextMinChars
        else {
            return .success(engineTop)
        }
        let values = Self.scoringCandidates(in: context).map(\.value)
        guard values.count >= 2 else { return .success(engineTop) }

        let left = String((context.preceding + split.left).suffix(Self.leftWindowChars))
        let right = String(split.right.prefix(Self.rightWindowChars))
        guard let scores = await scorer(
            left, values, right, Date().addingTimeInterval(Self.totalBudget))
        else {
            NSLog("AI神經重排: 打分失敗或逾時,維持引擎排序")
            return .success(engineTop)
        }
        return .success(
            AISentenceScorer.decide(
                scores: scores, current: engineTop, margin: Self.decisionMargin))
    }

    // MARK: - 純邏輯(可單元測試)

    /// 過符號閘門後仍有 >=2 個相異候選值才值得打 server。
    static func eligibleForNeural(_ context: AICandidateRerankContext) -> Bool {
        scoringCandidates(in: context).count >= 2
    }

    /// 要打分的候選:截 maxCandidateCount、沿用符號閘門(除非原 top-1 就是符號,
    /// 否則不讓符號/emoji 參與)、相同值去重(省呼叫)。
    static func scoringCandidates(in context: AICandidateRerankContext) -> [AICandidateRerankEntry] {
        let candidates = Array(context.candidates.prefix(AICandidateReranker.maxCandidateCount))
        guard let top = candidates.first else { return [] }
        let topIsSymbol = AICandidateReranker.isSymbolOrEmoji(top.value)

        var seen = Set<String>()
        var result: [AICandidateRerankEntry] = []
        for candidate in candidates {
            if !topIsSymbol && AICandidateReranker.isSymbolOrEmoji(candidate.value) { continue }
            if !seen.insert(candidate.value).inserted { continue }
            result.append(candidate)
        }
        return result
    }
}
