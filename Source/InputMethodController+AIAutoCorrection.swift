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
// 與手動 ⌘Return 的關鍵差異:這裡「只提示、不直接 commit」。偵測到句末標點後,
// 在背景以本機模型校正整句,結果不同時只顯示 tooltip 並存成 pending suggestion,
// 由使用者按 Tab 採用。手動 ⌘Return 仍維持直接套用的行為(見 +AICorrection)。
extension McBopomofoInputMethodController {

    func scheduleAIAutoCorrectionIfNeeded(for state: InputState.Inputting, client: Any?) {
        let buffer = state.composingBuffer

        // 已對同一句組字區給過建議,不重打 server。
        if let suggestion = aiAutoCorrectionSuggestion,
            suggestion.originalComposingBuffer == buffer
        {
            return
        }

        guard
            AIAutoCorrector.shouldSchedule(
                composingBuffer: buffer, cursorIndex: Int(state.cursorIndex))
        else {
            cancelPendingAIAutoCorrection()
            if aiAutoCorrectionSuggestion?.originalComposingBuffer != buffer {
                aiAutoCorrectionSuggestion = nil
            }
            return
        }

        aiAutoCorrectionWorkItem?.cancel()
        aiAutoCorrectionServerRetryWorkItem?.cancel()

        let preceding = Self.precedingTextForAI(from: client, maxChars: 100)
        let workItem = DispatchWorkItem { [weak self] in
            self?.beginAIAutoCorrection(composingBuffer: buffer, preceding: preceding, client: client)
        }
        aiAutoCorrectionWorkItem = workItem
        DispatchQueue.main.asyncAfter(
            deadline: .now() + AIAutoCorrector.debounceInterval, execute: workItem)
    }

    private func beginAIAutoCorrection(composingBuffer: String, preceding: String, client: Any?) {
        aiAutoCorrectionWorkItem = nil

        guard let inputting = state as? InputState.Inputting,
            inputting.composingBuffer == composingBuffer
        else {
            return
        }
        guard
            AIAutoCorrector.shouldSchedule(
                composingBuffer: composingBuffer, cursorIndex: Int(inputting.cursorIndex))
        else {
            return
        }

        if !AIAutoCorrector.canInvokeLocalModel() {
            LocalServerAICorrector.startIfNeeded()
            if !aiAutoCorrectionDidNotifyLocalServerLoading {
                aiAutoCorrectionDidNotifyLocalServerLoading = true
                NotifierController.notify(
                    message: NSLocalizedString("Local AI auto-correction is loading", comment: ""))
            }
            scheduleAIAutoCorrectionServerRetry(
                composingBuffer: composingBuffer, preceding: preceding, client: client, attempt: 1)
            return
        }

        aiAutoCorrectionDidNotifyLocalServerLoading = false
        aiAutoCorrectionServerRetryWorkItem?.cancel()
        invokeAIAutoCorrection(composingBuffer: composingBuffer, preceding: preceding, client: client)
    }

    private func scheduleAIAutoCorrectionServerRetry(
        composingBuffer: String, preceding: String, client: Any?, attempt: Int
    ) {
        guard attempt <= AIAutoCorrector.maxServerRetryAttempts else {
            return
        }

        aiAutoCorrectionServerRetryWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.aiAutoCorrectionServerRetryWorkItem = nil
            guard let inputting = self.state as? InputState.Inputting,
                inputting.composingBuffer == composingBuffer
            else {
                return
            }
            if AIAutoCorrector.canInvokeLocalModel() {
                self.aiAutoCorrectionDidNotifyLocalServerLoading = false
                self.invokeAIAutoCorrection(
                    composingBuffer: composingBuffer, preceding: preceding, client: client)
            } else {
                self.scheduleAIAutoCorrectionServerRetry(
                    composingBuffer: composingBuffer, preceding: preceding, client: client,
                    attempt: attempt + 1)
            }
        }
        aiAutoCorrectionServerRetryWorkItem = workItem
        DispatchQueue.main.asyncAfter(
            deadline: .now() + AIAutoCorrector.serverRetryInterval, execute: workItem)
    }

    private func invokeAIAutoCorrection(composingBuffer: String, preceding: String, client: Any?) {
        aiAutoCorrectionRequestSerial += 1
        let serial = aiAutoCorrectionRequestSerial
        DispatchQueue.global(qos: .userInitiated).async {
            let outcome = LocalServerAICorrector.correct(
                guess: composingBuffer, preceding: preceding)
            DispatchQueue.main.async {
                self.applyAIAutoCorrectionResult(
                    outcome, composingBuffer: composingBuffer, serial: serial, client: client)
            }
        }
    }

    private func applyAIAutoCorrectionResult(
        _ outcome: Result<String, AICorrectionError>, composingBuffer: String,
        serial: UInt, client: Any?
    ) {
        guard serial == aiAutoCorrectionRequestSerial else {
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
            aiAutoCorrectionSuggestion = nil
            return
        }

        // 第一版只提示、不 commit。存成 pending suggestion,等使用者按 Tab 採用。
        aiAutoCorrectionSuggestion = AICandidateSuggestion(
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
        guard let suggestion = aiAutoCorrectionSuggestion,
            let inputting = state as? InputState.Inputting,
            inputting.composingBuffer == suggestion.originalComposingBuffer
        else {
            return false
        }
        commitAIAutoCorrection(suggestion.suggestion, client: client)
        return true
    }

    private func commitAIAutoCorrection(_ suggestion: String, client: Any!) {
        cancelPendingAIAutoCorrection()
        aiAutoCorrectionSuggestion = nil
        aiAutoCorrectionRequestSerial += 1
        keyHandler.clear()
        handle(state: InputState.Committing(poppedText: suggestion), client: client)
        handle(state: InputState.Empty(), client: client)
    }

    func resetAIAutoCorrectionState() {
        aiAutoCorrectionWorkItem?.cancel()
        aiAutoCorrectionWorkItem = nil
        aiAutoCorrectionServerRetryWorkItem?.cancel()
        aiAutoCorrectionServerRetryWorkItem = nil
        aiAutoCorrectionSuggestion = nil
        aiAutoCorrectionDidNotifyLocalServerLoading = false
    }

    private func cancelPendingAIAutoCorrection() {
        aiAutoCorrectionWorkItem?.cancel()
        aiAutoCorrectionWorkItem = nil
        aiAutoCorrectionServerRetryWorkItem?.cancel()
        aiAutoCorrectionServerRetryWorkItem = nil
    }
}
