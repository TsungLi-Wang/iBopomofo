// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Manual correction samples: user re-picked after the model path was wrong.
// Highest-value hard forks for later retrain / crowd loop.
// Pure local append-only log under Application Support; never uploaded.
//
// Schema v1 (tab-separated, one event per line):
//   schemaVer \t ISO8601 \t reading \t left_context \t wrong_char \t chosen
// wrong_char may be empty for composing-time picks (no "before" surface).
//
// Schema v2 (baton 19) — strict superset of v1's column layout, so a v1 parser
// reading the first 6 columns still gets the same meaning:
//   schemaVer \t ISO8601 \t reading \t left_context \t engine_choice \t
//   user_choice \t event_type \t source \t candidate_count \t candidate_values
//
// Why v2 exists: baton 18 found that 95.2% of logged events came from the
// composing path, which wrote an EMPTY wrong_char — so "what did the engine
// originally pick" was unrecoverable, and only 15 of 584 events were usable.
// v2 captures the engine's own choice at decision time (never reconstructed
// afterwards, never inferred from gold).
//
//   engine_choice     what the engine had chosen before the user acted.
//                     Empty ONLY when genuinely unavailable.
//   event_type        TRUE_CORRECTION  engine_choice != user_choice
//                     NOOP_RESELECT    user re-picked the same value
//                     UNKNOWN_ORIGINAL engine_choice unavailable — never guessed
//   source            composing | reselect
//   candidate_count   size of the candidate set the engine offered,
//                     or -1 when unavailable. May exceed the listed values.
//   candidate_values  up to kMaxLoggedCandidates values, "|"-joined.
//                     Empty when unavailable. Truncation is visible by
//                     comparing candidate_count with the number listed.
//
// Data minimization: v2 adds no new free text. It records values that are
// already candidates of a single reading, plus two enum-like fields.
// No sentences beyond the pre-existing left_context field, no identifiers,
// no network. Writing stays best-effort: a failed write must never affect input.

import Foundation

@objc(ManualCorrectionLog)
final class ManualCorrectionLog: NSObject {
    /// Legacy line schema version written by append(...). Kept for compatibility.
    @objc static let schemaVersion = "1"

    /// Line schema version written by appendV2(...). Current writer.
    @objc static let schemaVersionV2 = "2"

    /// Upper bound on how many candidate values a single line may carry.
    /// Keeps lines bounded; truncation stays visible via candidateCount.
    @objc static let maxLoggedCandidates = 16

    @objc static let eventTrueCorrection = "TRUE_CORRECTION"
    @objc static let eventNoopReselect = "NOOP_RESELECT"
    @objc static let eventUnknownOriginal = "UNKNOWN_ORIGINAL"
    @objc static let sourceComposing = "composing"
    @objc static let sourceReselect = "reselect"

    /// ~/Library/Application Support/iBopomofo/manual-correction.log
    @objc static var logFilePath: String {
        let base = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first!
        .appendingPathComponent("iBopomofo", isDirectory: true)
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("manual-correction.log", isDirectory: false).path
    }

    /// Schema v1: schemaVer \t ISO8601 \t reading \t left_context \t wrong_char \t chosen

    /// The XCTest host sets this. Unit tests drive the real KeyHandler commit
    /// path, so without this guard a test run appends fabricated events to the
    /// developer's own log — which is precisely the data this instrumentation
    /// exists to make trustworthy. Same guard as the user override cache
    /// (`LTIsRunningUnitTests` in LanguageModelManager.mm); see dead-ends.md A
    /// for the earlier round of this exact bug polluting the UOM file.
    private static var isRunningUnitTests: Bool {
        ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
    }

