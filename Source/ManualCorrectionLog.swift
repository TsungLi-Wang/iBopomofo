// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Manual correction samples: user re-picked a candidate after the model path
// was wrong. These are the highest-value hard forks for later retrain.
// Pure local append-only log under Application Support; never uploaded.

import Foundation

@objc(ManualCorrectionLog)
final class ManualCorrectionLog: NSObject {
    /// ~/Library/Application Support/McBopomofo/manual-correction.log
    @objc static var logFilePath: String {
        let base = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first!
        .appendingPathComponent("McBopomofo", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("manual-correction.log", isDirectory: false).path
    }

    /// One line: ISO8601\treading\tcontext\tchosen\n
    @objc static func append(reading: String, context: String, chosen: String) {
        guard Preferences.enableManualCorrectionLog else { return }
        guard !reading.isEmpty, !chosen.isEmpty else { return }
        let esc: (String) -> String = {
            $0.replacingOccurrences(of: "\t", with: " ")
                .replacingOccurrences(of: "\n", with: " ")
        }
        let ts = ISO8601DateFormatter().string(from: Date())
        let line = "\(ts)\t\(esc(reading))\t\(esc(context))\t\(esc(chosen))\n"
        let path = logFilePath
        if !FileManager.default.fileExists(atPath: path) {
            FileManager.default.createFile(atPath: path, contents: nil)
        }
        guard let handle = FileHandle(forWritingAtPath: path) else { return }
        defer { try? handle.close() }
        handle.seekToEndOfFile()
        if let data = line.data(using: .utf8) {
            handle.write(data)
        }
    }

    @objc static func clearLog() {
        let path = logFilePath
        try? FileManager.default.removeItem(atPath: path)
        FileManager.default.createFile(atPath: path, contents: nil)
    }
}
