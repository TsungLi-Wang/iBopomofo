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

enum CodexAICorrector {

    static func correct(guess: String, preceding: String) -> Result<String, AICorrectionError> {
        let name = AICorrectionBackendName.codex
        let prompt = AICorrectionPrompt.taggedPrompt(guess: guess, preceding: preceding)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: AICorrectionConfig.codexPath)
        process.arguments = [
            "exec", "--sandbox", "read-only", "--skip-git-repo-check",
            "-m", AICorrectionConfig.codexModel,
            "-c", "model_reasoning_effort=low",
            prompt,
        ]

        let outPipe = Pipe()
        process.standardOutput = outPipe
        process.standardError = Pipe()
        do {
            try process.run()
        } catch {
            NSLog("AI校正: 無法啟動 codex: \(error.localizedDescription)")
            return .failure(.launchFailed(backend: name, detail: error.localizedDescription))
        }

        let deadline = Date().addingTimeInterval(15)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if process.isRunning {
            process.terminate()
            process.waitUntilExit()
            NSLog("AI校正: codex 執行逾時")
            return .failure(.timeout(backend: name))
        }

        let data = outPipe.fileHandleForReading.readDataToEndOfFile()
        let raw = String(data: data, encoding: .utf8) ?? ""
        if process.terminationStatus != 0 {
            NSLog("AI校正: codex 結束碼 \(process.terminationStatus),輸出:\(raw)")
            return .failure(
                .unavailable(backend: name, detail: "codex 執行失敗(可能未登入或無訂閱)"))
        }
        if let extracted = AICorrectionPrompt.extractTaggedResult(from: raw), !extracted.isEmpty {
            return .success(extracted)
        }
        return .failure(.emptyResult(backend: name))
    }
}
