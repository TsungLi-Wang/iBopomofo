// Copyright (c) 2026 and onwards The McBopomofo Authors.
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

/// 處理 macOS 下載隔離（quarantine）。未公證的發佈包若保留此屬性，
/// 內嵌 `llama-server` 會被 Gatekeeper 直接 SIGKILL。
enum QuarantineHelper {
    private static let attributeName = "com.apple.quarantine"

    static func hasQuarantineAttribute(at path: String) -> Bool {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
        process.arguments = ["-p", attributeName, path]
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return false
        }
        guard process.terminationStatus == 0 else { return false }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        return !data.isEmpty
    }

    @discardableResult
    static func stripQuarantine(at path: String) -> Bool {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
        process.arguments = ["-dr", attributeName, path]
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            process.waitUntilExit()
            return process.terminationStatus == 0
        } catch {
            NSLog("QuarantineHelper: 無法清除 quarantine — \(error.localizedDescription)")
            return false
        }
    }

    /// 若主 bundle 仍帶 quarantine，嘗試自動清除（拖曳安裝時免跑終端機）。
    @discardableResult
    static func stripQuarantineOnMainBundleIfNeeded() -> Bool {
        let path = Bundle.main.bundlePath
        guard hasQuarantineAttribute(at: path) else { return false }
        let ok = stripQuarantine(at: path)
        if ok {
            NSLog("QuarantineHelper: 已自動清除主 bundle 的 quarantine")
        } else {
            NSLog("QuarantineHelper: 主 bundle 仍帶 quarantine，本機 AI 可能無法啟動")
        }
        return ok
    }
}