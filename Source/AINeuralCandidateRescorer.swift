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

/// L1 神經候選重排(設計見 docs/l1-neural-rerank-integration.md)。
///
/// 核心:對候選窗的每個候選,把候選值代入 composing buffer 的 focus span 組成整句
/// (沿用 `AICandidateNGramScorer.contextText`),打 llama-server `/completion` 取整句
/// logprob,選最高分者。這是 PoC harness「focus position global full-sentence preview」
/// 在真實 L1 的對應——引擎 walk 已提供整句 baseline,因此不需要 beam search、
/// logit_bias 與 char→token 映射。
///
/// 鐵則:只在引擎既有候選裡挑,絕不生成;任何失敗一律退回 n-gram。
/// Fallback 條件(全部退 `NgramCandidateRescorer`):
/// - 偏好 `enableGlobalNeuralRerank` 關閉
/// - llama-server 未就緒(不等暖機)
/// - 過符號閘門後相異候選值不足 2 個
/// - 任一候選打分失敗(logprobs 缺失/非有限值)—— 部分分數會偏排序,寧可全退
/// - 超過總預算(300ms)
struct NeuralCandidateRescorer: CandidateRescorer {

    typealias SentenceScorer = @Sendable (String) async -> Double?

    /// 全部候選打分的總預算;逾時退 n-gram,不留使用者等。
    static let totalBudget: TimeInterval = 0.3

    private let fallback = NgramCandidateRescorer()
    private let scorer: SentenceScorer
    private let isNeuralAvailable: @Sendable () -> Bool

    init(
        scorer: @escaping SentenceScorer = { text in
            await LlamaServerManager.shared.scoreLogprob(text: text)
        },
        isNeuralAvailable: @escaping @Sendable () -> Bool = {
            Preferences.enableGlobalNeuralRerank && LlamaServerManager.shared.isReady
        }
    ) {
        self.scorer = scorer
        self.isNeuralAvailable = isNeuralAvailable
    }

    // MARK: - CandidateRescorer

    func shouldRescore(_ context: AICandidateRerankContext) -> Bool {
        // 觸發閘門完全沿用既有 collision 偵測;neural/n-gram 的分流在 rescore 內決定。
        fallback.shouldRescore(context)
    }

    func rescore(context: AICandidateRerankContext) async -> Result<String, AICorrectionError> {
        guard isNeuralAvailable(), Self.eligibleForNeural(context) else {
            return await fallback.rescore(context: context)
        }
        if let best = await Self.neuralBestCandidate(
            context: context, scorer: scorer, budget: Self.totalBudget)
        {
            return .success(best)
        }
        NSLog("AI神經重排: 打分失敗或逾時,退回 n-gram")
        return await fallback.rescore(context: context)
    }

    // MARK: - 純邏輯(可單元測試)

    /// 過符號閘門後仍有 >=2 個相異候選值才值得打 server(= harness 的 |allowed| > 1)。
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

    /// 逐候選代入組整句 → 打分 → 選最高。任一候選失敗或超出預算回 nil(呼叫端 fallback)。
    /// 循序打分:llama-server 單 slot,平行只會排隊;循序還能讓共享前綴命中 KV cache。
    /// 以嚴格大於比較、依引擎順序迭代,同分時自然由引擎原排序勝出。
    static func neuralBestCandidate(
        context: AICandidateRerankContext,
        scorer: @escaping SentenceScorer,
        budget: TimeInterval
    ) async -> String? {
        let candidates = scoringCandidates(in: context)
        guard candidates.count >= 2 else { return nil }

        let deadline = Date().addingTimeInterval(budget)
        var best: String?
        var bestScore = -Double.infinity

        for candidate in candidates {
            let remaining = deadline.timeIntervalSinceNow
            guard remaining > 0 else { return nil }

            let text = AICandidateNGramScorer.contextText(replacingWith: candidate.value, in: context)
            guard let score = await withTimeout(remaining, operation: { await scorer(text) }),
                score.isFinite
            else {
                return nil
            }
            if score > bestScore {
                bestScore = score
                best = candidate.value
            }
        }
        return best
    }

    /// 在時限內完成 operation,否則回 nil 並取消它(URLSession async 呼叫會跟著取消,
    /// 避免廢請求堆在 server 上卡到 L2)。
    static func withTimeout<T: Sendable>(
        _ seconds: TimeInterval, operation: @escaping @Sendable () async -> T?
    ) async -> T? {
        await withTaskGroup(of: T?.self) { group in
            group.addTask { await operation() }
            group.addTask {
                try? await Task.sleep(nanoseconds: UInt64(max(0, seconds) * 1_000_000_000))
                return nil
            }
            let first = await group.next() ?? nil
            group.cancelAll()
            return first
        }
    }
}
