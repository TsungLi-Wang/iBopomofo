// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// Tests for the decision census (baton 23) — the denominator that
// manual-correction.log structurally cannot provide.
//
// All fixtures are synthetic. The real log holds the user's own typing and is
// never used as test data. These exercise the pure line builder only: they do
// not touch the filesystem, so they cannot pollute the real census file.

import XCTest

@testable import iBopomofo

final class DecisionCensusLogTests: XCTestCase {

    /// A census line carries counts and nothing else. If this test ever needs
    /// changing to accommodate text, the change is a privacy regression:
    /// the whole point of this log is that it records no content.
    func testLineContainsNoTextOnlyCounts() {
        let line = DecisionCensusLog.line(
            timestamp: "2026-08-19T00:00:00Z", nodeCount: 7, charCount: 9,
            overriddenCount: 2)
        let fields = line.trimmingCharacters(in: .newlines).components(separatedBy: "\t")
        XCTAssertEqual(fields.count, 5)
        XCTAssertEqual(fields[0], DecisionCensusLog.schemaVersion)
        XCTAssertEqual(fields[1], "2026-08-19T00:00:00Z")
        XCTAssertEqual(fields[2], "7")
        XCTAssertEqual(fields[3], "9")
        XCTAssertEqual(fields[4], "2")
        // Every field after the timestamp must parse as an integer — that is
        // the machine-checkable form of "this file has no free text in it".
        for field in fields.dropFirst(2) {
            XCTAssertNotNil(Int(field), "census field must be numeric: \(field)")
        }
    }

    /// One event per line, so a census file can be counted with `wc -l`.
    func testOneEventIsOneLine() {
        let line = DecisionCensusLog.line(
            timestamp: "2026-08-19T00:00:00Z", nodeCount: 3, charCount: 3,
            overriddenCount: 0)
        XCTAssertTrue(line.hasSuffix("\n"))
        XCTAssertEqual(line.components(separatedBy: "\n").count, 2)
    }

    /// The census file must not be confusable with manual-correction.log.
    /// They live in different files, but a mis-pointed analysis tool that reads
    /// both must still be able to tell the formats apart by field count:
    /// census = 5, correction v0/v1/v2 = 4/6/10.
    func testFieldCountDoesNotCollideWithCorrectionLogSchemas() {
        let line = DecisionCensusLog.line(
            timestamp: "2026-08-19T00:00:00Z", nodeCount: 1, charCount: 1,
            overriddenCount: 0)
        let count = line.trimmingCharacters(in: .newlines)
            .components(separatedBy: "\t").count
        XCTAssertEqual(count, 5)
        XCTAssertFalse([4, 6, 10].contains(count),
                       "census must not collide with correction log v0/v1/v2")
    }

    /// The numerator is recorded in the same event as the denominator, so a
    /// correction rate never needs a timestamp join across two files.
    func testOverriddenCountIsCarriedAlongsideNodeCount() {
        let line = DecisionCensusLog.line(
            timestamp: "2026-08-19T00:00:00Z", nodeCount: 10, charCount: 14,
            overriddenCount: 3)
        let fields = line.trimmingCharacters(in: .newlines).components(separatedBy: "\t")
        let nodes = Int(fields[2])!
        let overridden = Int(fields[4])!
        XCTAssertLessThanOrEqual(overridden, nodes,
                                 "numerator can never exceed its own denominator")
        XCTAssertEqual(nodes, 10)
        XCTAssertEqual(overridden, 3)
    }

    /// Zero-override commits are the common case and must still be recorded —
    /// they are exactly the decisions the correction log can never see, and
    /// dropping them would rebuild the correction-only bias this log exists
    /// to remove.
    func testCommitWithNoCorrectionsIsStillARecordedDecision() {
        let line = DecisionCensusLog.line(
            timestamp: "2026-08-19T00:00:00Z", nodeCount: 5, charCount: 6,
            overriddenCount: 0)
        let fields = line.trimmingCharacters(in: .newlines).components(separatedBy: "\t")
        XCTAssertEqual(fields[2], "5")
        XCTAssertEqual(fields[4], "0")
    }
}
