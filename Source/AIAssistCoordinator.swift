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
import InputMethodKit

/// 依設計報告階段一：把散落在 InputMethodController 的 L1/L2 排程、debounce、serial、suggestion 狀態
/// 集中到 Coordinator 擁有。Controller 只負責「轉呼叫」與「把結果套到 state」。
///
/// 目前為骨架 + 協議注入，後續會逐步把原本 +AIRerank / +AIAutoCorrection 的邏輯搬進來。
/// 預期效益：重複代碼消除、單元測試變容易、Controller 瘦身。

protocol AIAssistControllerDelegate: AnyObject {
    // serial 過期判斷已由 Coordinator 在呼叫前完成，delegate 收到的必為最新請求結果，
    // 只需再比對目前 composing 狀態是否仍相同即可（那需要 controller 端的當前 state）。
    func applyRerankResult(_ outcome: Result<String, AICorrectionError>, context: AICandidateRerankContext, client: Any?)
    func applyAutoCorrectionResult(_ outcome: Result<String, AICorrectionError>, composingBuffer: String, client: Any?)
    // Add more actions as needed for invisibility (commit, show tooltip, etc.)
}

final class AIAssistCoordinator {

    weak var controller: McBopomofoInputMethodController?
    weak var delegate: AIAssistControllerDelegate?

    private let rescorer: CandidateRescorer
    private let sentenceCorrector: SentenceCorrector

    // L1 / L2 狀態現在由 Coordinator 擁有（設計報告階段一目標：消除散落狀態）
    // 保留與舊程式碼相容的命名，方便逐步遷移。
    var aiCandidateSuggestion: AICandidateSuggestion?
    var aiCandidateRequestSerial: UInt = 0
    var aiCandidateDidNotifyLocalServerLoading = false
    var aiCandidateRerankedValue: String?
    var aiCandidateRerankWorkItem: DispatchWorkItem?
    var aiCandidateServerRetryWorkItem: DispatchWorkItem?

    // Phase 2 L2
    var aiAutoCorrectionSuggestion: AICandidateSuggestion?
    var aiAutoCorrectionRequestSerial: UInt = 0
    var aiAutoCorrectionDidNotifyLocalServerLoading = false
    var aiAutoCorrectionWorkItem: DispatchWorkItem?
    var aiAutoCorrectionServerRetryWorkItem: DispatchWorkItem?

    init(
        controller: McBopomofoInputMethodController?,
        delegate: AIAssistControllerDelegate? = nil,
        rescorer: CandidateRescorer = NgramCandidateRescorer(),
        sentenceCorrector: SentenceCorrector = LocalServerSentenceCorrector()
    ) {
        self.controller = controller
        self.delegate = delegate
        self.rescorer = rescorer
        self.sentenceCorrector = sentenceCorrector
    }

    // MARK: - 公開 API（設計報告建議的乾淨介面）

