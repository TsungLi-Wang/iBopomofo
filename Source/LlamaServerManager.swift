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
import Darwin
import NotifierUI

// MARK: - 本機 AI 推理伺服器管理(內嵌 llama-server)
//
// 仿 azooKey 的 ConverterServer:把 llama.cpp 的 `llama-server`(OpenAI 相容 HTTP)
// 連同精簡 dylib 打包進 app(Contents/Resources/llama/bin/),app 啟動時自動 spawn、結束時 kill。
// 模型本身不打包(太大會讓 dmg 爆 GitHub 2GiB 上限),改由首次使用時下載到 Application Support
// (見下方「模型」段)。使用者裝 app、首次下載一次後就能離線用本機 AI 修正,
// 完全不必自己裝 Ollama、不必開任何外部伺服器。
//
// 設計重點:
//  - 綁 127.0.0.1 + 系統配置的空閒 port,只給本機自己連,不對外。
//  - 子程序參照存活整個 app 生命週期;app 結束(applicationWillTerminate)時 terminate。
//  - 啟動前先清掉可能殘留的孤兒(上次被 pkill 沒收乾淨的同路徑 server)。
@objc(LlamaServerManager)
final class LlamaServerManager: NSObject {

    @objc static let shared = LlamaServerManager()

    private let lock = NSLock()
    private var process: Process?
    private var serverPort: Int = 0

    // 模型下載狀態(由 ensureModelDownloaded 管理)。
    private var downloadSession: URLSession?
    private var downloadTask: URLSessionDownloadTask?
    private var isDownloading = false
    private var lastNotifiedDecile = -1

    private override init() { super.init() }

    // MARK: bundle 內 runtime 路徑

    /// Contents/Resources/llama/bin/llama-server(dylib 與它同層,靠 @loader_path 載入)。
    private var serverBinaryURL: URL? {
        Bundle.main.url(forResource: "llama-server", withExtension: nil, subdirectory: "llama/bin")
    }

    // MARK: 模型(不內嵌,首次使用時下載到 Application Support)
    //
    // 模型 2.9GB 內嵌會讓發佈 dmg 爆過 GitHub Release 的 2GiB 上限。改成「裝完不含模型,
    // 首次使用本機 AI 時才從 HuggingFace 下載」——dmg 瘦到 ~25MB 可直接上 GitHub Release,
    // 模型由 HF CDN 免費代管;下載一次後永久離線(與 Adobe 等「基本安裝包 + 按需下載大資產」同套路)。
    // 存 Application Support(可寫、不在唯讀的 app bundle 內、不被 quarantine 連坐)。

    /// HuggingFace 上的 Q5_K_M 模型(apache-2.0)。與 llama-runtime/fetch-runtime.sh 同一條。
    static let modelDownloadURLString =
        "https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen_Qwen3-4B-Instruct-2507-Q5_K_M.gguf"
    /// 完整檔大小(bytes)。下載後核對,半途中斷的殘檔不會被當成已安裝。
    static let modelExpectedSize: Int64 = 2_889_513_696

