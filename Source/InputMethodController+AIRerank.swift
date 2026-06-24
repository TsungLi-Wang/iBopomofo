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

struct AICandidateSuggestion: Equatable {
    let originalComposingBuffer: String
    let suggestion: String
}

extension McBopomofoInputMethodController {

    func scheduleAICandidateRerankIfNeeded(for state: InputState.ChoosingCandidate, client: Any?) {
        let context = makeRerankContext(from: state, client: client)

        if let rerankedValue = aiCandidateRerankedValue,
            state.candidates.first?.value == rerankedValue
                || state.candidates.first?.displayText == rerankedValue
        {
            return
        }

        guard AICandidateReranker.shouldSchedule(for: context) else {
            cancelPendingAICandidateRerank()
            if aiCandidateSuggestion?.originalComposingBuffer != state.composingBuffer {
                aiCandidateSuggestion = nil
            }
            return
        }

        aiCandidateRerankWorkItem?.cancel()
        aiCandidateServerRetryWorkItem?.cancel()

        let workItem = DispatchWorkItem { [weak self] in
            self?.beginAICandidateRerank(context: context, client: client)
        }
        aiCandidateRerankWorkItem = workItem
        DispatchQueue.main.asyncAfter(
            deadline: .now() + AICandidateReranker.debounceInterval, execute: workItem)
    }

    private func makeRerankContext(
        from state: InputState.ChoosingCandidate, client: Any?
    ) -> AICandidateRerankContext {
        let entries = state.candidates
            .prefix(AICandidateReranker.maxCandidateCount)
            .map { candidate in
                AICandidateRerankEntry(value: candidate.value, reading: candidate.reading)
            }
        return AICandidateRerankContext(
            preceding: Self.precedingTextForAI(from: client, maxChars: 80),
            composingBuffer: state.composingBuffer,
            candidates: Array(entries))
    }

    private func beginAICandidateRerank(context: AICandidateRerankContext, client: Any?) {
        aiCandidateRerankWorkItem = nil

        guard let choosing = state as? InputState.ChoosingCandidate,
            choosing.composingBuffer == context.composingBuffer
        else {
            return
        }

        guard AICandidateReranker.shouldSchedule(for: context) else {
            return
        }

        if !AICandidateReranker.canInvokeLocalModel() {
            LocalServerAICorrector.startIfNeeded()
            if !aiCandidateDidNotifyLocalServerLoading {
                aiCandidateDidNotifyLocalServerLoading = true
                NotifierController.notify(
                    message: NSLocalizedString("Local AI candidate suggestions are loading", comment: ""))
            }
            scheduleAICandidateServerRetry(context: context, client: client, attempt: 1)
            return
        }

        aiCandidateDidNotifyLocalServerLoading = false
        aiCandidateServerRetryWorkItem?.cancel()
        invokeAICandidateRerank(context: context, client: client)
    }

