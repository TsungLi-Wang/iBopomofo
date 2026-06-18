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

// MARK: - 本機 AI 推理伺服器管理(內嵌 llama-server)
//
// 仿 azooKey 的 ConverterServer:把 llama.cpp 的 `llama-server`(OpenAI 相容 HTTP)
// 連同精簡 dylib 與量化模型一起打包進 app(Contents/Resources/llama/),
// app 啟動時自動 spawn、結束時 kill。使用者裝 app 就能離線用本機 AI 修正,
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

    private override init() { super.init() }

    // MARK: bundle 內 runtime 路徑

    /// Contents/Resources/llama/bin/llama-server(dylib 與它同層,靠 @loader_path 載入)。
    private var serverBinaryURL: URL? {
        Bundle.main.url(forResource: "llama-server", withExtension: nil, subdirectory: "llama/bin")
    }

    /// Contents/Resources/llama/models/model.gguf(打包的量化模型)。
    private var modelURL: URL? {
        Bundle.main.url(forResource: "model", withExtension: "gguf", subdirectory: "llama/models")
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
        guard let bin = serverBinaryURL, let model = modelURL else {
            NSLog("LlamaServer: 找不到 bundle 內的 llama-server 或模型,本機後端不可用")
            return
        }

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