    /// ~/Library/Application Support/McBopomofo/AIModel/
    private var modelDirectoryURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("McBopomofo", isDirectory: true)
            .appendingPathComponent("AIModel", isDirectory: true)
    }

    /// 下載後的模型檔位置。
    private var modelFileURL: URL { modelDirectoryURL.appendingPathComponent("model.gguf") }

    /// 模型是否已完整安裝(存在且大小符合,排除半途殘檔)。
    @objc var isModelInstalled: Bool {
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: modelFileURL.path),
            let size = attrs[.size] as? Int64
        else { return false }
        return size == Self.modelExpectedSize
    }

    // MARK: 對外狀態

    /// 目前 server 的 base URL(例:http://127.0.0.1:54321);未啟動/未就緒回 nil。
    var baseURL: String? {
        lock.lock()
        defer { lock.unlock() }
        guard let p = process, p.isRunning, serverPort != 0 else { return nil }
        return "http://127.0.0.1:\(serverPort)"
    }

    // MARK: 生命週期

    /// app 啟動(或使用者切到本機後端)時呼叫:挑空閒 port、spawn server。已在跑就跳過。
    @objc func startIfNeeded() {
        lock.lock()
        defer { lock.unlock() }
        guard process == nil else { return }
        guard let bin = serverBinaryURL else {
            NSLog("LlamaServer: 找不到 bundle 內的 llama-server,本機後端不可用")
            return
        }
        guard isModelInstalled else {
            NSLog("LlamaServer: 模型尚未下載,先不啟動 server(請呼叫 ensureModelDownloaded)")
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
            "-c", "2048",
            "-ngl", "99",  // 全層上 Metal GPU(3B 在 8GB 以上 Mac 跑得動)
            "--no-webui",
        ]
        proc.standardOutput = FileHandle.nullDevice
        proc.standardError = FileHandle.nullDevice
        proc.terminationHandler = { _ in
            NSLog("LlamaServer: 子程序已結束")
        }

        do {
            try proc.run()
            process = proc
            serverPort = port
            NSLog("LlamaServer: 已啟動於 127.0.0.1:\(port)")
        } catch {
            NSLog("LlamaServer: 啟動失敗 — \(error.localizedDescription)")
            process = nil
            serverPort = 0
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
    }

    /// 首次使用本機 AI 時呼叫:若模型尚未安裝,從 HuggingFace 背景下載到 Application Support。
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

        notify("首次使用本機 AI:正在下載模型(約 2.9GB,一次性),完成後即可永久離線使用…")

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

    /// 確保 server 已啟動且模型載入完成(/health=200)。回傳就緒的 base URL,逾時回 nil。
    /// 校正前呼叫:涵蓋「開機後模型還在載入(3B 約 2–3s)時使用者就按了熱鍵」的情況。
    func ensureReady(timeout: TimeInterval = 15) -> String? {
        startIfNeeded()
        guard let base = baseURL else { return nil }
        guard let healthURL = URL(string: base + "/health") else { return nil }

        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            var req = URLRequest(url: healthURL)
            req.timeoutInterval = 2
            let sem = DispatchSemaphore(value: 0)
            var ok = false
            URLSession.shared.dataTask(with: req) { _, response, _ in
                ok = (response as? HTTPURLResponse)?.statusCode == 200
                sem.signal()
            }.resume()
            _ = sem.wait(timeout: .now() + 3)
            if ok { return baseURL }
            Thread.sleep(forTimeInterval: 0.3)
        }
        return nil
    }

    // MARK: 工具

    /// 用 bind(port 0) 讓系統配一個空閒 TCP port,讀回後關掉。
    private static func findFreePort() -> Int {
        let fd = socket(AF_INET, SOCK_STREAM, 0)
        if fd < 0 { return 8127 }
        defer { close(fd) }
        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_addr.s_addr = inet_addr("127.0.0.1")
        addr.sin_port = 0
        let bound = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                // 明確用 Darwin.bind:NSObject 也有同名的 Cocoa Bindings `bind`,不限定會撞名。
                Darwin.bind(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        if bound != 0 { return 8127 }
        var len = socklen_t(MemoryLayout<sockaddr_in>.size)
        let got = withUnsafeMutablePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                getsockname(fd, $0, &len)
            }
        }
        if got != 0 { return 8127 }
        return Int(UInt16(bigEndian: addr.sin_port))
    }

    /// 清掉上次沒收乾淨的同路徑 llama-server 孤兒(例如 app 被 pkill 強制結束時)。
    private func killStaleInstances(modelPath: String) {
        let pkill = Process()
        pkill.executableURL = URL(fileURLWithPath: "/usr/bin/pkill")
        // 比對完整命令列裡的 model 路徑,只殺我們自己的 server,不誤傷使用者其他 llama-server。
        pkill.arguments = ["-f", "llama-server.*\(modelPath)"]
        pkill.standardOutput = FileHandle.nullDevice
        pkill.standardError = FileHandle.nullDevice
        try? pkill.run()
        pkill.waitUntilExit()
    }
}

// MARK: - 模型下載進度/完成處理
extension LlamaServerManager: URLSessionDownloadDelegate {

    /// 下載進度:每跨過一個 10% 里程碑就通知一次,避免洗版。
    func urlSession(
        _ session: URLSession, downloadTask: URLSessionDownloadTask,
        didWriteData bytesWritten: Int64, totalBytesWritten: Int64,
        totalBytesExpectedToWrite: Int64
    ) {
        // HF 可能不回 Content-Length;沒有就退用已知的完整大小估算。
        let total = totalBytesExpectedToWrite > 0 ? totalBytesExpectedToWrite : Self.modelExpectedSize
        guard total > 0 else { return }
        let decile = Int(Double(totalBytesWritten) / Double(total) * 10)
        lock.lock()
        let shouldNotify = decile > lastNotifiedDecile && decile >= 1 && decile <= 9
        if shouldNotify { lastNotifiedDecile = decile }
        lock.unlock()
        if shouldNotify {
            notify("本機 AI 模型下載中… \(decile * 10)%")
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
            NSLog("LlamaServer: 模型搬移失敗 — \(error.localizedDescription)")
            notify("本機 AI 模型下載失敗(寫入錯誤),稍後可重試或改用雲端後端。")
            finishDownload()
            return
        }
        guard isModelInstalled else {
            // 大小不符:可能下載被截斷。刪除殘檔,下次重新下載。
            let got = ((try? fm.attributesOfItem(atPath: dest.path))?[.size] as? Int64) ?? 0
            NSLog("LlamaServer: 模型大小不符(得 \(got),期望 \(Self.modelExpectedSize)),刪除殘檔")
            try? fm.removeItem(at: dest)
            notify("本機 AI 模型下載不完整,請重試(再按一次 ⌘Enter)。")
            finishDownload()
            return
        }
        notify("本機 AI 模型已就緒,正在載入…首次載入約需數秒。")
        finishDownload()
        startIfNeeded()
    }

    /// 下載出錯(網路中斷等)。
    func urlSession(
        _ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?
    ) {
        guard let error = error else { return }  // 成功的情形已在 didFinishDownloadingTo 處理
        NSLog("LlamaServer: 模型下載失敗 — \(error.localizedDescription)")
        notify("本機 AI 模型下載失敗(網路問題),請連網後再按一次 ⌘Enter 重試,或改用雲端後端。")
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
