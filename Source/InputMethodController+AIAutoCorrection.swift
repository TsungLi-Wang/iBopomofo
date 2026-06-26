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

import Cocoa
import InputMethodKit
import NotifierUI

// Phase 2:句末自動 L2 整句校正。
//
// L2 自動校正擴充。
// 目前行為(非破壞性):對長句或含潛在錯誤的現階段輸入,用上下文在背景取得修正建議,
// 只跳低調提示,使用者按 Tab 才真正套用;繼續打字則忽略。手動 ⌘Return 仍維持直接套用
// (見 +AICorrection)。「邊打邊隱形修正」的願景需走引擎節點覆寫,待 Coordinator 穩定後設計;
// 早期版本曾用 setMarkedText 直接塞文字,但那與讀音驅動的引擎脫鉤、會被後續按鍵蓋掉,已移除。
extension McBopomofoInputMethodController {

    func scheduleAIAutoCorrectionIfNeeded(for state: InputState.Inputting, client: Any?) {
        let buffer = state.composingBuffer
        let preceding = Self.precedingTextForAI(from: client, maxChars: 100)
        aiAssistCoordinator.scheduleAutoCorrection(composingBuffer: buffer, preceding: preceding, cursorIndex: Int(state.cursorIndex), client: client)
    }

    // begin/invoke/scheduleRetry 已搬到 AIAssistCoordinator (使用協議驅動)。
    // 舊路徑已不再使用，保留註解以利過渡期間檢視。

    func applyAIAutoCorrectionResult(
        _ outcome: Result<String, AICorrectionError>, composingBuffer: String,
        serial: UInt, client: Any?
    ) {
        let coordinator = aiAssistCoordinator
        guard serial == coordinator.aiAutoCorrectionRequestSerial else {
            NSLog("AI自動校正: 丟棄過期結果")
            return
        }
        guard let inputting = state as? InputState.Inputting,
            inputting.composingBuffer == composingBuffer
        else {
            NSLog("AI自動校正: composing 狀態已變更,丟棄結果")
            return
        }

        guard case let .success(text) = outcome else {
            return
        }

        // AI 認為整句已正確:不打擾使用者,清掉任何殘留建議。
        guard text != composingBuffer else {
            coordinator.aiAutoCorrectionSuggestion = nil
            return
        }

        // 非破壞性:只儲存建議 + 顯示低調提示,使用者按 Tab 才真正套用。
        //
        // 刻意不在這裡直接改 composingBuffer。注音引擎是讀音驅動的,從 Swift 端
        // 用 setMarkedText 塞自由文字並不會更新 keyHandler 的引擎狀態,會在下一個
        // 按鍵或送出時被引擎以原文蓋掉(假修正),也違反「只在引擎狀態裡操作」原則。
        // 真正的隱形修正應走「在引擎讀音格子上覆寫節點」的路徑,待 Coordinator
        // 穩定後再設計(見 ~/Documents 的隱形警察交班與設計報告)。
        coordinator.aiAutoCorrectionSuggestion = AICandidateSuggestion(
            originalComposingBuffer: composingBuffer, suggestion: text)
        showAIAutoCorrectionTooltip(text, for: inputting, client: client)
    }

    private func showAIAutoCorrectionTooltip(
        _ suggestion: String, for state: InputState.Inputting, client: Any?
    ) {
        let tip = String(
            format: NSLocalizedString("AI Suggestion: %@ (Tab)", comment: ""), suggestion)
        show(
            tooltip: tip, composingBuffer: state.composingBuffer,
            cursorIndex: state.cursorIndex, client: client)
    }

    /// Tab 採用句末自動校正建議。僅當目前仍在同一句 Inputting 狀態時生效。
    func acceptAIAutoCorrectionSuggestionIfAvailable(client: Any!) -> Bool {
        let coordinator = aiAssistCoordinator
        guard let suggestion = coordinator.aiAutoCorrectionSuggestion,
            let inputting = state as? InputState.Inputting,
            inputting.composingBuffer == suggestion.originalComposingBuffer
        else {
            return false
        }
        commitAIAutoCorrection(suggestion.suggestion, client: client)
        return true
    }

    private func commitAIAutoCorrection(_ suggestion: String, client: Any!) {
        let coordinator = aiAssistCoordinator
        coordinator.cancelPendingAutoCorrection()
        coordinator.aiAutoCorrectionSuggestion = nil
        coordinator.aiAutoCorrectionRequestSerial += 1
        keyHandler.clear()
        handle(state: InputState.Committing(poppedText: suggestion), client: client)
        handle(state: InputState.Empty(), client: client)
    }

    func resetAIAutoCorrectionState() {
        aiAssistCoordinator.reset()
    }

    private func cancelPendingAIAutoCorrection() {
        aiAssistCoordinator.cancelPendingAutoCorrection()
    }

    // 舊的個別 reset 已委派給 Coordinator，保留相容介面。
}
