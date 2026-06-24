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

extension McBopomofoInputMethodController {

    // 目前選的後端,存 UserDefaults。0=Codex 1=Claude Haiku 2=Claude Opus 3=本機 AI(內建)
    static var aiBackend: Int {
        // 未設定過時預設「本機 AI(3)」:離線、免 API key、免裝 Ollama。
        get {
            guard UserDefaults.standard.object(forKey: "AICorrectionBackend") != nil else { return 3 }
            return UserDefaults.standard.integer(forKey: "AICorrectionBackend")
        }
        set { UserDefaults.standard.set(newValue, forKey: "AICorrectionBackend") }
    }

    func triggerAICorrection(guess: String, client: Any!) {
        let preceding = Self.precedingTextForAI(from: client, maxChars: 100)
        let backend = Self.aiBackend

        if backend == 3, !LocalServerAICorrector.isModelInstalled {
            LocalServerAICorrector.ensureModelDownloaded()
            return
        }

        if backend == 3, !LocalServerAICorrector.isReady {
            LocalServerAICorrector.startIfNeeded()
            NotifierController.notify(message: "本機 AI 模型載入中,請稍候幾秒再按一次 ⌘Enter")
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            let corrected = Self.correctAIGuess(guess: guess, preceding: preceding, backend: backend)
            DispatchQueue.main.async {
                self.applyAICorrectionResult(corrected, originalGuess: guess, client: client)
            }
        }
    }

    static func startLocalServerIfNeeded() {
        guard aiBackend == 3 else { return }
        DispatchQueue.global(qos: .utility).async {
            if LocalServerAICorrector.isModelInstalled {
                LocalServerAICorrector.startIfNeeded()
            }
        }
    }

    private static func correctAIGuess(guess: String, preceding: String, backend: Int) -> String? {
        switch backend {
        case 1:
            return ClaudeAICorrector.correct(
                guess: guess, preceding: preceding, model: AICorrectionConfig.claudeHaikuModel)
        case 2:
            return ClaudeAICorrector.correct(
                guess: guess, preceding: preceding, model: AICorrectionConfig.claudeOpusModel)
        case 3:
            return LocalServerAICorrector.correct(guess: guess, preceding: preceding)
        default:
            return CodexAICorrector.correct(guess: guess, preceding: preceding)
        }
    }

    private func applyAICorrectionResult(_ corrected: String?, originalGuess guess: String, client: Any!) {
        guard let currentInputting = state as? InputState.Inputting,
            currentInputting.composingBuffer == guess
        else {
            NSLog("AI校正: composing 狀態已變更,丟棄過期結果")
            return
        }

        guard let corrected, !corrected.isEmpty else {
            NotifierController.notify(message: "AI 修正失敗(可能 API 額度不足或逾時)")
            return
        }
        guard corrected != guess else { return }

        keyHandler.clear()
        handle(state: InputState.Committing(poppedText: corrected), client: client)
        handle(state: InputState.Empty(), client: client)
    }

    // 移植 azooKey 的做法:用 IMKTextInput 讀游標前已上字的前文。
    private static func precedingTextForAI(from client: Any!, maxChars: Int) -> String {
        guard let imk = client as? IMKTextInput else { return "" }
        let cursor = imk.selectedRange().location
        guard cursor != NSNotFound, cursor > 0 else { return "" }
        let start = max(0, cursor - maxChars)
        let range = NSRange(location: start, length: cursor - start)
        var actual = NSRange()
        return imk.string(from: range, actualRange: &actual) ?? ""
    }
}
