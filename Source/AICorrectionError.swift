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

/// AI 修正後端的顯示名稱,集中管理避免散落各檔。
enum AICorrectionBackendName {
    static let claude = "Claude"
    static let codex = "Codex"
    static let local = "本機 AI"
    static let openAIVoice = "OpenAI 語音"
}

/// AI 修正後端失敗的結構化原因。
///
/// 每個 case 都帶得出一句可直接顯示給使用者的中文訊息(`userMessage`),
/// 讓使用者看到「哪個後端、什麼原因、怎麼辦」,而不是只有一句泛用的「修正失敗」。
/// 後端內部仍可用 `NSLog` 記詳細技術內容供開發者除錯;`userMessage` 只給使用者看摘要。
enum AICorrectionError: Error {
    /// 缺少 API key(雲端後端)。
    case missingAPIKey(backend: String)
    /// 端點 URL 設定無效。
    case invalidEndpoint(backend: String, endpoint: String)
    /// 請求逾時。
    case timeout(backend: String)
    /// 連線失敗(無網路、端點無法連上)。
    case network(backend: String)
    /// 認證失敗(HTTP 401/403):key 錯誤或無權限。
    case unauthorized(backend: String)
    /// 被限流或額度用罄(HTTP 429)。
    case rateLimited(backend: String)
    /// 後端伺服器回傳其他 HTTP 錯誤。
    case httpError(backend: String, status: Int)
    /// 回應格式無法解析。
    case malformedResponse(backend: String)
    /// 後端尚未就緒或不可用(本機 server 未啟動、codex 未登入等)。
    case unavailable(backend: String, detail: String)
    /// 無法啟動外部程序(codex 執行檔不存在等)。
    case launchFailed(backend: String, detail: String)
    /// 後端有回應但取不到可用的修正結果。
    case emptyResult(backend: String)

    /// 直接顯示給使用者的一句話。
    var userMessage: String {
        switch self {
        case let .missingAPIKey(backend):
            return "\(backend):尚未設定 API key,請從輸入法選單「AI 修正設定…」填入"
        case let .invalidEndpoint(backend, endpoint):
            return "\(backend):端點設定無效(\(endpoint)),請檢查「AI 修正設定…」"
        case let .timeout(backend):
            return "\(backend):請求逾時,請稍後再試或改用其他後端"
        case let .network(backend):
            return "\(backend):連線失敗,請檢查網路或端點設定"
        case let .unauthorized(backend):
            return "\(backend):API key 無效或無權限(401),請重新確認金鑰"
        case let .rateLimited(backend):
            return "\(backend):額度用罄或被限流(429),請稍後再試或改用本機 AI"
        case let .httpError(backend, status):
            return "\(backend):伺服器回應錯誤(HTTP \(status)),請稍後再試"
        case let .malformedResponse(backend):
            return "\(backend):回應格式無法解析,請稍後再試"
        case let .unavailable(backend, detail):
            return "\(backend):\(detail)"
        case let .launchFailed(backend, detail):
            return "\(backend):無法啟動(\(detail)),請確認「AI 修正設定…」的執行檔路徑"
        case let .emptyResult(backend):
            return "\(backend):未取得修正結果,請稍後再試"
        }
    }
}
