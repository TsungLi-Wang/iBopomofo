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
import CryptoKit
import Darwin
import NotifierUI

// MARK: - 本機語音辨識伺服器管理(內嵌 whisper-server)
//
// 與 LlamaServerManager 同一套路:whisper.cpp 的 `whisper-server`(HTTP /inference)
// 打包進 app(Contents/Resources/whisper/bin/),語音輸入首次使用時 spawn。
// 模型本身不打包,首次使用時從 HuggingFace 下載到 Application Support。
// 完全離線辨識:錄音與音訊都不出機器。
//
// 設計重點:
//  - 綁 127.0.0.1 + 系統配置的空閒 port,只給本機自己連,不對外。
//  - 不在 app 啟動時 spawn(模型常駐 ~0.9GB 記憶體);第一次語音輸入才啟動,之後保持存活。
//  - app 結束(applicationWillTerminate)時 terminate,並先清孤兒。
@objc(WhisperServerManager)
final class WhisperServerManager: NSObject {

    @objc static let shared = WhisperServerManager()

    private let lock = NSLock()
    private var process: Process?
    private var serverPort: Int = 0
    private var serverReady = false

    // 模型下載狀態(由 ensureModelDownloaded 管理)。
    private var downloadSession: URLSession?
    private var downloadTask: URLSessionDownloadTask?
    private var isDownloading = false
    private var lastNotifiedDecile = -1

    private override init() { super.init() }

    // MARK: bundle 內 runtime 路徑

    /// Contents/Resources/whisper/bin/whisper-server(靜態連結,無 dylib)。
    private var serverBinaryURL: URL? {
        Bundle.main.url(
            forResource: "whisper-server", withExtension: nil, subdirectory: "whisper/bin")
    }

    // MARK: 模型(不內嵌,首次使用時下載到 Application Support)
    //
    // large-v3-turbo q5_0:2026-07-07 以 say 生成的 zh-TW 測試音訊與 ggml-small 同條件對比,
    // turbo-q5_0 錯 1 句、small 錯 2 句(候選字→後選字);每句約 1.7s(M2),準度優先選 turbo。
    // 輸出偶帶簡體,由呼叫端統一過 OpenCC 轉繁(與本機 L2 後端同一個安全網)。

    /// HuggingFace ggerganov/whisper.cpp 上的 large-v3-turbo q5_0(MIT)。
    static let modelDownloadURLString =
        "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin"
    /// 完整檔大小(bytes)。下載後核對,半途中斷的殘檔不會被當成已安裝。
    static let modelExpectedSize: Int64 = 574_041_195
    /// 完整檔 SHA256。大小只能抓截斷檔,hash 才能抓錯檔/損毀檔。
    static let modelExpectedSHA256 =
        "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2"

