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

/// 選項 3:OpenAI 雲端語音轉文字(可選後端)。把錄好的整段 WAV 上傳到 OpenAI 的
/// transcription API(`/v1/audio/transcriptions`),回傳辨識文字。
///
/// 需要使用者自行在「AI 修正設定…」填入 OpenAI Platform API key(存 Keychain);
/// 這是按量付費的雲端服務,與 ChatGPT / Codex 訂閱不同。輸出統一過 OpenCC 轉繁,
/// 因為 Whisper 對中文有時會吐簡體(與本機後端共用同一個安全網)。
enum WhisperVoiceTranscriber {

    static let endpoint = "https://api.openai.com/v1/audio/transcriptions"

    /// 上傳 WAV 音訊,回辨識文字(已轉繁)。同步阻塞,由背景佇列呼叫。
    static func transcribe(wavData: Data, fileName: String) -> Result<String, AICorrectionError> {
        let name = AICorrectionBackendName.openAIVoice
        guard let key = AICorrectionConfig.openAIAPIKey else {
            return .failure(.missingAPIKey(backend: name))
        }
        guard let url = URL(string: endpoint) else {
            return .failure(.invalidEndpoint(backend: name, endpoint: endpoint))
        }

        let boundary = "Boundary-\(UUID().uuidString)"
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        req.setValue(
            "multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 60

        var body = Data()
        func appendField(_ fieldName: String, _ value: String) {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append(
                "Content-Disposition: form-data; name=\"\(fieldName)\"\r\n\r\n".data(using: .utf8)!)
            body.append("\(value)\r\n".data(using: .utf8)!)
        }
        appendField("model", AICorrectionConfig.openAITranscribeModel)
        appendField("language", "zh")
        appendField("response_format", "json")
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append(
            "Content-Disposition: form-data; name=\"file\"; filename=\"\(fileName)\"\r\n"
                .data(using: .utf8)!)
        body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
        body.append(wavData)
        body.append("\r\n".data(using: .utf8)!)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body

        let sem = DispatchSemaphore(value: 0)
        var result: Result<String, AICorrectionError> = .failure(.malformedResponse(backend: name))
        URLSession.shared.dataTask(with: req) { data, response, error in
            defer { sem.signal() }
            if let error {
                NSLog("語音辨識 OpenAI 連線失敗:\(error.localizedDescription)")
                result = .failure(.network(backend: name))
                return
            }
            guard let http = response as? HTTPURLResponse else {
                result = .failure(.malformedResponse(backend: name))
                return
            }
            guard http.statusCode == 200 else {
                if let data {
                    NSLog(
                        "語音辨識 OpenAI HTTP \(http.statusCode):\(String(data: data, encoding: .utf8) ?? "")"
                    )
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
                let text = json["text"] as? String
            else {
                if let data {
                    NSLog("語音辨識 OpenAI 回應異常:\(String(data: data, encoding: .utf8) ?? "")")
                }
                result = .failure(.malformedResponse(backend: name))
                return
            }
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else {
                result = .failure(.emptyResult(backend: name))
                return
            }
            result = .success(OpenCCBridge.shared.convertToTraditional(trimmed) ?? trimmed)
        }.resume()

        guard sem.wait(timeout: .now() + 65) == .success else {
            NSLog("語音辨識: OpenAI 請求逾時")
            return .failure(.timeout(backend: name))
        }
        return result
    }
}
