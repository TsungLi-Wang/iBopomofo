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

/// L1.5 延遲全局重審(deferred global re-rank)。
/// 設計:docs/l1-neural-rerank-integration.md 第 8 節。
///
/// 「右文不足」的根治:整句打分的優勢全部來自右文,而右文只是「還沒到」——
/// 使用者多打 2-4 個字它就到了。所以決策點不設在候選窗瞬間,而是:
/// 每次 Inputting 更新 → debounce → 向 KeyHandler 要 walk 上的歧義節點清單 →
/// 對「右文已累積 >=2 字」的位置做整句打分 → margin 過門檻就 soft override
/// 隱形改選(override-without-observe,使用者手動選字永遠優先)→ 重建畫面。
///
/// 分工:混淆表擁有 ㄗㄞˋ(在/再;它有針對性語料、精確率 92.3%,而 4B 模型對
/// 「在」有系統性偏好,sim 顯示會把表翻對的「再」翻回去)。本層只審表沒覆蓋的
/// 歧義字(的/得/地、平翹舌、語意對),字集見 neuralDeferredCharacters。
extension McBopomofoInputMethodController {

    static let neuralDeferredDebounce: TimeInterval = 0.6
    static let neuralDeferredMaxSpansPerPass = 2
    static let neuralDeferredMinBufferLength = 4
    static let neuralDeferredScoreBudget: TimeInterval = 1.5

    /// 神經層追蹤的歧義字(刻意排除混淆表擁有的 在/再/載)。
    /// 涵蓋 sim 驗證過的 pair:的得地、知資、支枝、師詩、之、直值、姿、
    /// 訂定、清青、決絕、行航、船傳、裡裏、做作。
    static let neuralDeferredCharacters =
        "的得地做作知資支枝師詩之直值姿訂定清青決絕行航船傳裡裏"

    func scheduleNeuralDeferredCheckIfNeeded(for state: InputState.Inputting, client: Any?) {
        guard Preferences.enableGlobalNeuralRerank else { return }
        guard state.composingBuffer.count >= Self.neuralDeferredMinBufferLength else { return }

        let coordinator = aiAssistCoordinator
        coordinator.neuralDeferredWorkItem?.cancel()
        coordinator.neuralDeferredSerial += 1
        let serial = coordinator.neuralDeferredSerial

        let workItem = DispatchWorkItem { [weak self] in
            self?.performNeuralDeferredCheck(serial: serial, client: client)
        }
        coordinator.neuralDeferredWorkItem = workItem
        DispatchQueue.main.asyncAfter(
            deadline: .now() + Self.neuralDeferredDebounce, execute: workItem)
    }

    private func performNeuralDeferredCheck(serial: UInt, client: Any?) {
        let coordinator = aiAssistCoordinator
        coordinator.neuralDeferredWorkItem = nil
        guard serial == coordinator.neuralDeferredSerial else { return }
        guard Preferences.enableGlobalNeuralRerank, LlamaServerManager.shared.isReady else {
            return
        }
        guard let inputting = state as? InputState.Inputting else { return }
        guard
            let snapshot = keyHandler.neuralRerankSnapshot(
                characters: Self.neuralDeferredCharacters, maxAlternatives: 4)
                as? [String: Any],
            let text = snapshot["text"] as? String,
            let spans = snapshot["spans"] as? [[String: Any]], !spans.isEmpty
        else { return }
        // 對齊守門:walk 攤平字串必須等於 composing buffer(游標處有打到一半的
        // 音節時兩者不等,這輪直接跳過,音節落地後的下一次停頓自然會再來)。
        guard text == inputting.composingBuffer else { return }

        let scalars = Array(text.unicodeScalars)
        var pending:
            [(location: Int, reading: String, current: String, alternatives: [String],
              left: String, right: String)] = []

        for span in spans {
            guard pending.count < Self.neuralDeferredMaxSpansPerPass else { break }
            guard let location = span["location"] as? Int,
                let reading = span["reading"] as? String,
                let current = span["current"] as? String,
                let rawAlternatives = span["alternatives"] as? [String]
            else { continue }
            // 右文 gate:與候選窗路徑同一條件。
            let rightCount = scalars.count - (location + 1)
            guard rightCount >= NeuralCandidateRescorer.rightContextMinChars else { continue }
            // 同一「位置+語境」只審一次;buffer 一變鍵就不同,右文增長自然重審。
            let key = "\(location):\(text)"
            guard !coordinator.neuralDeferredDecidedKeys.contains(key) else { continue }

            let alternatives = rawAlternatives.filter { !AICandidateReranker.isSymbolOrEmoji($0) }
            guard alternatives.count >= 2, alternatives.contains(current) else { continue }

            let leftStart = max(0, location - NeuralCandidateRescorer.leftWindowChars)
            let left = String(String.UnicodeScalarView(scalars[leftStart..<location]))
            let rightEnd = min(
                scalars.count, location + 1 + NeuralCandidateRescorer.rightWindowChars)
            let right = String(String.UnicodeScalarView(scalars[(location + 1)..<rightEnd]))

            if coordinator.neuralDeferredDecidedKeys.count > 200 {
                coordinator.neuralDeferredDecidedKeys.removeAll()
            }
            coordinator.neuralDeferredDecidedKeys.insert(key)
            pending.append((location, reading, current, alternatives, left, right))
        }
        guard !pending.isEmpty else { return }

        Task { [weak self] in
            var decisions: [(location: Int, reading: String, current: String, value: String)] = []
            for item in pending {
                guard
                    let scores = await AISentenceScorer.shared.scoreAlternatives(
                        left: item.left, alternatives: item.alternatives, right: item.right,
                        deadline: Date().addingTimeInterval(Self.neuralDeferredScoreBudget))
                else { continue }
                let choice = AISentenceScorer.decide(
                    scores: scores, current: item.current,
                    margin: NeuralCandidateRescorer.decisionMargin)
                if choice != item.current {
                    decisions.append((item.location, item.reading, item.current, choice))
                }
            }
            guard !decisions.isEmpty else { return }

            await MainActor.run { [weak self] in
                guard let self else { return }
                let coordinator = self.aiAssistCoordinator
                // 打分期間使用者可能繼續動作:serial + buffer 雙守門,過期丟棄。
                guard serial == coordinator.neuralDeferredSerial else { return }
                guard let currentState = self.state as? InputState.Inputting,
                    currentState.composingBuffer == text
                else { return }

                var appliedText = Array(text.unicodeScalars)
                var applied = false
                for decision in decisions {
                    if self.keyHandler.applyNeuralOverride(
                        location: UInt(decision.location), reading: decision.reading,
                        expectedCurrent: decision.current, value: decision.value)
                    {
                        applied = true
                        if let scalar = decision.value.unicodeScalars.first,
                            decision.value.unicodeScalars.count == 1
                        {
                            appliedText[decision.location] = scalar
                        }
                        NSLog(
                            "AI延遲重審: 位置 %d %@ → %@", decision.location, decision.current,
                            decision.value)
                    }
                }
                guard applied else { return }
                // 改選後的新語境視為已審,省掉一輪只會維持原判的重打分。
                let newText = String(String.UnicodeScalarView(appliedText))
                for decision in decisions {
                    coordinator.neuralDeferredDecidedKeys.insert("\(decision.location):\(newText)")
                }
                self.handle(state: self.keyHandler.buildInputtingState(), client: client)
            }
        }
    }
}
