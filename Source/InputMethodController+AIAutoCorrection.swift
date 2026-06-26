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
// 目前主要行為：對長句或含潛在錯誤的現階段輸入，使用上下文自動修正，並在 Inputting 時直接無聲套用（隱形警察模式）。
// 保留 tooltip + Tab 作為 fallback 給其他狀態。手動 ⌘Return 仍維持直接套用（見 +AICorrection）。
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

        // 為支援「邊打長句時隱形修正現階段句子/字詞」的願景：
        // 如果目前在 Inputting，直接無聲更新 composingBuffer 為修正後文字。
        // 使用者會看到文字自己被修正，繼續打注音即可。平滑體驗為主。
        if let inputting = state as? InputState.Inputting {
            let correctedState = InputState.Inputting(composingBuffer: text, cursorIndex: UInt(text.count))
            coordinator.aiAutoCorrectionSuggestion = nil
            correctedState.pendingAISuggestion = AICandidateSuggestion(originalComposingBuffer: composingBuffer, suggestion: text)
            correctedState.aiTooltipMessage = "AI 已自動修正"
            state = correctedState
            guard let imkClient = client as? IMKTextInput else { return }
            imkClient.setMarkedText(
                correctedState.attributedString,
                selectionRange: NSMakeRange(Int(correctedState.cursorIndex), 0),
                replacementRange: NSMakeRange(NSNotFound, NSNotFound))
            // 純隱形：無聲替換，pending 和 aiTooltipMessage 保留供未來低調 UI 或記錄使用
            return
        }

        // 其他情況（或舊行為）仍用提示 + Tab 採用。
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
