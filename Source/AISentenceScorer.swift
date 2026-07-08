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

/// 真・整句機率打分器(鏈式法則 + logit_bias 探針)。
///
/// llama-server 的 /completion 在 n_predict=0 時**不會**回 prompt logprobs——
/// 它會生成一個 token 並回報那個 token 的機率(harness 踩過的雷,見
/// deferred_rerank_sim.py 檔頭)。真正可比的整句分數要用鏈式法則逐 token 取:
/// 對每個位置發一次單 token 呼叫,logit_bias 把目標 token 加 +100 讓 greedy
/// 必中,而回報的 logprob 已實測(build b9692,與無偏 top_logprobs 全精度吻合)
/// 是 **raw** 值——一次呼叫拿到任意目標 token 的精確機率,無 top-k 損失。
///
/// 公平性:各候選一律從「哨兵 + 左文」的頭開始打分。BPE 可能把左文末字與候選
/// 併成單 token(「我再」一個 token、「我/載」兩個),若只從共同前綴起算,合併的
/// 候選會被記入左文字的機率而未合併的不會。從頭打分讓每個候選拿到自己
/// canonical tokenization 下完整字序的 log 機率,才可比。左文前綴呼叫在事件內
/// 快取,跨候選去重,額外成本只在第一個候選。
///
/// cache_prompt=true 讓巢狀前綴增量解碼;呼叫循序(llama-server 單 slot 排隊,
/// 平行沒有好處,循序還能吃 KV cache)。
final class AISentenceScorer: @unchecked Sendable {

    static let shared = AISentenceScorer()

    private let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    /// 對每個候選字(串)打「哨兵+left+候選+right」的整句 logprob 總和。
    /// 任一候選打分失敗或超過 deadline 回 nil(部分分數會偏排序,寧可全退)。
    func scoreAlternatives(
        left: String, alternatives: [String], right: String, deadline: Date
    ) async -> [String: Double]? {
        guard !alternatives.isEmpty else { return nil }
        let sentinelLeft = "\n" + left
        guard let sentinelTokens = await tokenize("\n") else { return nil }

        var probeCache: [ProbeKey: Double] = [:]
        var results: [String: Double] = [:]

        for alternative in alternatives {
            guard let fullTokens = await tokenize(sentinelLeft + alternative + right) else {
                return nil
            }
            var start = 0
            while start < min(sentinelTokens.count, fullTokens.count),
                sentinelTokens[start] == fullTokens[start]
            {
                start += 1
            }

            var total = 0.0
            for index in start..<fullTokens.count {
                guard deadline.timeIntervalSinceNow > 0 else { return nil }
                let key = ProbeKey(prefix: Array(fullTokens[..<index]), target: fullTokens[index])
                if let cached = probeCache[key] {
                    total += cached
                    continue
                }
                guard let logprob = await probeLogprob(
                    prefix: key.prefix, target: key.target)
                else {
                    return nil
                }
                probeCache[key] = logprob
                total += logprob
            }
            results[alternative] = total
        }
        return results
    }

    /// margin 決策(純函式,可測):最高分者比 current 高出 margin 以上才翻,
    /// 否則維持 current。current 沒有分數視為打分不完整,維持 current。
    static func decide(scores: [String: Double], current: String, margin: Double) -> String {
        guard let currentScore = scores[current] else { return current }
        var best = current
        var bestScore = currentScore
        for (value, score) in scores.sorted(by: { $0.key < $1.key }) {
            if score > bestScore {
                bestScore = score
                best = value
            }
        }
        guard best != current, bestScore - currentScore > margin else { return current }
        return best
    }

    // MARK: - server 呼叫

    private struct ProbeKey: Hashable {
        let prefix: [Int]
        let target: Int
    }

    private func baseURL() -> String? {
        LlamaServerManager.shared.isReady ? LlamaServerManager.shared.baseURL : nil
    }

    private func tokenize(_ text: String) async -> [Int]? {
        guard let base = baseURL(), let url = URL(string: base + "/tokenize") else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 2
        guard let body = try? JSONSerialization.data(
            withJSONObject: ["content": text, "add_special": false])
        else { return nil }
        request.httpBody = body
        guard let (data, response) = try? await session.data(for: request),
            (response as? HTTPURLResponse)?.statusCode == 200,
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let tokens = object["tokens"] as? [Int]
        else { return nil }
        return tokens
    }

    /// logit_bias 探針:target +100 → greedy 必中 → 回報的 logprob 是 raw 值。
    /// HTTP 500 = 探到 UTF-8 續位元組(罕見字被拆 byte token,此 server 版本組
    /// 回應時炸掉);字的續位元組給定首位元組後機率趨近 1,以 0 近似,且同一
    /// 事件內所有候選拿到同樣的近似,比較仍公平。
    private func probeLogprob(prefix: [Int], target: Int) async -> Double? {
        guard !prefix.isEmpty, let base = baseURL(),
            let url = URL(string: base + "/completion")
        else { return nil }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 3
        let payload: [String: Any] = [
            "prompt": prefix,
            "n_predict": 1,
            "temperature": 0,
            "logprobs": true,
            "n_probs": 1,
            "cache_prompt": true,
            "logit_bias": [String(target): 100.0],
        ]
        guard let body = try? JSONSerialization.data(withJSONObject: payload) else { return nil }
        request.httpBody = body

        guard let (data, response) = try? await session.data(for: request) else { return nil }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        if status == 500 {
            return 0.0
        }
        guard status == 200,
            let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let probabilities = object["completion_probabilities"] as? [[String: Any]],
            let first = probabilities.first,
            first["id"] as? Int == target,
            let logprob = first["logprob"] as? Double,
            logprob.isFinite
        else { return nil }
        return logprob
    }
}
