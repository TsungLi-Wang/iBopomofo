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

    /// 組字區最短長度(含句末標點)。低於此長度的句子不值得送 server。
    static let minComposingLength = 4

    /// 句末標點集合。刻意只收「整句結束」的標點,不含逗號、頓號等句中標點,
    /// 以免在使用者還在寫同一句時就觸發。
    static let sentenceEndingPunctuation = Set("。！？!?…")

    /// 組字區最後一個字元是否為句末標點。
    static func endsWithSentencePunctuation(_ buffer: String) -> Bool {
        guard let last = buffer.last else { return false }
        return sentenceEndingPunctuation.contains(last)
    }

    /// 純邏輯觸發判斷:不檢查偏好設定與 server 是否就緒(那些由 controller 處理)。
    /// 條件:長度達門檻、游標在句尾、且以句末標點結束。
    static func isCorrectableSentence(composingBuffer: String, cursorIndex: Int) -> Bool {
        guard composingBuffer.count >= minComposingLength else { return false }
        guard cursorIndex == composingBuffer.count else { return false }
        return endsWithSentencePunctuation(composingBuffer)
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
}