    @objc static func append(
        reading: String,
        leftContext: String,
        wrongChar: String,
        chosen: String
    ) {
        guard !isRunningUnitTests else { return }
        guard Preferences.enableManualCorrectionLog else { return }
        guard !reading.isEmpty, !chosen.isEmpty else { return }
        let esc: (String) -> String = {
            $0.replacingOccurrences(of: "\t", with: " ")
                .replacingOccurrences(of: "\n", with: " ")
        }
        let ts = ISO8601DateFormatter().string(from: Date())
        let line =
            "\(schemaVersion)\t\(ts)\t\(esc(reading))\t\(esc(leftContext))\t\(esc(wrongChar))\t\(esc(chosen))\n"
        write(line)
    }

    /// Schema v2. `engineChoice` must come from the engine's own state at
    /// decision time — never reconstructed from the post-correction surface and
    /// never inferred from a known-good answer. Pass "" when truly unavailable;
    /// this method then records UNKNOWN_ORIGINAL rather than guessing.
    ///
    /// `candidateValues` empty + `candidateCount` -1 means "not available here".
    ///
    /// Best-effort: any failure returns silently. Callers must not depend on it.
    @objc static func appendV2(
        reading: String,
        leftContext: String,
        engineChoice: String,
        userChoice: String,
        source: String,
        candidateValues: [String],
        candidateCount: Int
    ) {
        guard !isRunningUnitTests else { return }
        guard Preferences.enableManualCorrectionLog else { return }
        guard !reading.isEmpty, !userChoice.isEmpty else { return }
        let eventType = classify(engineChoice: engineChoice, userChoice: userChoice)
        let ts = ISO8601DateFormatter().string(from: Date())
        write(v2Line(timestamp: ts, reading: reading, leftContext: leftContext,
                     engineChoice: engineChoice, userChoice: userChoice,
                     eventType: eventType, source: source,
                     candidateValues: candidateValues,
                     candidateCount: candidateCount))
    }

    /// Pure line builder for schema v2 — no clock, no filesystem, no state.
    /// Exists so the format has deterministic tests without touching the real
    /// log file (which holds the user's own typing and must not be a fixture).
    @objc static func v2Line(
        timestamp: String,
        reading: String,
        leftContext: String,
        engineChoice: String,
        userChoice: String,
        eventType: String,
        source: String,
        candidateValues: [String],
        candidateCount: Int
    ) -> String {
        let esc: (String) -> String = {
            $0.replacingOccurrences(of: "\t", with: " ")
                .replacingOccurrences(of: "\n", with: " ")
                .replacingOccurrences(of: "|", with: " ")
        }
        let bounded = candidateValues.prefix(maxLoggedCandidates).map(esc)
        return [
            schemaVersionV2, timestamp, esc(reading), esc(leftContext),
            esc(engineChoice), esc(userChoice), eventType, esc(source),
            String(candidateCount), bounded.joined(separator: "|"),
        ].joined(separator: "\t") + "\n"
    }

    /// Classify an event from the engine's own choice. Pure; used by both the
    /// writer and the tests. Never guesses: empty engineChoice stays UNKNOWN.
    @objc static func classify(engineChoice: String, userChoice: String) -> String {
        if engineChoice.isEmpty { return eventUnknownOriginal }
        return engineChoice == userChoice ? eventNoopReselect : eventTrueCorrection
    }

    /// Shared best-effort writer. Fail-open by construction: every failure path
    /// returns silently, so a broken log can never affect typing.
    ///
    /// Uses the throwing `write(contentsOf:)` / `seekToEnd()` rather than the
    /// legacy `write(_:)` / `seekToEndOfFile()`: the legacy pair raises an
    /// ObjC exception on write failure (disk full, revoked permission), which
    /// Swift cannot catch — that would crash the input method because of a
    /// diagnostic log. The throwing API turns the same failure into a caught
    /// error we drop.
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
            return  // fail-open: a dropped log line must never surface to the user
        }
    }

    @objc static func clearLog() {
        let path = logFilePath
        try? FileManager.default.removeItem(atPath: path)
        FileManager.default.createFile(atPath: path, contents: nil)
    }
}
