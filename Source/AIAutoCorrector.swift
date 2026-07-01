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

/// L2 句末自動校正(Phase 2)的純邏輯層。
///
/// 設計取向刻意比 L1 候選重排更保守:只在使用者打到「句末標點」、組字區夠長、
/// 游標停在句尾時才考慮觸發,避免每個短句或半句都打本機 server。實際的 server
/// 呼叫與狀態套用由 `McBopomofoInputMethodController` 的 AIAutoCorrection 擴充負責;
/// 這裡只放可單元測試的觸發判斷與常數。
enum AIAutoCorrector {

    /// 防抖間隔。句末標點觸發後等這段時間,讓使用者若繼續打字可取消這次請求。
    static let debounceInterval: TimeInterval = 0.8
    static let serverRetryInterval: TimeInterval = 2.0
    static let maxServerRetryAttempts = 6

    /// 組字區最短長度。為支援邊打長句時即時檢查，適度放寬。
    static let minComposingLength = 4

    /// 句末標點集合。刻意只收「整句結束」的標點,不含逗號、頓號等句中標點,
    /// 以免在使用者還在寫同一句時就觸發。
    static let sentenceEndingPunctuation = Set("。！？!?…")

    static let ambiguousCharacters = Set("在再的得地做作知資麼摸裡裏裡哪那裡这這")

    /// 組字區最後一個字元是否為句末標點。
    static func endsWithSentencePunctuation(_ buffer: String) -> Bool {
        guard let last = buffer.last else { return false }
        return sentenceEndingPunctuation.contains(last)
    }

    static func containsAmbiguity(in text: String) -> Bool {
        text.contains { ambiguousCharacters.contains($0) }
    }

    /// 純邏輯觸發判斷:不檢查偏好設定與 server 是否就緒(那些由 controller 處理)。
    /// 為支援「邊打長句時隨時檢查現階段句子/字詞」願景，改為：
    /// - 游標在句尾
    /// - 長度達門檻
    /// - 且 (有句末標點 或 長句且含潛在歧義字)
    static func isCorrectableSentence(composingBuffer: String, cursorIndex: Int) -> Bool {
        guard cursorIndex == composingBuffer.count else { return false }
        guard composingBuffer.count >= minComposingLength else { return false }
        if endsWithSentencePunctuation(composingBuffer) {
            return true
        }
        // 支援長句中上下文修正 (e.g. 在/再 類錯誤在打長句時)
        if composingBuffer.count >= 8 && containsAmbiguity(in: composingBuffer) {
            return true
        }
        return false
    }

    /// controller 用的完整判斷:在純邏輯之上再加偏好設定與模型安裝狀態。
    static func shouldSchedule(composingBuffer: String, cursorIndex: Int) -> Bool {
        guard Preferences.enableAIAutoCorrection else { return false }
        guard LocalServerAICorrector.isModelInstalled else { return false }
        return isCorrectableSentence(composingBuffer: composingBuffer, cursorIndex: cursorIndex)
    }

    /// 本機模型是否可立即呼叫。
    static func canInvokeLocalModel() -> Bool {
        LocalServerAICorrector.isModelInstalled && LocalServerAICorrector.isReady
    }

    // MARK: - 低調隱形提示的顯示決策

    /// L2 校正結果拿到後,要不要對使用者顯示低調提示。
    ///
    /// 這是純決策:不碰 IMK / state。實際把提示掛到 `InputState.Inputting` 的
    /// `pendingAISuggestion` / `aiTooltipMessage` 欄位、以及畫面顯示,由 controller 做。
    enum SuggestionOutcome: Equatable {
        /// AI 認為現階段句子已正確,不打擾使用者。
        case noHint
        /// 有值得提示的修正建議(與原文不同)。
        case hint(String)
    }

    /// 依 L2 結果與目前組字區,決定要不要跳低調提示。
    /// 目前規則:結果與原文相同 → 不提示;不同 → 提示該建議文字。
    static func suggestionOutcome(result: String, composingBuffer: String) -> SuggestionOutcome {
        guard result != composingBuffer else { return .noHint }
        return .hint(result)
    }
}
