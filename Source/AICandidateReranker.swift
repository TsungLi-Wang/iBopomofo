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
import OpenCCBridge

struct AICandidateRerankEntry: Equatable {
    let value: String
    let reading: String
}

struct AICandidateRerankContext: Equatable {
    let preceding: String
    let composingBuffer: String
    let candidates: [AICandidateRerankEntry]
}

enum AICandidateReranker {

    static let maxCandidateCount = 8
    static let debounceInterval: TimeInterval = 0.15
    static let serverRetryInterval: TimeInterval = 2.0
    static let maxServerRetryAttempts = 6

    private static let ambiguousCharacters = Set("在再的得地做作知資麼摸裡裏裡哪那裡这這")

    /// 是否值得啟動 L1（不檢查 server 就緒；暖機重試由 controller 處理）。
    static func shouldSchedule(for context: AICandidateRerankContext) -> Bool {
        guard Preferences.enableAICandidateRerank else { return false }
        guard context.composingBuffer.count >= 2 else { return false }
        guard LocalServerAICorrector.isModelInstalled else { return false }
        return needsSemanticRerank(for: context)
    }

    /// 可立即呼叫本機 server 執行 L1。
    static func canInvokeLocalModel() -> Bool {
        LocalServerAICorrector.isModelInstalled && LocalServerAICorrector.isReady
    }

    static func needsSemanticRerank(for context: AICandidateRerankContext) -> Bool {
        let entries = Array(context.candidates.prefix(maxCandidateCount))
        guard !entries.isEmpty else { return false }

        if hasReadingCollision(in: entries) {
            return true
        }

        if hasPhraseAlternativeCollision(in: entries) {
            return true
        }

        if containsAmbiguity(in: context.composingBuffer), entries.count >= 2 {
            let distinctValues = Set(entries.map(\.value))
            if distinctValues.count >= 2 {
                return true
            }
        }

        return false
    }

    static func hasReadingCollision(in entries: [AICandidateRerankEntry]) -> Bool {
        var readingToValues: [String: Set<String>] = [:]
        for entry in entries {
            let reading = normalizedReading(entry.reading)
            guard !reading.isEmpty else { continue }
            readingToValues[reading, default: []].insert(entry.value)
        }
        return readingToValues.values.contains { $0.count >= 2 }
    }

    /// 多字候選彼此「近似同音」時才觸發:音節數相同、且僅差一個音節(其餘相同)。
    /// 例:資道(ㄗ/ㄉㄠˋ) vs 知道(ㄓ/ㄉㄠˋ) 只差首音節 → 觸發。
    ///
    /// 舊版只要候選裡有任兩個不同的多字詞就觸發,等同每次多字選字都打 server,
    /// 過度觸發、浪費本機推理。改為要求結構上接近的同音詞才送 server 判斷;
    /// 讀音完全相同的同音詞已由 `hasReadingCollision` 覆蓋,這裡專收「平翹舌/
    /// 捲舌不分」這類差一個音節的近似音詞。
    static func hasPhraseAlternativeCollision(in entries: [AICandidateRerankEntry]) -> Bool {
        let phrases = entries.filter { $0.value.count >= 2 }
        guard phrases.count >= 2 else { return false }

        for index in 0..<(phrases.count - 1) {
            for next in (index + 1)..<phrases.count {
                if phrases[index].value == phrases[next].value { continue }
                if areNearHomophonePhrases(phrases[index].reading, phrases[next].reading) {
                    return true
                }
            }
        }
        return false
    }

    /// 兩個讀音是否「只差一個音節」(音節數相同、其餘音節一致)。
    static func areNearHomophonePhrases(_ lhs: String, _ rhs: String) -> Bool {
        let lhsSyllables = readingSyllables(lhs)
        let rhsSyllables = readingSyllables(rhs)
        guard lhsSyllables.count >= 2, lhsSyllables.count == rhsSyllables.count else {
            return false
        }
        let differing = zip(lhsSyllables, rhsSyllables).reduce(0) { $0 + ($1.0 == $1.1 ? 0 : 1) }
        return differing == 1
    }

    /// 把讀音字串切成音節(以空白分隔),例:"ㄗ ㄉㄠˋ" → ["ㄗ", "ㄉㄠˋ"]。
    static func readingSyllables(_ reading: String) -> [String] {
        reading.components(separatedBy: .whitespacesAndNewlines).filter { !$0.isEmpty }
    }

    /// 去除讀音內所有空白,讓「格式化差異」不會掩蓋同音(例:"ㄗㄞ ˋ" 與 "ㄗㄞˋ")。
    static func normalizedReading(_ reading: String) -> String {
        reading.components(separatedBy: .whitespacesAndNewlines).joined()
    }

    static func containsAmbiguity(in text: String) -> Bool {
        text.contains { ambiguousCharacters.contains($0) }
    }

    static func rerank(context: AICandidateRerankContext) -> Result<String, AICorrectionError> {
        let name = AICorrectionBackendName.local
        guard let base = LlamaServerManager.shared.ensureReady(),
            let endpointURL = URL(string: base + "/v1/chat/completions")
        else {
            return .failure(.unavailable(backend: name, detail: "模型 server 未就緒"))
        }

        var req = URLRequest(url: endpointURL)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "content-type")
        req.timeoutInterval = 8

        let body: [String: Any] = [
            "messages": [
                ["role": "system", "content": AICorrectionPrompt.rerankSystemPrompt],
                ["role": "user", "content": AICorrectionPrompt.rerankPrompt(context: context)],
            ],
            "temperature": 0,
            "max_tokens": 32,
            "stream": false,
            "stop": ["\n"],
        ]
        guard let httpBody = try? JSONSerialization.data(withJSONObject: body) else {
            return .failure(.malformedResponse(backend: name))
        }
        req.httpBody = httpBody

        let sem = DispatchSemaphore(value: 0)
        var result: Result<String, AICorrectionError> = .failure(.malformedResponse(backend: name))
        URLSession.shared.dataTask(with: req) { data, response, error in
            defer { sem.signal() }
            if let error {
                NSLog("AI候選建議 本機 server 連線失敗:\(error.localizedDescription)")
                result = .failure(.unavailable(backend: name, detail: "模型 server 連線失敗"))
                return
            }
            guard let http = response as? HTTPURLResponse else {
                result = .failure(.malformedResponse(backend: name))
                return
            }
            guard http.statusCode == 200 else {
                result = .failure(.httpError(backend: name, status: http.statusCode))
                return
            }
            guard let data,
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                let choices = json["choices"] as? [[String: Any]],
                let message = choices.first?["message"] as? [String: Any],
                let text = message["content"] as? String,
                let suggestion = AICorrectionPrompt.extractRerankSuggestion(from: text)
            else {
                result = .failure(.malformedResponse(backend: name))
                return
            }
            result = .success(OpenCCBridge.shared.convertToTraditional(suggestion) ?? suggestion)
        }.resume()

        guard sem.wait(timeout: .now() + 10) == .success else {
            NSLog("AI候選建議: 本機 server 請求逾時")
            return .failure(.timeout(backend: name))
        }
        return result
    }

    static func reorderedCandidates(
        suggestion: String, candidates: [InputState.Candidate]
    ) -> [InputState.Candidate]? {
        guard let selectedIndex = candidates.firstIndex(where: {
            $0.value == suggestion || $0.displayText == suggestion
        }) else {
            return nil
        }
        guard selectedIndex > 0 else {
            return candidates
        }
        var reordered = candidates
        let selected = reordered.remove(at: selectedIndex)
        reordered.insert(selected, at: 0)
        return reordered
    }
}