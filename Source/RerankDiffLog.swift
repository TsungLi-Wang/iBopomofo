// Copyright (c) 2026 and onwards The McBopomofo Authors.
//
// Local append-only log of commit-time neural rerank changes (Enter only).
// Privacy: never upload, never bundle, never attach to crash reports.
// Tab preview must NOT call this — only KeyHandler Enter path when text changes.

import Foundation

@objc(RerankDiffLog)
final class RerankDiffLog: NSObject {

    /// Max log file size before rotate (keep one .1 backup).
    private static let maxBytes: UInt64 = 5 * 1024 * 1024

    private static let lock = NSLock()

    /// ~/Library/Application Support/McBopomofo/rerank-diff.log
    @objc static var logFilePath: String {
        logFileURL.path
    }

    private static var logFileURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("iBopomofo", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("rerank-diff.log", isDirectory: false)
    }

    /// Append one line if walk ≠ reranked. No-op when logging disabled or equal.
    /// Format: ISO8601\twalk\treranked\n
    @objc static func appendIfChanged(walk: String, reranked: String) {
        guard Preferences.enableRerankDiffLog else { return }
        guard walk != reranked else { return }
        let stamp = ISO8601DateFormatter().string(from: Date())
        // Escape newlines/tabs in text so one physical line = one event.
        let w = walk.replacingOccurrences(of: "\t", with: " ").replacingOccurrences(of: "\n", with: " ")
        let r = reranked.replacingOccurrences(of: "\t", with: " ").replacingOccurrences(of: "\n", with: " ")
        let line = "\(stamp)\t\(w)\t\(r)\n"
        lock.lock()
        defer { lock.unlock() }
        rotateIfNeededLocked()
        let url = logFileURL
        if let data = line.data(using: .utf8) {
            if FileManager.default.fileExists(atPath: url.path),
                let handle = try? FileHandle(forWritingTo: url)
            {
                defer { try? handle.close() }
                _ = try? handle.seekToEnd()
                try? handle.write(contentsOf: data)
            } else {
                try? data.write(to: url, options: .atomic)
            }
        }
    }

    @objc static func clearLog() {
        lock.lock()
        defer { lock.unlock() }
        let url = logFileURL
        try? FileManager.default.removeItem(at: url)
        let bak = url.appendingPathExtension("1")
        try? FileManager.default.removeItem(at: bak)
    }

    /// Test helper: line count of current log (0 if missing).
    @objc static func lineCountForTesting() -> Int {
        lock.lock()
        defer { lock.unlock() }
        guard let text = try? String(contentsOf: logFileURL, encoding: .utf8), !text.isEmpty
        else {
            return 0
        }
        return text.split(separator: "\n", omittingEmptySubsequences: true).count
    }

    private static func rotateIfNeededLocked() {
        let url = logFileURL
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
            let size = attrs[.size] as? UInt64, size >= maxBytes
        else {
            return
        }
        let bak = url.appendingPathExtension("1")
        try? FileManager.default.removeItem(at: bak)
        try? FileManager.default.moveItem(at: url, to: bak)
    }
}