    /// ~/Library/Application Support/McBopomofo/WhisperModel/
    private var modelDirectoryURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("iBopomofo", isDirectory: true)
            .appendingPathComponent("WhisperModel", isDirectory: true)
    }

    /// 下載後的模型檔位置。
    private var modelFileURL: URL { modelDirectoryURL.appendingPathComponent("model.bin") }

    /// 模型是否已完整安裝(存在且大小符合,排除半途殘檔)。
    @objc var isModelInstalled: Bool {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: modelFileURL.path),
            let size = attrs[.size] as? Int64
        else { return false }
        return size == Self.modelExpectedSize
    }

    // MARK: 對外狀態

    /// 目前 server 的 base URL(例:http://127.0.0.1:54321);未啟動回 nil。
    var baseURL: String? {
        lock.lock()
        defer { lock.unlock() }
        guard let p = process, p.isRunning, serverPort != 0 else { return nil }
        return "http://127.0.0.1:\(serverPort)"
    }

    // MARK: 生命週期

    /// 錄音開始時呼叫:挑空閒 port、spawn server(錄音期間背景載入模型,停止時通常已就緒)。
    /// 已在跑就跳過;子程序已死就清掉參照重新 spawn。
    @objc func startIfNeeded() {
        lock.lock()
        defer { lock.unlock() }
        if let p = process {
            if p.isRunning { return }
            process = nil
            serverPort = 0
            serverReady = false
        }
        guard let bin = serverBinaryURL else {
            NSLog("WhisperServer: 找不到 bundle 內的 whisper-server,語音輸入不可用")
            return
        }
        if QuarantineHelper.hasQuarantineAttribute(at: Bundle.main.bundlePath) {
            _ = QuarantineHelper.stripQuarantineOnMainBundleIfNeeded()
        }
        guard isModelInstalled else {
            NSLog("WhisperServer: 模型尚未下載,先不啟動 server(請呼叫 ensureModelDownloaded)")
            return
        }
        let model = modelFileURL

        killStaleInstances(modelPath: model.path)

        let port = Self.findFreePort()
        let proc = Process()
        proc.executableURL = bin
        proc.arguments = [
            "-m", model.path,
            "--host", "127.0.0.1",
            "--port", String(port),
            "-l", "zh",
            // 偏置繁體輸出(2026-07-07 實測有效);殘餘簡體由 OpenCC 安全網轉換。
            "--prompt", "以下是繁體中文的句子。",
        ]
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice
        proc.terminationHandler = { _ in
            NSLog("WhisperServer: 子程序已結束")
        }

        do {
            try proc.run()
            process = proc
            serverPort = port
            serverReady = false
            NSLog("WhisperServer: 已啟動於 127.0.0.1:\(port),背景載入模型中…")
        } catch {
            NSLog("WhisperServer: 啟動失敗 — \(error.localizedDescription)")
            process = nil
            serverPort = 0
            serverReady = false
        }
    }

    /// app 結束時呼叫:kill 子程序,別留孤兒佔記憶體。
    @objc func stop() {
        lock.lock()
        defer { lock.unlock() }
        if let p = process, p.isRunning {
            p.terminate()
        }
        process = nil
        serverPort = 0
        serverReady = false
    }

    /// 確保 server 已啟動且模型載入完成(/health=200)。回傳就緒的 base URL,逾時回 nil。
    /// 由背景佇列呼叫(轉寫前);turbo-q5 冷載入約 2~5s。
    func ensureReady(timeout: TimeInterval = 30) -> String? {
        startIfNeeded()
        guard let base = baseURL else { return nil }
        guard let healthURL = URL(string: base + "/health") else { return nil }

        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if Self.probeHealthOnce(healthURL) {
                lock.lock()
                serverReady = true
                lock.unlock()
                return baseURL
            }
            Thread.sleep(forTimeInterval: 0.3)
        }
        return nil
    }

    /// 對 /health 發一次同步探測,200 回 true。
    private static func probeHealthOnce(_ healthURL: URL) -> Bool {
        var req = URLRequest(url: healthURL)
        req.timeoutInterval = 2
        let sem = DispatchSemaphore(value: 0)
        var ok = false
        URLSession.shared.dataTask(with: req) { _, response, _ in
            ok = (response as? HTTPURLResponse)?.statusCode == 200
            sem.signal()
        }.resume()
        _ = sem.wait(timeout: .now() + 3)
        return ok
    }

    /// 首次使用語音輸入時呼叫:若模型尚未安裝,從 HuggingFace 背景下載到 Application Support。
    /// 冪等——已安裝或正在下載都直接返回。下載完成後自動 spawn server。
    @objc func ensureModelDownloaded() {
        lock.lock()
        if isModelInstalled || isDownloading {
            lock.unlock()
            if isModelInstalled { startIfNeeded() }
            return
        }
        isDownloading = true
        lastNotifiedDecile = -1
        lock.unlock()

        guard let url = URL(string: Self.modelDownloadURLString) else {
            lock.lock(); isDownloading = false; lock.unlock()
            return
        }
        try? FileManager.default.createDirectory(
            at: modelDirectoryURL, withIntermediateDirectories: true)

        notify("首次使用語音輸入:正在下載辨識模型(約 574MB,一次性),完成後即可永久離線使用…")

        let session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
        let task = session.downloadTask(with: url)
        lock.lock()
        downloadSession = session
        downloadTask = task
        lock.unlock()
        task.resume()
    }

    fileprivate func notify(_ message: String) {
        DispatchQueue.main.async { NotifierController.notify(message: message) }
    }

    // MARK: 工具

    /// 用 bind(port 0) 讓系統配一個空閒 TCP port,讀回後關掉。
    private static func findFreePort() -> Int {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        if fd < 0 { return 8227 }
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        addr.sin_port = 0
        let bound = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        if bound != 0 { return 8227 }
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        let got = withUnsafeMutablePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                getsockname(fd, $0, &len)
            }
        }
        if got != 0 { return 8227 }
        return Int(UInt16(bigEndian: addr.sin_port))
    }

    /// 清掉上次沒收乾淨的同路徑 whisper-server 孤兒(例如 app 被 pkill 強制結束時)。
    private func killStaleInstances(modelPath: String) {
        let pkill = Process()
        pkill.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        pkill.arguments = ["-f", "whisper-server.*\(modelPath)"]
        pkill.standardOutput = FileHandle.nullDevice
        pkill.standardError = FileHandle.nullDevice
        try? pkill.run()
        pkill.waitUntilExit()
    }

    /// 串流計算 SHA256,避免一次把整顆模型載進記憶體。
    private static func sha256Hex(of fileURL: URL) -> String? {
        guard let handle = try? FileHandle(forReadingFrom: fileURL) else { return nil }
        defer { try? handle.close() }

        var hasher = SHA256()
        while true {
            let data = autoreleasepool {
                let data = handle.readData(ofLength: 8 * 1024 * 1024)
                return data
            }
            if data.isEmpty { break }
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}

// MARK: - 模型下載進度/完成處理
extension WhisperServerManager: URLSessionDownloadDelegate {

    /// 下載進度:每跨過一個 10% 里程碑就通知一次,避免洗版。
    func urlSession(
        _ session: URLSession, downloadTask: URLSessionDownloadTask,
        didWriteData bytesWritten: Int64, totalBytesWritten: Int64,
        totalBytesExpectedToWrite: Int64
    ) {
        let total = totalBytesExpectedToWrite > 0 ? totalBytesExpectedToWrite : Self.modelExpectedSize
        guard total > 0 else { return }
        let decile = Int(Double(totalBytesWritten) / Double(total) * 10)
        lock.lock()
        let shouldNotify = decile > lastNotifiedDecile && decile >= 1 && decile <= 9
        if shouldNotify { lastNotifiedDecile = decile }
        lock.unlock()
        if shouldNotify {
            notify("語音辨識模型下載中… \(decile * 10)%")
        }
    }

    /// 下載完成:搬到正式位置 + 核對大小。大小不符視為失敗,刪除殘檔。
    func urlSession(
        _ session: URLSession, downloadTask: URLSessionDownloadTask,
        didFinishDownloadingTo location: URL
    ) {
        let fm = FileManager.default
        let dest = modelFileURL
        do {
            try? fm.removeItem(at: dest)
            try fm.moveItem(at: location, to: dest)
        } catch {
            NSLog("WhisperServer: 模型搬移失敗 — \(error.localizedDescription)")
            notify("語音辨識模型下載失敗(寫入錯誤),稍後再連按兩下右 Shift 重試。")
            finishDownload()
            return
        }
        guard isModelInstalled else {
            let got = ((try? fm.attributesOfItem(atPath: dest.path))?[.size] as? Int64) ?? 0
            NSLog("WhisperServer: 模型大小不符(得 \(got),期望 \(Self.modelExpectedSize)),刪除殘檔")
            try? fm.removeItem(at: dest)
            notify("語音辨識模型下載不完整,請再連按兩下右 Shift 重試。")
            finishDownload()
            return
        }
        notify("語音辨識模型下載完成,正在驗證完整性…")
        guard Self.sha256Hex(of: dest) == Self.modelExpectedSHA256 else {
            NSLog("WhisperServer: 模型 SHA256 不符,刪除檔案")
            try? fm.removeItem(at: dest)
            notify("語音辨識模型驗證失敗,請再連按兩下右 Shift 重試。")
            finishDownload()
            return
        }
        notify("語音辨識模型已就緒,連按兩下右 Shift 即可開始說話。")
        finishDownload()
        startIfNeeded()
    }

    /// 下載出錯(網路中斷等)。
    func urlSession(
        _ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?
    ) {
        guard let error = error else { return }
        NSLog("WhisperServer: 模型下載失敗 — \(error.localizedDescription)")
        notify("語音辨識模型下載失敗(網路問題),請連網後再連按兩下右 Shift 重試。")
        finishDownload()
    }

    private func finishDownload() {
        lock.lock()
        isDownloading = false
        downloadTask = nil
        downloadSession?.finishTasksAndInvalidate()
        downloadSession = nil
        lock.unlock()
    }
}
