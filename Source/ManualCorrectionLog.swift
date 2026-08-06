// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Manual correction samples: user re-picked after the model path was wrong.
// Highest-value hard forks for later retrain / crowd loop.
// Pure local append-only log under Application Support; never uploaded.
//
// Schema v1 (tab-separated, one event per line):
//   schemaVer \t ISO8601 \t reading \t left_context \t wrong_char \t chosen
// wrong_char may be empty for composing-time picks (no "before" surface).

import Foundation

@objc(ManualCorrectionLog)
final class ManualCorrectionLog: NSObject {
    /// Current line schema version written by append(...).
    @objc static let schemaVersion = "1"

    /// ~/Library/Application Support/McBopomofo/manual-correction.log
    @objc static var logFilePath: String {
        let base = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first!
        .appendingPathComponent("McBopomofo", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("manual-correction.log", isDirectory: false).path
    }

    /// Schema v1: schemaVer \t ISO8601 \t reading \t left_context \t wrong_char \t chosen
    @objc static func append(
        reading: String,
        leftContext: String,
        wrongChar: String,
        chosen: String
    ) {
        guard Preferences.enableManualCorrectionLog else { return }
        guard !reading.isEmpty, !chosen.isEmpty else { return }
        let esc: (String) -> String = {
            $0.replacingOccurrences(of: "\t", with: " ")
                .replacingOccurrences(of: "\n", with: " ")
        }
        let ts = ISO8601DateFormatter().string(from: Date())
        let line =
            "\(schemaVersion)\t\(ts)\t\(esc(reading))\t\(esc(leftContext))\t\(esc(wrongChar))\t\(esc(chosen))\n"
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
