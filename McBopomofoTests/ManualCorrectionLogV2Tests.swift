// Copyright (c) 2026 and onwards The iBopomofo Authors.
//
// 棒⑲ instrumentation 的確定性測試。
//
// 全部使用人工構造的 fixture —— **不得**把真實使用者輸入放進 repo。
// 測的是純函式 `v2Line` 與 `classify`，不碰真實 log 檔
// （那個檔是使用者自己的打字內容）。

import XCTest

@testable import iBopomofo

final class ManualCorrectionLogV2Tests: XCTestCase {

    private func fields(_ line: String) -> [String] {
        XCTAssertTrue(line.hasSuffix("\n"), "每個事件必須是完整一行")
        return String(line.dropLast()).components(separatedBy: "\t")
    }

    private func line(
        reading: String = "ㄗㄨㄛˋ",
        leftContext: String = "ctx",
        engine: String,
        user: String,
        source: String = ManualCorrectionLog.sourceComposing,
        candidates: [String] = [],
        count: Int = -1
    ) -> [String] {
        fields(
            ManualCorrectionLog.v2Line(
                timestamp: "2026-08-18T00:00:00Z",
                reading: reading, leftContext: leftContext,
                engineChoice: engine, userChoice: user,
                eventType: ManualCorrectionLog.classify(
                    engineChoice: engine, userChoice: user),
                source: source, candidateValues: candidates,
                candidateCount: count))
    }

    // Gate 2 — 真正的修正必須留下引擎原本的選擇，而不是使用者的選擇。
    func testTrueCorrectionKeepsEngineChoice() {
        let f = line(engine: "作", user: "做", candidates: ["作", "做", "坐"], count: 3)
        XCTAssertEqual(f[0], "2", "schema version")
        XCTAssertEqual(f[2], "ㄗㄨㄛˋ")
        XCTAssertEqual(f[4], "作", "engine_choice 必須是引擎原本選的")
        XCTAssertEqual(f[5], "做", "user_choice")
        XCTAssertEqual(f[6], ManualCorrectionLog.eventTrueCorrection)
        XCTAssertNotEqual(f[4], f[5], "engine 與 user 不同才叫 correction")
    }

    // Gate 3 — 重選同一個字不是引擎錯誤。
    func testNoopReselectIsNotAnError() {
        let f = line(engine: "做", user: "做")
        XCTAssertEqual(f[6], ManualCorrectionLog.eventNoopReselect)
        XCTAssertNotEqual(
            f[6], ManualCorrectionLog.eventTrueCorrection,
            "noop 不得被算成 error")
    }

    // 引擎原本選什麼不可得時，必須誠實標 UNKNOWN，不得拿 user_choice 頂替。
    func testUnknownOriginalIsNeverGuessed() {
        let f = line(engine: "", user: "做")
        XCTAssertEqual(f[6], ManualCorrectionLog.eventUnknownOriginal)
        XCTAssertEqual(f[4], "", "engine_choice 不可得就留空")
        XCTAssertNotEqual(f[4], f[5], "不得用 user_choice 當 engine_choice")
    }

    // Gate 4 — 候選集要能回答「使用者選的字在不在候選裡」。
    func testCandidateSetIsRecoverable() {
        let f = line(engine: "作", user: "做", candidates: ["作", "做", "坐"], count: 3)
        XCTAssertEqual(f[8], "3", "candidate_count")
        let values = f[9].components(separatedBy: "|")
        XCTAssertEqual(values, ["作", "做", "坐"])
        XCTAssertTrue(values.contains(f[5]), "user_choice 應在候選集內")
        XCTAssertTrue(values.contains(f[4]), "engine_choice 應在候選集內")
    }

    // 候選不可得時必須明確標示，而不是寫成空候選集混淆。
    func testCandidateUnavailableIsExplicit() {
        let f = line(
            engine: "作", user: "做",
            source: ManualCorrectionLog.sourceReselect, candidates: [], count: -1)
        XCTAssertEqual(f[7], ManualCorrectionLog.sourceReselect)
        XCTAssertEqual(f[8], "-1", "-1 = 明確不可得")
        XCTAssertEqual(f[9], "")
    }

    // 候選過多時截斷，但截斷本身必須看得出來。
    func testCandidateTruncationStaysVisible() {
        let many = (0..<40).map { "字\($0)" }
        let f = line(engine: "作", user: "做", candidates: many, count: many.count)
        let listed = f[9].components(separatedBy: "|")
        XCTAssertEqual(listed.count, ManualCorrectionLog.maxLoggedCandidates)
        XCTAssertEqual(f[8], "40")
        XCTAssertGreaterThan(
            Int(f[8])!, listed.count, "count 大於列出數 = 有截斷，可被下游偵測")
    }

    // 多音節讀音（詞級修正）。
    func testMultiSyllableReading() {
        let f = line(reading: "ㄗㄨㄛˋ-ㄆㄧㄣˇ", engine: "作品", user: "做品")
        XCTAssertEqual(f[2], "ㄗㄨㄛˋ-ㄆㄧㄣˇ")
        XCTAssertEqual(f[2].components(separatedBy: "-").count, 2)
        XCTAssertEqual(f[6], ManualCorrectionLog.eventTrueCorrection)
    }

    // 一個事件永遠是一行：分隔字元必須被轉義掉。
    func testSeparatorsAreEscapedSoOneEventIsOneLine() {
        let f = line(
            leftContext: "a\tb\nc|d", engine: "作", user: "做",
            candidates: ["x|y"], count: 1)
        XCTAssertEqual(f.count, 10, "欄位數必須固定")
        XCTAssertFalse(f[3].contains("\t"))
        XCTAssertFalse(f[3].contains("\n"))
        XCTAssertFalse(f[3].contains("|"))
        XCTAssertEqual(f[9], "x y", "候選值裡的 | 必須轉義，否則會被誤切")
    }

    // 空讀音 / 空使用者選擇一律不寫入（append 的守門條件）。
    func testEmptyReadingOrChoiceIsRejectedByClassifierContract() {
        XCTAssertEqual(
            ManualCorrectionLog.classify(engineChoice: "", userChoice: ""),
            ManualCorrectionLog.eventUnknownOriginal)
    }

    // Gate 5 — 新 schema 不得與舊格式撞欄位數，否則 parser 無法分辨。
    func testSchemaVersionsAreDistinguishable() {
        let v2 = line(engine: "作", user: "做")
        XCTAssertEqual(v2.count, 10, "v2 = 10 欄")
        XCTAssertNotEqual(v2.count, 6, "v1 = 6 欄")
        XCTAssertNotEqual(v2.count, 4, "v0 = 4 欄")
        XCTAssertEqual(v2[0], ManualCorrectionLog.schemaVersionV2)
        XCTAssertNotEqual(
            ManualCorrectionLog.schemaVersionV2, ManualCorrectionLog.schemaVersion)
    }

    // v2 的前 6 欄與 v1 的語意對齊（engine_choice 對應 v1 的 wrong_char）。
    func testV2IsSupersetOfV1Layout() {
        let f = line(engine: "作", user: "做")
        XCTAssertEqual(f[4], "作", "第 5 欄 = v1 的 wrong_char 位置")
        XCTAssertEqual(f[5], "做", "第 6 欄 = v1 的 chosen 位置")
    }
}
