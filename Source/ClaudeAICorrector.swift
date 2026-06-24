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

enum ClaudeAICorrector {

    static func correct(guess: String, preceding: String, model: String)
        -> Result<String, AICorrectionError>
    {
        let name = AICorrectionBackendName.claude
        guard let key = AICorrectionConfig.claudeAPIKey else {
            return .failure(.missingAPIKey(backend: name))
        }
        guard let endpointURL = URL(string: AICorrectionConfig.claudeEndpoint) else {
            return .failure(.invalidEndpoint(backend: name, endpoint: AICorrectionConfig.claudeEndpoint))
        }

        var req = URLRequest(url: endpointURL)
        req.httpMethod = "POST"
        req.setValue(key, forHTTPHeaderField: "x-api-key")
        req.setValue("2023-06-01", forHTTPHeaderField: "anthropic-version")
        req.setValue("application/json", forHTTPHeaderField: "content-type")
        req.timeoutInterval = 30

        let body: [String: Any] = [
            "model": model,
            "max_tokens": 256,
            "messages": [
                ["role": "user", "content": AICorrectionPrompt.taggedPrompt(guess: guess, preceding: preceding)]
            ],
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
                NSLog("AI校正 Claude 連線失敗:\(error.localizedDescription)")
                result = .failure(.network(backend: name))
                return
            }
            guard let http = response as? HTTPURLResponse else {
                result = .failure(.malformedResponse(backend: name))
                return
            }
            guard http.statusCode == 200 else {
                if let data {
                    NSLog("AI校正 Claude HTTP \(http.statusCode):\(String(data: data, encoding: .utf8) ?? "")")
                }
                switch http.statusCode {
                case 401, 403: result = .failure(.unauthorized(backend: name))
                case 429: result = .failure(.rateLimited(backend: name))
                default: result = .failure(.httpError(backend: name, status: http.statusCode))
                }
                return
            }
            guard let data,
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                let content = json["content"] as? [[String: Any]],
                let text = content.first(where: { ($0["type"] as? String) == "text" })?["text"]
                    as? String
            else {
                if let data {
                    NSLog("AI校正 Claude 回應異常:\(String(data: data, encoding: .utf8) ?? "")")
                }
                result = .failure(.malformedResponse(backend: name))
                return
            }
            if let extracted = AICorrectionPrompt.extractTaggedResult(from: text), !extracted.isEmpty {
                result = .success(extracted)
            } else {
                result = .failure(.emptyResult(backend: name))
            }
        }.resume()

        guard sem.wait(timeout: .now() + 35) == .success else {
            NSLog("AI校正: Claude 請求逾時")
            return .failure(.timeout(backend: name))
        }
        return result
    }
}
