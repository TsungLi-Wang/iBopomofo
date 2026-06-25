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
import Speech

/// Phase 3 語音輸入(語音 → 文字)。
///
/// 刻意保持獨立、不碰 L0 打字流程:呼叫端(controller)開始錄音、拿到最終辨識文字後,
/// 再走既有 commit 出口 `InputState.Committing` 落地。用 Apple 內建
/// `SFSpeechRecognizer`(zh-TW,優先 on-device),零內嵌、離線可用。
///
/// on-device 離線辨識需要使用者在「系統設定 ▸ 鍵盤 ▸ 聽寫」開啟聽寫(否則
/// `SFSpeechRecognitionTask` 會回 `kLSRErrorDomain 201`)。已實機驗證輸入法
/// (input method)程序能取得麥克風授權並穩定錄音。
@objc final class VoiceInputManager: NSObject {

    @objc static let shared = VoiceInputManager()

    private let audioEngine = AVAudioEngine()
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-TW"))
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    private(set) var isRecording = false

    /// 拿到最終辨識文字時回呼(主執行緒)。
    var onFinalText: ((String) -> Void)?
    /// 發生錯誤時回呼(主執行緒),帶可顯示的訊息。
    var onError: ((String) -> Void)?

    private override init() {
        super.init()
    }

    /// 請求語音辨識 + 麥克風授權(兩者都過才算成功)。
    func requestAuthorization(completion: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { speechStatus in
            guard speechStatus == .authorized else {
                DispatchQueue.main.async { completion(false) }
                return
            }
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
    }

    /// 開始錄音與辨識。實際的最終文字透過 `onFinalText` 回呼。
    func start() {
        guard !isRecording else { return }
        guard let recognizer, recognizer.isAvailable else {
            onError?(NSLocalizedString("Voice recognition is unavailable", comment: ""))
            return
        }

        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = false
        if recognizer.supportsOnDeviceRecognition {
            request.requiresOnDeviceRecognition = true
        }
        self.request = request

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            self?.request?.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            onError?(
                String(
                    format: NSLocalizedString("Cannot start microphone: %@", comment: ""),
                    error.localizedDescription))
            teardown()
            return
        }

        isRecording = true
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            if let result, result.isFinal {
                let text = result.bestTranscription.formattedString
                DispatchQueue.main.async { self.onFinalText?(text) }
                self.stop()
            } else if let error {
                DispatchQueue.main.async { self.onError?(Self.message(for: error)) }
                self.stop()
            }
        }
    }

    /// 把辨識器錯誤轉成可顯示訊息。最常見的是 on-device 需要聽寫卻沒開
    /// (`kLSRErrorDomain 201`),特別給引導提示;其餘回通用失敗訊息。
    private static func message(for error: Error) -> String {
        let ns = error as NSError
        if ns.domain == "kLSRErrorDomain" && ns.code == 201 {
            return NSLocalizedString(
                "Voice input needs Dictation: turn it on in System Settings ▸ Keyboard ▸ Dictation",
                comment: "")
        }
        return NSLocalizedString("Voice recognition failed", comment: "")
    }

    /// 停止錄音。停止後辨識器會把累積音訊收尾,最終文字仍由 `onFinalText` 送出。
    func stop() {
        guard isRecording else { return }
        isRecording = false
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        request = nil
    }

    private func teardown() {
        isRecording = false
        if audioEngine.isRunning {
            audioEngine.stop()
            audioEngine.inputNode.removeTap(onBus: 0)
        }
        request = nil
        task = nil
    }
}
