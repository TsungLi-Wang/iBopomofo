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
        let candidates = state.candidates
            .prefix(AICandidateReranker.maxCandidateCount)
            .map(\.value)
        let context = AICandidateRerankContext(
            preceding: Self.precedingTextForAI(from: client, maxChars: 80),
            composingBuffer: state.composingBuffer,
            candidates: Array(candidates))

        if let rerankedValue = aiCandidateRerankedValue,
            state.candidates.first?.value == rerankedValue
                || state.candidates.first?.displayText == rerankedValue
        {
            return
        }

        guard Preferences.enableAICandidateRerank,
            context.composingBuffer.count >= 2,
            AICandidateReranker.containsAmbiguity(in: context.composingBuffer)
        else {
            if aiCandidateSuggestion?.originalComposingBuffer != state.composingBuffer {
                aiCandidateSuggestion = nil
            }
            return
        }

        if LocalServerAICorrector.isModelInstalled, !LocalServerAICorrector.isReady {
            LocalServerAICorrector.startIfNeeded()
            if !aiCandidateDidNotifyLocalServerLoading {
                aiCandidateDidNotifyLocalServerLoading = true
                NotifierController.notify(
                    message: NSLocalizedString("Local AI candidate suggestions are loading", comment: ""))
            }
        }

        guard AICandidateReranker.shouldTrigger(for: context) else {
            if aiCandidateSuggestion?.originalComposingBuffer != state.composingBuffer {
                aiCandidateSuggestion = nil
            }
            return
        }

        aiCandidateDidNotifyLocalServerLoading = false
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
        aiCandidateSuggestion = nil
        aiCandidateRerankedValue = nil
        aiCandidateRequestSerial += 1
        gCurrentCandidateController?.visible = false
        keyHandler.clear()
        handle(state: InputState.Committing(poppedText: suggestion), client: client)
        handle(state: InputState.Empty(), client: client)
    }
}
