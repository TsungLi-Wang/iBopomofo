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

struct AICandidateRerankContext: Equatable {
    let preceding: String
    let composingBuffer: String
    let candidates: [String]
}

enum AICandidateReranker {

    static let maxCandidateCount = 8

    static func shouldTrigger(for context: AICandidateRerankContext) -> Bool {
        guard Preferences.enableAICandidateRerank else { return false }
        guard context.composingBuffer.count >= 2 else { return false }
        guard LocalServerAICorrector.isModelInstalled, LocalServerAICorrector.isReady else {
            return false
        }
        return containsAmbiguity(in: context.composingBuffer)
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

    static func containsAmbiguity(in text: String) -> Bool {
        let ambiguousCharacters = Set("在再的得地做作知資麼摸")
        return text.contains { ambiguousCharacters.contains($0) }
    }
}
