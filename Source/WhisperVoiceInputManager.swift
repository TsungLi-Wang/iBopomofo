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

import AVFoundation
import Foundation

/// 語音輸入的錄音端:「錄完整段 → 本機辨識」。雙擊右 Shift 開始錄音、再雙擊停止後,
/// 把錄到的整段音訊轉成 16kHz WAV 交給 `WhisperVoiceTranscriber`(內嵌 whisper-server,
/// 完全離線),回文字走既有 commit 出口。
///
/// 只需要麥克風授權(不需要 Speech Recognition 授權、也不需系統「聽寫」)。
@objc final class WhisperVoiceInputManager: NSObject {

    @objc static let shared = WhisperVoiceInputManager()

    private let audioEngine = AVAudioEngine()
    private var audioFile: AVAudioFile?
    private var fileURL: URL?

    private(set) var isRecording = false

    /// 拿到最終辨識文字時回呼(主執行緒)。
    var onFinalText: ((String) -> Void)?
    /// 發生錯誤時回呼(主執行緒),帶可顯示的訊息。
    var onError: ((String) -> Void)?

    private override init() { super.init() }

    /// 雲端辨識只需要麥克風授權。
    var hasRequiredAuthorization: Bool {
        AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    }

    func requestAuthorization(completion: @escaping (Bool) -> Void) {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            DispatchQueue.main.async { completion(true) }
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                DispatchQueue.main.async { completion(granted) }
            }
        default:
            DispatchQueue.main.async { completion(false) }
        }
    }

    private func reportStartFailure(_ detail: String) {
        onError?(
            String(
                format: NSLocalizedString("Cannot start microphone: %@", comment: ""), detail))
    }

    func start() {
        guard !isRecording else { return }

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            reportStartFailure(NSLocalizedString("Voice recognition is unavailable", comment: ""))
            return
        }

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("laowang-voice-\(UUID().uuidString).wav")
        do {
            // 用與 tap buffer 相同的格式建立檔案,避免寫入時格式不符而丟例外。
            audioFile = try AVAudioFile(forWriting: url, settings: format.settings)
        } catch {
            NSLog("語音錄音: 建立檔案失敗 \(error.localizedDescription)")
            reportStartFailure(error.localizedDescription)
            return
        }
        fileURL = url

        if let tapError = AudioTapInstaller.installTap(
            on: inputNode, bus: 0, bufferSize: 4096, format: nil,
            block: { [weak self] buffer, _ in
                guard let self, let file = self.audioFile else { return }
                try? file.write(from: buffer)
            })
        {
            NSLog("語音錄音: 安裝 tap 失敗 \(tapError)")
            reportStartFailure(tapError)
            teardown()
            return
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            NSLog("語音錄音: 引擎啟動失敗 \(error.localizedDescription)")
            reportStartFailure(error.localizedDescription)
            teardown()
            return
        }
        isRecording = true
    }

    /// 停止錄音並把整段上傳辨識。最終文字仍由 `onFinalText` 送出。
    func stop() {
        guard isRecording else { return }
        isRecording = false
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        let url = fileURL
        audioFile = nil  // 釋放即 flush + 關檔

        guard let url else {
            cleanupFile()
            onError?(NSLocalizedString("Voice recognition failed", comment: ""))
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            // whisper-server 只吃 16kHz 16-bit mono WAV;錄音檔是 tap 原生格式
            // (通常 48kHz float32),用系統 afconvert 轉一次(比 AVAudioConverter 少一坨碼)。
            let converted = url.deletingPathExtension().appendingPathExtension("16k.wav")
            defer { try? FileManager.default.removeItem(at: converted) }
            let outcome: Result<String, AICorrectionError>
            if Self.convertTo16kMonoWAV(input: url, output: converted),
                let data = try? Data(contentsOf: converted), !data.isEmpty
            {
                outcome = WhisperVoiceTranscriber.transcribe(
                    wavData: data, fileName: converted.lastPathComponent)
            } else {
                outcome = .failure(
                    .unavailable(
                        backend: AICorrectionBackendName.whisper, detail: "錄音檔轉換失敗"))
            }
            DispatchQueue.main.async {
                self.cleanupFile()
                switch outcome {
                case let .success(text): self.onFinalText?(text)
                case let .failure(error): self.onError?(error.userMessage)
                }
            }
        }
    }

    /// 用 /usr/bin/afconvert 把錄音檔轉成 whisper 需要的 16kHz 16-bit mono WAV。
    private static func convertTo16kMonoWAV(input: URL, output: URL) -> Bool {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/afconvert")
        proc.arguments = ["-f", "WAVE", "-d", "LEI16@16000", "-c", "1", input.path, output.path]
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice
        do {
            try proc.run()
        } catch {
            NSLog("語音錄音: afconvert 啟動失敗 \(error.localizedDescription)")
            return false
        }
        proc.waitUntilExit()
        return proc.terminationStatus == 0
    }

    private func teardown() {
        isRecording = false
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        audioFile = nil
        cleanupFile()
    }

    private func cleanupFile() {
        if let url = fileURL { try? FileManager.default.removeItem(at: url) }
        fileURL = nil
    }
}
