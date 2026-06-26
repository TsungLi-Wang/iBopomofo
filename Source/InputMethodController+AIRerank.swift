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
        aiAssistCoordinator.scheduleRerank(context: context, client: client)
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
            cursorIndex: Int(state.cursorIndex),
            candidates: Array(entries))
    }

    // begin/invoke moved to AIAssistCoordinator (design report refactor)
    // kept for reference during transition; currently unused.

    func resetAICandidateAssistState() {
        aiAssistCoordinator.reset()
    }

    func acceptAICandidateSuggestionIfAvailable(client: Any!) -> Bool {
        guard let currentInputting = state as? InputState.Inputting,
            let text = aiAssistCoordinator.candidateSuggestion(
                matching: currentInputting.composingBuffer)
        else {
            return false
        }
        commitAISuggestion(text, client: client)
        return true
    }

    func acceptAICandidateSuggestionFromCandidateWindowIfAvailable(client: Any!) -> Bool {
        guard let choosing = state as? InputState.ChoosingCandidate,
            let text = aiAssistCoordinator.candidateSuggestion(matching: choosing.composingBuffer)
        else {
            return false
        }
        commitAISuggestion(text, client: client)
        return true
    }

    func applyAICandidateRerankResult(
        _ outcome: Result<String, AICorrectionError>, context: AICandidateRerankContext,
        client: Any?
    ) {
        // serial 過期判斷已由 Coordinator 完成；這裡只需確認 composing 狀態仍相同。
        let coordinator = aiAssistCoordinator
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
            coordinator.aiCandidateSuggestion = nil
            coordinator.aiCandidateRerankedValue = nil
            gCurrentCandidateController?.tooltip = ""
            return
        }

        if choosing.candidates.first?.value == text || choosing.candidates.first?.displayText == text {
            coordinator.aiCandidateSuggestion = nil
            coordinator.aiCandidateRerankedValue = text
            gCurrentCandidateController?.tooltip = ""
            // update state fields for invisible support
            if let choosingState = state as? InputState.ChoosingCandidate {
                choosingState.aiRerankedTopCandidate = text
            }
            return
        }

        if let rerankedCandidates = AICandidateReranker.reorderedCandidates(
            suggestion: text, candidates: choosing.candidates)
        {
            coordinator.aiCandidateSuggestion = nil
            coordinator.aiCandidateRerankedValue = text
            let rerankedState = InputState.ChoosingCandidate(
                composingBuffer: choosing.composingBuffer,
                cursorIndex: choosing.cursorIndex,
                candidates: rerankedCandidates,
                useVerticalMode: choosing.useVerticalMode)
            rerankedState.originalCursorIndex = choosing.originalCursorIndex
            rerankedState.aiRerankedTopCandidate = text
            handle(state: rerankedState, client: client)
            return
        }

        coordinator.aiCandidateRerankedValue = nil
        coordinator.aiCandidateSuggestion = AICandidateSuggestion(
            originalComposingBuffer: context.composingBuffer, suggestion: text)
        gCurrentCandidateController?.tooltip = String(
            format: NSLocalizedString("AI Suggestion: %@ (Tab)", comment: ""), text)
    }

    private func commitAISuggestion(_ suggestion: String, client: Any!) {
        aiAssistCoordinator.consumeCandidateSuggestion()
        gCurrentCandidateController?.visible = false
        keyHandler.clear()
        handle(state: InputState.Committing(poppedText: suggestion), client: client)
        handle(state: InputState.Empty(), client: client)
    }
}
