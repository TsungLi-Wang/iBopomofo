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

    static func correct(guess: String, preceding: String, model: String) -> String? {
        guard let key = AICorrectionConfig.claudeAPIKey else {
            NSLog("AI校正: 找不到 Claude API key(請從輸入法選單『AI 修正設定…』填入)")
            return nil
        }
        guard let endpointURL = URL(string: AICorrectionConfig.claudeEndpoint) else {
            NSLog("AI校正: Claude 端點設定無效:\(AICorrectionConfig.claudeEndpoint)")
            return nil
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
        guard let httpBody = try? JSONSerialization.data(withJSONObject: body) else { return nil }
        req.httpBody = httpBody

        let sem = DispatchSemaphore(value: 0)
        var result: String?
        URLSession.shared.dataTask(with: req) { data, response, _ in
            defer { sem.signal() }
            guard let data,
                let http = response as? HTTPURLResponse, http.statusCode == 200,
                let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                let content = json["content"] as? [[String: Any]],
                let text = content.first(where: { ($0["type"] as? String) == "text" })?["text"]
                    as? String
            else {
                if let data {
                    NSLog("AI校正 Claude 回應異常:\(String(data: data, encoding: .utf8) ?? "")")
                }
                return
            }
            result = AICorrectionPrompt.extractTaggedResult(from: text)
        }.resume()

        guard sem.wait(timeout: .now() + 35) == .success else {
            NSLog("AI校正: Claude 請求逾時")
            return nil
        }
        return result
    }
}
