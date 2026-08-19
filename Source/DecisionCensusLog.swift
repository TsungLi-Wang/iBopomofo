// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Decision census: the DENOMINATOR that manual-correction.log structurally
// cannot provide.
//
// Why this file exists (baton 23):
//   ManualCorrectionLog only writes when the user *corrects* something. That
//   makes it a numerator with no denominator: baton 18 measured that accuracy
//   is NOT COMPUTABLE from it, and baton 22-B established the stronger result
//   that correction-only data is a missing-not-at-random sample — you cannot
//   recover the decision population from it after the fact, at any sample size.
//
//   So we count the decisions themselves. One line per hard commit:
//
//     schemaVer \t ISO8601 \t n_nodes \t n_chars \t n_overridden
//
//   n_nodes        how many walk nodes the engine committed. Each node is one
//                  engine decision (it chose a value for that reading span).
//   n_chars        how many characters those nodes produced.
//   n_overridden   how many of those nodes carried a user override, i.e. the
//                  numerator, counted in the *same* population and the *same*
//                  event as the denominator. Recording both here means the
//                  correction rate needs no timestamp join against the other
//                  log — a join that would silently drop events.
//
// Data minimization: this file records NO TEXT AT ALL. Three integers and a
// timestamp. It is strictly less than what manual-correction.log already
// collects. No readings, no characters, no context, no identifiers, no
// network. Same on/off switch as the correction log.
//
// Cost: the counting loop walks nodes we are already holding, at commit time
// only (never per keystroke). It does NOT call candidatesAt() — resolving the
// candidate set per node would add an O(n) lattice lookup to the commit path,
// and node ambiguity can be recovered offline from the correction log's
// candidate_count instead.
//
// Best-effort, like the correction log: a failed write must never affect
// typing.

import Foundation

@objc(DecisionCensusLog)
final class DecisionCensusLog: NSObject {
    /// Line schema version. Independent of ManualCorrectionLog's versions —
    /// this is a different file with a different meaning.
    @objc static let schemaVersion = "1"

    /// ~/Library/Application Support/iBopomofo/decision-census.log
    @objc static var logFilePath: String {
        let base = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first!
        .appendingPathComponent("iBopomofo", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("decision-census.log", isDirectory: false).path
    }

    /// Record one committed composing buffer.
    ///
    /// `nodeCount` is the denominator contribution; `overriddenCount` is the
    /// numerator contribution from the same commit. A commit with no nodes is
    /// not a decision and is not recorded — counting it would inflate the
    /// denominator with punctuation-only and empty commits.
    ///
    /// Best-effort: any failure returns silently.
    @objc static func append(nodeCount: Int, charCount: Int, overriddenCount: Int) {
        guard Preferences.enableManualCorrectionLog else { return }
        guard nodeCount > 0 else { return }
        let ts = ISO8601DateFormatter().string(from: Date())
        write(line(timestamp: ts, nodeCount: nodeCount, charCount: charCount,
                   overriddenCount: overriddenCount))
    }

    /// Pure line builder — no clock, no filesystem, no state. Exists so the
    /// format is testable without touching the real log file.
    @objc static func line(
        timestamp: String, nodeCount: Int, charCount: Int, overriddenCount: Int
    ) -> String {
        return [
            schemaVersion, timestamp, String(nodeCount), String(charCount),
            String(overriddenCount),
        ].joined(separator: "\t") + "\n"
    }

    /// Shared best-effort writer. Fail-open by construction: every failure path
    /// returns silently. Uses the throwing `seekToEnd()` / `write(contentsOf:)`
    /// rather than the legacy pair, which raises an uncatchable ObjC exception
    /// on write failure — see ManualCorrectionLog for the same reasoning.
    private static func write(_ line: String) {
        guard let data = line.data(using: .utf8) else { return }
        let path = logFilePath
        if !FileManager.default.fileExists(atPath: path) {
            FileManager.default.createFile(atPath: path, contents: nil)
        }
        guard let handle = FileHandle(forWritingAtPath: path) else { return }
        defer { try? handle.close() }
        do {
            try handle.seekToEnd()
            try handle.write(contentsOf: data)
        } catch {
            return  // fail-open: a dropped census line must never surface
        }
    }

    @objc static func clearLog() {
        let path = logFilePath
        try? FileManager.default.removeItem(atPath: path)
        FileManager.default.createFile(atPath: path, contents: nil)
    }
}