    private func scheduleAICandidateServerRetry(
        context: AICandidateRerankContext, client: Any?, attempt: Int
    ) {
        guard attempt <= AICandidateReranker.maxServerRetryAttempts else {
            return
        }

        aiCandidateServerRetryWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.aiCandidateServerRetryWorkItem = nil
            guard let choosing = self.state as? InputState.ChoosingCandidate,
                choosing.composingBuffer == context.composingBuffer
            else {
                return
            }
            if AICandidateReranker.canInvokeLocalModel() {
                self.aiCandidateDidNotifyLocalServerLoading = false
                self.invokeAICandidateRerank(context: context, client: client)
            } else {
                self.scheduleAICandidateServerRetry(
                    context: context, client: client, attempt: attempt + 1)
            }
        }
        aiCandidateServerRetryWorkItem = workItem
        DispatchQueue.main.asyncAfter(
            deadline: .now() + AICandidateReranker.serverRetryInterval, execute: workItem)
    }

    private func invokeAICandidateRerank(context: AICandidateRerankContext, client: Any?) {
        aiCandidateRequestSerial += 1
        let serial = aiCandidateRequestSerial
        DispatchQueue.global(qos: .userInitiated).async {
            let outcome = AICandidateReranker.rerank(context: context)
            DispatchQueue.main.async {
                self.applyAICandidateRerankResult(
                    outcome, context: context, serial: serial, client: client)
            }
        }
    }

    func resetAICandidateAssistState() {
        aiCandidateRerankWorkItem?.cancel()
        aiCandidateRerankWorkItem = nil
        aiCandidateServerRetryWorkItem?.cancel()
        aiCandidateServerRetryWorkItem = nil
        aiCandidateSuggestion = nil
        aiCandidateRerankedValue = nil
        aiCandidateDidNotifyLocalServerLoading = false
    }

    private func cancelPendingAICandidateRerank() {
        aiCandidateRerankWorkItem?.cancel()
        aiCandidateRerankWorkItem = nil
        aiCandidateServerRetryWorkItem?.cancel()
        aiCandidateServerRetryWorkItem = nil
    }

    func acceptAICandidateSuggestionIfAvailable(client: Any!) -> Bool {
        guard let suggestion = aiCandidateSuggestion,
            let currentInputting = state as? InputState.Inputting,
            currentInputting.composingBuffer == suggestion.originalComposingBuffer
        else {
            return false
        }
        commitAISuggestion(suggestion.suggestion, client: client)
        return true
    }

    func acceptAICandidateSuggestionFromCandidateWindowIfAvailable(client: Any!) -> Bool {
        guard let suggestion = aiCandidateSuggestion,
            let choosing = state as? InputState.ChoosingCandidate,
            choosing.composingBuffer == suggestion.originalComposingBuffer
        else {
            return false
        }
        commitAISuggestion(suggestion.suggestion, client: client)
        return true
    }

    private func applyAICandidateRerankResult(
        _ outcome: Result<String, AICorrectionError>, context: AICandidateRerankContext,
        serial: UInt, client: Any?
    ) {
        guard serial == aiCandidateRequestSerial else {
            NSLog("AI候選建議: 丟棄過期結果")
            return
        }
        guard let choosing = state as? InputState.ChoosingCandidate,
            choosing.composingBuffer == context.composingBuffer
        else {
            NSLog("AI候選建議: composing 狀態已變更,丟棄結果")
            return
        }

        guard case let .success(text) = outcome else {
            return
        }
        guard text != context.composingBuffer else {
            aiCandidateSuggestion = nil
            aiCandidateRerankedValue = nil
            gCurrentCandidateController?.tooltip = ""
            return
        }

        if let rerankedCandidates = AICandidateReranker.reorderedCandidates(
            suggestion: text, candidates: choosing.candidates)
        {
            aiCandidateSuggestion = nil
            aiCandidateRerankedValue = text
            let rerankedState = InputState.ChoosingCandidate(
                composingBuffer: choosing.composingBuffer,
                cursorIndex: choosing.cursorIndex,
                candidates: rerankedCandidates,
                useVerticalMode: choosing.useVerticalMode)
            rerankedState.originalCursorIndex = choosing.originalCursorIndex
            handle(state: rerankedState, client: client)
            return
        }

        aiCandidateRerankedValue = nil
        aiCandidateSuggestion = AICandidateSuggestion(
            originalComposingBuffer: context.composingBuffer, suggestion: text)
        gCurrentCandidateController?.tooltip = String(
            format: NSLocalizedString("AI Suggestion: %@ (Tab)", comment: ""), text)
    }

    private func commitAISuggestion(_ suggestion: String, client: Any!) {
        cancelPendingAICandidateRerank()
        aiCandidateSuggestion = nil
        aiCandidateRerankedValue = nil
        aiCandidateRequestSerial += 1
        gCurrentCandidateController?.visible = false
        keyHandler.clear()
        handle(state: InputState.Committing(poppedText: suggestion), client: client)
        handle(state: InputState.Empty(), client: client)
    }
}