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

enum LocalServerAICorrector {

    static var isModelInstalled: Bool { LlamaServerManager.shared.isModelInstalled }
    static var isReady: Bool { LlamaServerManager.shared.isReady }

    static func ensureModelDownloaded() {
        LlamaServerManager.shared.ensureModelDownloaded()
    }

    static func startIfNeeded() {
        LlamaServerManager.shared.startIfNeeded()
    }

    static func correct(guess: String, preceding: String) -> Result<String, AICorrectionError> {
        let name = AICorrectionBackendName.local
        guard let base = LlamaServerManager.shared.ensureReady(),
            let endpointURL = URL(string: base + "/v1/chat/completions")
        else {
            NSLog("AI校正: 本機 AI server 未就緒")
            return .failure(
                .unavailable(backend: name, detail: "模型 server 未就緒,請稍候幾秒再按一次 ⌘Enter"))
        }

        let userContent = (preceding.isEmpty ? "" : "前文:\(preceding)\n") + "待修正:\(guess)"
        var req = URLRequest(url: endpointURL)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "content-type")
        req.timeoutInterval = 30

        let body: [String: Any] = [
            "messages": [
                ["role": "system", "content": AICorrectionPrompt.localSystemPrompt],
                ["role": "user", "content": userContent],
            ],
            "temperature": 0,
            "max_tokens": 64,
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
                NSLog("AI校正 本機 server 連線失敗:\(error.localizedDescription)")
                result = .failure(.unavailable(backend: name, detail: "模型 server 連線失敗,請稍候再試"))
                return
            }
            guard let http = response as? HTTPURLResponse else {
                result = .failure(.malformedResponse(backend: name))
                return
            }
            guard http.statusCode == 200 else {
                if let data {
                    NSLog("AI校正 本機 server HTTP \(http.statusCode):\(String(data: data, encoding: .utf8) ?? "")")
                }
                result = .failure(.httpError(backend: name, status: http.statusCode))
                return
            }
            guard let data,
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                let choices = json["choices"] as? [[String: Any]],
                let message = choices.first?["message"] as? [String: Any],
                let text = message["content"] as? String
            else {
                if let data {
                    NSLog("AI校正 本機 server 回應異常:\(String(data: data, encoding: .utf8) ?? "")")
                }
                result = .failure(.malformedResponse(backend: name))
                return
            }
            guard let cleaned = AICorrectionPrompt.cleanLocalResult(text) else {
                result = .failure(.emptyResult(backend: name))
                return
            }
            result = .success(OpenCCBridge.shared.convertToTraditional(cleaned) ?? cleaned)
        }.resume()

        guard sem.wait(timeout: .now() + 35) == .success else {
            NSLog("AI校正: 本機 server 請求逾時")
            return .failure(.timeout(backend: name))
        }
        return result
    }
}
