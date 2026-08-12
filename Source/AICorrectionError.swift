// Copyright (c) 2022 and onwards The McBopomofo Authors.
//
// Shared local-service error type (voice / offline helpers). Cloud Claude
// backend and ⌘Return AI correction were removed in v2.7.0; this type is kept
// only for whisper local HTTP errors.

import Foundation

enum AICorrectionBackendName {
    static let whisper = "語音辨識"
}

/// ⚠️ 名稱是歷史遺留，**不要被它誤導**。
///
/// 「AI 校正」那條路（雲端 Claude 送整句回來改字）在 v2.7 已經整個移除，
/// 現在**不存在任何雲端校正**。這個 enum 目前唯一的用途是
/// `WhisperVoiceTranscriber` / `WhisperVoiceInputManager` 的**本機語音轉寫**錯誤。
///
/// 沒有改名是因為改了要動語音那條路的一串簽章，而它跟解碼行為無關；
/// 真要改請排在品牌統一那一棒一起做，不要單獨動。
enum AICorrectionError: Error {
    case timeout(backend: String)
    case network(backend: String)
    case httpError(backend: String, status: Int)
    case malformedResponse(backend: String)
    case unavailable(backend: String, detail: String)
    case emptyResult(backend: String)

    var userMessage: String {
        switch self {
        case let .timeout(backend):
            return "\(backend):請求逾時,請稍後再試"
        case let .network(backend):
            return "\(backend):連線失敗(本機服務),請稍後再試"
        case let .httpError(backend, status):
            return "\(backend):伺服器回應錯誤(HTTP \(status)),請稍後再試"
        case let .malformedResponse(backend):
            return "\(backend):回應格式無法解析,請稍後再試"
        case let .unavailable(backend, detail):
            return "\(backend):\(detail)"
        case let .emptyResult(backend):
            return "\(backend):未取得結果,請稍後再試"
        }
    }
}
