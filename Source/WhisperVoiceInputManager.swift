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

/// 選項 3 的錄音端:OpenAI Whisper 雲端語音輸入。與 Apple 的 `VoiceInputManager`
/// (邊講邊辨識)不同,這個是「錄完整段 → 上傳辨識」:雙擊右 Shift 開始錄音、
/// 再雙擊停止後,把錄到的整段 WAV 交給 `WhisperVoiceTranscriber` 上傳,回文字走
/// 既有 commit 出口。
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

        guard let url, let data = try? Data(contentsOf: url), !data.isEmpty else {
            cleanupFile()
            onError?(NSLocalizedString("Voice recognition failed", comment: ""))
            return
        }

        DispatchQueue.global(qos: .userInitiated).async {
            let outcome = WhisperVoiceTranscriber.transcribe(
                wavData: data, fileName: url.lastPathComponent)
            DispatchQueue.main.async {
                self.cleanupFile()
                switch outcome {
                case let .success(text): self.onFinalText?(text)
                case let .failure(error): self.onError?(error.userMessage)
                }
            }
        }
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