    func scheduleRerank(context: AICandidateRerankContext, client: Any?) {
        let buffer = context.composingBuffer

        // Skip if already have a rerank for this exact buffer
        if let rerankedValue = aiCandidateRerankedValue,
            context.candidates.first?.value == rerankedValue
        {
            return
        }

        guard rescorer.shouldRescore(context) else {
            cancelPendingRerank()
            if aiCandidateSuggestion?.originalComposingBuffer != buffer {
                aiCandidateSuggestion = nil
            }
            return
        }

        aiCandidateRerankWorkItem?.cancel()
        aiCandidateServerRetryWorkItem?.cancel()

        aiCandidateRequestSerial += 1
        let serial = aiCandidateRequestSerial

        let workItem = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.aiCandidateRerankWorkItem = nil
            // Use protocol for rescore (fast ngram now, future LLM hybrid)
            Task {
                let outcome = await self.rescorer.rescore(context: context)
                await MainActor.run {
                    // Coordinator 擁有 serial：在這裡擋掉過期結果，delegate 只會收到最新請求。
                    guard serial == self.aiCandidateRequestSerial else {
                        NSLog("AI候選建議: 丟棄過期結果")
                        return
                    }
                    self.delegate?.applyRerankResult(outcome, context: context, client: client)
                }
            }
        }
        aiCandidateRerankWorkItem = workItem
        DispatchQueue.main.asyncAfter(
            deadline: .now() + AICandidateReranker.debounceInterval, execute: workItem)
    }

    func scheduleAutoCorrection(composingBuffer: String, preceding: String, cursorIndex: Int, client: Any?) {
        // Skip duplicate
        if let suggestion = aiAutoCorrectionSuggestion,
            suggestion.originalComposingBuffer == composingBuffer
        {
            return
        }

        guard AIAutoCorrector.shouldSchedule(composingBuffer: composingBuffer, cursorIndex: cursorIndex) else {
            cancelPendingAutoCorrection()
            if aiAutoCorrectionSuggestion?.originalComposingBuffer != composingBuffer {
                aiAutoCorrectionSuggestion = nil
            }
            return
        }

        aiAutoCorrectionWorkItem?.cancel()
        aiAutoCorrectionServerRetryWorkItem?.cancel()

        aiAutoCorrectionRequestSerial += 1
        let serial = aiAutoCorrectionRequestSerial

        let workItem = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.aiAutoCorrectionWorkItem = nil

            Task {
                let outcome = await self.sentenceCorrector.correct(guess: composingBuffer, preceding: preceding)
                await MainActor.run {
                    // Coordinator 擁有 serial：在這裡擋掉過期結果，delegate 只會收到最新請求。
                    guard serial == self.aiAutoCorrectionRequestSerial else {
                        NSLog("AI自動校正: 丟棄過期結果")
                        return
                    }
                    self.delegate?.applyAutoCorrectionResult(outcome, composingBuffer: composingBuffer, client: client)
                }
            }
        }
        aiAutoCorrectionWorkItem = workItem
        DispatchQueue.main.asyncAfter(
            deadline: .now() + AIAutoCorrector.debounceInterval, execute: workItem)
    }

    // MARK: - Accept 決策（純函式，可單元測試）
    //
    // 「目前 buffer 是否仍與建議的原始 buffer 相同 → 該採用哪段文字」這個判斷不需要碰
    // IMK / state，搬進 Coordinator 後可直接測。實際的 commit（碰 client）仍由 controller 做。

    /// L1：若目前 composing buffer 仍與候選建議的原始 buffer 相同，回傳該採用的文字，否則 nil。
    func candidateSuggestion(matching buffer: String) -> String? {
        guard let suggestion = aiCandidateSuggestion,
            suggestion.originalComposingBuffer == buffer
        else {
            return nil
        }
        return suggestion.suggestion
    }

    /// L2：若目前 composing buffer 仍與自動校正建議的原始 buffer 相同，回傳該採用的文字，否則 nil。
    func autoCorrectionSuggestion(matching buffer: String) -> String? {
        guard let suggestion = aiAutoCorrectionSuggestion,
            suggestion.originalComposingBuffer == buffer
        else {
            return nil
        }
        return suggestion.suggestion
    }

    /// 採用 L1 候選建議後的善後：取消 pending、清狀態、bump serial（讓任何 in-flight 結果作廢）。
    func consumeCandidateSuggestion() {
        cancelPendingRerank()
        aiCandidateSuggestion = nil
        aiCandidateRerankedValue = nil
        aiCandidateRequestSerial += 1
    }

    /// 採用 L2 自動校正建議後的善後。
    func consumeAutoCorrectionSuggestion() {
        cancelPendingAutoCorrection()
        aiAutoCorrectionSuggestion = nil
        aiAutoCorrectionRequestSerial += 1
    }

    func reset() {
        cancelAll()
        aiCandidateSuggestion = nil
        aiAutoCorrectionSuggestion = nil
        aiCandidateDidNotifyLocalServerLoading = false
        aiAutoCorrectionDidNotifyLocalServerLoading = false
        aiCandidateRerankedValue = nil
    }

    func cancelPendingRerank() {
        aiCandidateRerankWorkItem?.cancel()
        aiCandidateRerankWorkItem = nil
        aiCandidateServerRetryWorkItem?.cancel()
        aiCandidateServerRetryWorkItem = nil
    }

    func cancelPendingAutoCorrection() {
        aiAutoCorrectionWorkItem?.cancel()
        aiAutoCorrectionWorkItem = nil
        aiAutoCorrectionServerRetryWorkItem?.cancel()
        aiAutoCorrectionServerRetryWorkItem = nil
    }

    private func cancelAll() {
        cancelPendingRerank()
        cancelPendingAutoCorrection()
    }
}

// 注意：這是階段一骨架檔。實際把原本 extension 內的 debounce、serial、workItem 擁有權搬進來後，
// Controller 會變瘦（只剩少量狀態 + 呼叫 coordinator）。
// 目前不影響既有行為。
