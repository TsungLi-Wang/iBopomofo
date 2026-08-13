// Commit-contract golden suite (棒⑤).
//
// Product invariant (v2.13.0+): 定案 ≠ 送出
//   - 定案 (hard commit): text → host, underline gone; key is consumed
//   - 送出: host action (search / chat send) via another Enter after 定案
//
// Matrix covered (see case IDs in method names):
//   trigger: pause-API / Enter / period / comma
//   underline: composing (有底線) / Empty (無底線)
//   caret: readable document / unreadable (NSNotFound)
//
// Mutation checks prove each assertion turns RED when the corresponding
// product logic is broken. 逐案破壞方式與紅/綠結果記在
// ~/ai-handoff/20260812-baton5-report.md（棒⑤ §Mutation check）。
// 目前沒有自動化的 mutation 腳本 —— 是手動逐案做的。要重跑就照報告那張表。
//
// 另一條相關契約「使用者手選 > 規則」不在本檔，而由 C++ 的
// ParticleRuleDisambiguatorTest.RescoreWalkNeverOverridesUserChoice 守著
// （2026-08-12 統治局實測：拿掉護欄該測試會紅）。

import XCTest

@testable import iBopomofo

final class CommitContractGoldenTests: XCTestCase {

    var handler = KeyHandler()
    var savedKeyboardLayout: KeyboardLayout = .standard
    var savedAssociated = false
    var savedPeriod = false
    var savedComma = false
    var savedNeural = false
    var savedHalfWidth = false
    var savedContextual = false

    override func setUpWithError() throws {
        savedKeyboardLayout = Preferences.keyboardLayout
        savedAssociated = Preferences.associatedPhrasesEnabled
        savedPeriod = Preferences.sentenceEndTriggerPeriod
        savedComma = Preferences.sentenceEndTriggerComma
        savedNeural = Preferences.enableNeuralPathRerank
        savedHalfWidth = Preferences.halfWidthPunctuationEnabled
        savedContextual = Preferences.enableContextualWalk

        Preferences.keyboardLayout = .standard
        Preferences.associatedPhrasesEnabled = false
        Preferences.halfWidthPunctuationEnabled = false
        Preferences.sentenceEndTriggerPeriod = false
        Preferences.sentenceEndTriggerComma = false
        LanguageModelManager.loadDataModels()
        // G17/G18 hand-pick candidates[1] (often 妳好 for su3cl3). Clear so
        // soft DP does not leak into later cases or KeyHandlerBopomofoTests.
        LanguageModelManager.clearUserOverrideModelForTesting()
        remakeHandler()
    }

    override func tearDownWithError() throws {
        LanguageModelManager.clearUserOverrideModelForTesting()
        Preferences.keyboardLayout = savedKeyboardLayout
        Preferences.associatedPhrasesEnabled = savedAssociated
        Preferences.sentenceEndTriggerPeriod = savedPeriod
        Preferences.sentenceEndTriggerComma = savedComma
        Preferences.enableNeuralPathRerank = savedNeural
        Preferences.halfWidthPunctuationEnabled = savedHalfWidth
        Preferences.enableContextualWalk = savedContextual
    }

    private func remakeHandler() {
        handler = KeyHandler()
        handler.inputMode = .bopomofo
    }

    // MARK: - Helpers

    private func charCode(_ string: String) -> UInt16 {
        let scalars = string.unicodeScalars
        return UInt16(scalars[scalars.startIndex].value)
    }

    /// Type standard-layout keys into composing state. Returns final state.
    @discardableResult
    private func typeKeys(_ keys: String, state: inout InputState) -> InputState {
        var current = state
        for key in keys.map({ String($0) }) {
            let input = KeyHandlerInput(
                inputText: key, keyCode: 0, charCode: charCode(key), flags: [],
                isVerticalMode: false)
            handler.handle(input: input, state: current) { newState in
                current = newState
            } errorCallback: {}
        }
        state = current
        return current
    }

    /// Enter key while composing → 定案 path.
    private func enterKey() -> KeyHandlerInput {
        KeyHandlerInput(
            inputText: " ", keyCode: KeyCode.enter.rawValue, charCode: 13, flags: [],
            isVerticalMode: false)
    }

    /// Shift+. → fullwidth period reading under Standard layout.
    private func shiftPeriod() -> KeyHandlerInput {
        KeyHandlerInput(
            inputText: ">", keyCode: 0, charCode: charCode(">"), flags: .shift,
            isVerticalMode: false)
    }

    /// Shift+, → fullwidth comma reading under Standard layout.
    private func shiftComma() -> KeyHandlerInput {
        KeyHandlerInput(
            inputText: "<", keyCode: 0, charCode: charCode("<"), flags: .shift,
            isVerticalMode: false)
    }

    private func downKey() -> KeyHandlerInput {
        KeyHandlerInput(
            inputText: " ", keyCode: KeyCode.down.rawValue, charCode: 0, flags: [],
            isVerticalMode: false)
    }

    /// Type 你好 readings (su3cl3). Surface may be 你好 or 妳好 etc. if UOM/rules
    /// already have evidence from earlier tests — callers must use returned `text`.
    private func composeNihao() -> (state: InputState, text: String) {
        var state: InputState = InputState.Empty()
        typeKeys("su3cl3", state: &state)
        let text = (state as? InputState.Inputting)?.composingBuffer ?? ""
        return (state, text)
    }

    private struct CommitTrace {
        var handled: Bool = false
        var states: [InputState] = []
        var committingTexts: [String] {
            states.compactMap { ($0 as? InputState.Committing)?.poppedText }
        }
        var sawCommitting: Bool { states.contains { $0 is InputState.Committing } }
        var sawEmpty: Bool { states.contains { $0 is InputState.Empty } }
        var final: InputState? { states.last }
    }

    private func handle(_ input: KeyHandlerInput, state: InputState) -> CommitTrace {
        var trace = CommitTrace()
        var current = state
        trace.handled = handler.handle(input: input, state: current) { newState in
            trace.states.append(newState)
            current = newState
        } errorCallback: {}
        return trace
    }

    // =========================================================================
    // G01–G04  定案 ≠ 送出（Enter / Empty）
    // =========================================================================

    /// G01: Enter while underlined (Inputting) → Committing + Empty; handled=true (consumed).
    func testG01_enterWhileComposing_isCommitNotSend() {
        let (state, text) = composeNihao()
        XCTAssertTrue(state is InputState.Inputting, "pre: composing")
        XCTAssertFalse(text.isEmpty, "pre: composing buffer non-empty")

        let trace = handle(enterKey(), state: state)
        XCTAssertTrue(trace.handled, "G01: Enter while composing must be consumed (not 送出)")
        XCTAssertTrue(trace.sawCommitting, "G01: must emit Committing (字進 host)")
        XCTAssertEqual(trace.committingTexts.first, text)
        XCTAssertTrue(trace.sawEmpty, "G01: must end Empty (底線收掉)")
    }

    /// G02: Enter on Empty (already 定案) → handled=false (pass to host = 送出).
    func testG02_enterOnEmpty_isSendPassThrough() {
        let empty: InputState = InputState.Empty()
        let trace = handle(enterKey(), state: empty)
        XCTAssertFalse(trace.handled, "G02: Enter on Empty must pass through (送出)")
        XCTAssertFalse(trace.sawCommitting, "G02: must not re-commit")
    }

    /// G03: After Enter 定案, second Enter on resulting Empty is still pass-through.
    func testG03_secondEnterAfterCommit_isSend() {
        let (state, _) = composeNihao()
        let first = handle(enterKey(), state: state)
        XCTAssertTrue(first.handled)
        XCTAssertTrue(first.sawEmpty)

        let after = first.final ?? InputState.Empty()
        // Handler is clear after hard commit; state is Empty.
        let second = handle(enterKey(), state: after is InputState.Empty ? after : InputState.Empty())
        XCTAssertFalse(second.handled, "G03: second Enter is 送出, not another 定案")
    }

    /// G04: hardCommitSentence API matches Enter-commit text (pause path shares this API).
    func testG04_pauseAPI_sameTextAsEnter() {
        // Path A: Enter
        remakeHandler()
        let (stateA, textA) = composeNihao()
        XCTAssertFalse(textA.isEmpty)
        let enterTrace = handle(enterKey(), state: stateA)
        let enterText = enterTrace.committingTexts.first

        // Path B: hardCommitSentence (what pause timer calls)
        remakeHandler()
        let (stateB, textB) = composeNihao()
        XCTAssertEqual(textB, textA, "G04: same readings → same compose under same prefs")
        var pauseTexts: [String] = []
        var sawEmpty = false
        let ok = handler.hardCommitSentence(state: stateB) { newState in
            if let c = newState as? InputState.Committing {
                pauseTexts.append(c.poppedText)
            }
            if newState is InputState.Empty { sawEmpty = true }
        } errorCallback: {}
        XCTAssertTrue(ok, "G04: hardCommit must succeed on Inputting")
        XCTAssertEqual(pauseTexts.first, enterText, "G04: pause API text == Enter text")
        XCTAssertEqual(pauseTexts.first, textA)
        XCTAssertTrue(sawEmpty)
    }

    // =========================================================================
    // G05–G10  句號 / 逗號 觸發定案
    // =========================================================================

    /// G05: period trigger ON → Shift+. 定案 with text including 。
    func testG05_periodTriggerOn_commitsWithPeriod() {
        Preferences.sentenceEndTriggerPeriod = true
        remakeHandler()
        var state: InputState = InputState.Empty()
        typeKeys("su3cl3", state: &state)
        let stem = (state as? InputState.Inputting)?.composingBuffer ?? ""
        let trace = handle(shiftPeriod(), state: state)
        XCTAssertTrue(trace.handled)
        XCTAssertTrue(trace.sawCommitting, "G05: period 定案 must Commit")
        let text = trace.committingTexts.first ?? ""
        XCTAssertTrue(text.hasPrefix(stem), "G05: got \(text) stem \(stem)")
        XCTAssertTrue(text.contains("。"), "G05: period included in committed text: \(text)")
        XCTAssertTrue(trace.sawEmpty)
    }

    /// G06: period trigger OFF → stay Inputting with 。 (no 定案).
    func testG06_periodTriggerOff_staysComposing() {
        Preferences.sentenceEndTriggerPeriod = false
        remakeHandler()
        var state: InputState = InputState.Empty()
        typeKeys("su3cl3", state: &state)
        let trace = handle(shiftPeriod(), state: state)
        XCTAssertTrue(trace.handled)
        XCTAssertFalse(trace.sawCommitting, "G06: must NOT 定案 when period trigger off")
        let final = trace.final
        XCTAssertTrue(final is InputState.Inputting, "G06: stay composing")
        let buf = (final as? InputState.Inputting)?.composingBuffer ?? ""
        XCTAssertTrue(buf.contains("。"), "G06: period inserted into buffer: \(buf)")
    }

    /// G07: comma trigger ON → Shift+, 定案 with ，
    func testG07_commaTriggerOn_commitsWithComma() {
        Preferences.sentenceEndTriggerComma = true
        remakeHandler()
        var state: InputState = InputState.Empty()
        typeKeys("su3cl3", state: &state)
        let stem = (state as? InputState.Inputting)?.composingBuffer ?? ""
        let trace = handle(shiftComma(), state: state)
        XCTAssertTrue(trace.handled)
        XCTAssertTrue(trace.sawCommitting, "G07: comma 定案")
        let text = trace.committingTexts.first ?? ""
        XCTAssertTrue(text.hasPrefix(stem), "G07: \(text) stem \(stem)")
        XCTAssertTrue(text.contains("，"), "G07: \(text)")
        XCTAssertTrue(trace.sawEmpty)
    }

    /// G08: comma trigger OFF → stay Inputting with ，
    func testG08_commaTriggerOff_staysComposing() {
        Preferences.sentenceEndTriggerComma = false
        remakeHandler()
        var state: InputState = InputState.Empty()
        typeKeys("su3cl3", state: &state)
        let trace = handle(shiftComma(), state: state)
        XCTAssertTrue(trace.handled)
        XCTAssertFalse(trace.sawCommitting)
        let buf = (trace.final as? InputState.Inputting)?.composingBuffer ?? ""
        XCTAssertTrue(buf.contains("，"), "G08: \(buf)")
    }

    /// G09: Enter 定案 text without punct == hardCommit text (period path with same keys minus punct).
    func testG09_enterAndHardCommit_identicalBuffer() {
        remakeHandler()
        let (s1, t1) = composeNihao()
        let e = handle(enterKey(), state: s1)
        remakeHandler()
        let (s2, t2) = composeNihao()
        var hard = ""
        _ = handler.hardCommitSentence(state: s2) { st in
            if let c = st as? InputState.Committing { hard = c.poppedText }
        } errorCallback: {}
        XCTAssertEqual(t1, t2)
        XCTAssertEqual(e.committingTexts.first, hard)
        XCTAssertEqual(hard, t1)
        XCTAssertFalse(hard.isEmpty)
    }

    /// G10: period-ON 定案 is still 定案 only — subsequent Enter on Empty is 送出.
    func testG10_afterPeriodCommit_enterIsSend() {
        Preferences.sentenceEndTriggerPeriod = true
        remakeHandler()
        var state: InputState = InputState.Empty()
        typeKeys("su3cl3", state: &state)
        let c = handle(shiftPeriod(), state: state)
        XCTAssertTrue(c.sawEmpty)
        let second = handle(enterKey(), state: InputState.Empty())
        XCTAssertFalse(second.handled, "G10: after period 定案, Enter is 送出")
    }

    // =========================================================================
    // G11–G16  Post-commit reselect 1→1 + caret readability
    // =========================================================================

    /// G11: readable caret → caretLocation returns index.
    func testG11_caretReadable_returnsLocation() {
        let doc = PostCommitStringDocument(text: "你好世界", caret: 2)
        let loc = PostCommitReselect.caretLocation(client: doc)
        XCTAssertEqual(loc, 2, "G11")
    }

    /// G12: unreadable caret (NSNotFound) → nil (LINE/Telegram degrade path).
    func testG12_caretUnreadable_returnsNil() {
        let doc = UnreadableCaretDocument(text: "你好")
        let loc = PostCommitReselect.caretLocation(client: doc)
        XCTAssertNil(loc, "G12: unreadable selectedRange must yield nil")
    }

    /// G13: 1→1 replace succeeds on readable document (atomic path).
    func testG13_replace1to1_readable_succeeds() {
        let doc = PostCommitStringDocument(text: "你好世界", caret: 1)
        let range = NSRange(location: 1, length: 1)  // 好
        let outcome = PostCommitReselect.replacePendingCharacter(
            client: doc, documentRange: range, oldChar: "好", newChar: "號")
        XCTAssertEqual(outcome, .replaced, "G13")
        XCTAssertEqual(doc.text, "你號世界")
        // Net length must not grow: 4 graphemes still.
        XCTAssertEqual((doc.text as NSString).length, 4)
    }

    /// G14: replace must NOT grow the sentence when delete cannot be verified.
    func testG14_replace_unwritableClient_abortsNoOp() {
        let doc = IgnoreReplaceDocument(text: "你好", caret: 1)
        let range = NSRange(location: 1, length: 1)
        let outcome = PostCommitReselect.replacePendingCharacter(
            client: doc, documentRange: range, oldChar: "好", newChar: "號")
        // IgnoreReplaceDocument ignores all mutations → old still there → abort.
        XCTAssertEqual(outcome, .abortedNoOp, "G14: must abort, not grow")
        XCTAssertEqual(doc.text, "你好", "G14: document unchanged")
    }

    /// G15: invalid range aborts without insert.
    func testG15_replace_invalidRange_aborts() {
        let doc = PostCommitStringDocument(text: "你好", caret: 0)
        let outcome = PostCommitReselect.replacePendingCharacter(
            client: doc,
            documentRange: NSRange(location: NSNotFound, length: 0),
            oldChar: "你",
            newChar: "您")
        XCTAssertEqual(outcome, .abortedNoOp, "G15")
        XCTAssertEqual(doc.text, "你好")
    }

    /// G16: readCluster at location returns grapheme + range.
    func testG16_readCluster_readable() {
        let doc = PostCommitStringDocument(text: "你好", caret: 0)
        let cluster = PostCommitReselect.readCluster(client: doc, at: 0)
        XCTAssertEqual(cluster?.char, "你")
        XCTAssertEqual(cluster?.range, NSRange(location: 0, length: 1))
    }

    // =========================================================================
    // G17–G20  手選壓過規則／神經；定案後狀態
    // =========================================================================

    /// Open candidates after composing `keys`; fail hard if LM has no multi-cand.
    private func composeAndOpenCandidates(_ keys: String) -> (
        state: InputState, choosing: InputState.ChoosingCandidate
    )? {
        var state: InputState = InputState.Empty()
        typeKeys(keys, state: &state)
        let open = handle(downKey(), state: state)
        state = open.final ?? state
        guard let choosing = state as? InputState.ChoosingCandidate,
            choosing.candidates.count >= 2
        else {
            return nil
        }
        return (state, choosing)
    }

    /// G17: hand-selected candidate survives hardCommit (pin before 定案).
    func testG17_handPick_survivesHardCommit() {
        Preferences.enableNeuralPathRerank = true
        remakeHandler()
        // Prefer 你好 (su3cl3) — dense candidate list on 好; fall back to 在/再 reading.
        let opened =
            composeAndOpenCandidates("su3cl3")
            ?? composeAndOpenCandidates("ulk4 ")
        guard let opened else {
            XCTFail("G17: need ≥2 candidates (LM data missing?) — cannot soft-skip hand-pick contract")
            return
        }
        var state = opened.state
        let choosing = opened.choosing
        let selected = choosing.candidates[1]
        handler.fixNode(
            reading: selected.reading, value: selected.value,
            originalCursorIndex: Int(choosing.originalCursorIndex),
            useMoveCursorAfterSelectionSetting: false)
        state = handler.buildInputtingState()
        let pinned = (state as? InputState.Inputting)?.composingBuffer ?? ""
        XCTAssertTrue(pinned.contains(selected.value), "G17 pre: pin \(selected.value) in \(pinned)")

        var committed = ""
        let ok = handler.hardCommitSentence(state: state) { st in
            if let c = st as? InputState.Committing { committed = c.poppedText }
        } errorCallback: {}
        XCTAssertTrue(ok)
        XCTAssertTrue(
            committed.contains(selected.value),
            "G17: hand pick must survive 定案; committed=\(committed) pick=\(selected.value)")
    }

    /// G18: hand pick survives Enter 定案 (same pin invariant as G17).
    func testG18_handPick_survivesEnterCommit() {
        Preferences.enableNeuralPathRerank = true
        remakeHandler()
        let opened =
            composeAndOpenCandidates("su3cl3")
            ?? composeAndOpenCandidates("ulk4 ")
        guard let opened else {
            XCTFail("G18: need ≥2 candidates — cannot soft-skip hand-pick contract")
            return
        }
        var state = opened.state
        let choosing = opened.choosing
        let selected = choosing.candidates[1]
        handler.fixNode(
            reading: selected.reading, value: selected.value,
            originalCursorIndex: Int(choosing.originalCursorIndex),
            useMoveCursorAfterSelectionSetting: false)
        state = handler.buildInputtingState()
        let trace = handle(enterKey(), state: state)
        XCTAssertTrue(trace.handled)
        let committed = trace.committingTexts.first ?? ""
        XCTAssertTrue(
            committed.contains(selected.value),
            "G18: hand pick survives Enter 定案; \(committed) vs \(selected.value)")
    }

    /// G19: mid-syllable (unfinished BPMF) Enter does not 定案 the grid text as 送出 confusion.
    func testG19_midSyllableEnter_doesNotPassAsSendWhenGridEmpty() {
        var state: InputState = InputState.Empty()
        // Type incomplete reading only (no tone/space commit into grid).
        typeKeys("su", state: &state)
        // If still only reading buffer / empty grid, Enter clears reading or no-ops — must handle.
        let trace = handle(enterKey(), state: state)
        // Either handled (clear reading) or not; must NOT emit Committing of host-send style
        // with non-empty Chinese unless grid had content.
        if let text = trace.committingTexts.first {
            // If something committed, it came from grid — still 定案 not 送出 (handled true).
            XCTAssertTrue(trace.handled, "G19: if commit happened, key was consumed")
            _ = text
        }
        // Core: Empty without grid must not be confused with "handled false send".
        // After incomplete "su", grid may be empty → handled true clears reading OR false.
        // Contract: never Committing empty string as fake 送出.
        for t in trace.committingTexts {
            XCTAssertFalse(t.isEmpty, "G19: empty Committing is invalid")
        }
    }

    /// G20: Empty + Down is ignored (not ShadowReselect from KeyHandler alone).
    func testG20_downOnEmpty_notHandledByKeyHandler() {
        let empty: InputState = InputState.Empty()
        let trace = handle(downKey(), state: empty)
        XCTAssertFalse(trace.handled, "G20: ↓ on Empty is controller/shadow path, not KeyHandler")
    }

    // =========================================================================
    // G21–G24  額外矩陣釘死（≥20 案）
    // =========================================================================

    /// G21: hardCommit on Empty returns false (cannot 定案 without composing).
    func testG21_hardCommit_onEmpty_returnsFalse() {
        let ok = handler.hardCommitSentence(state: InputState.Empty()) { _ in
            XCTFail("G21: must not emit states")
        } errorCallback: {}
        XCTAssertFalse(ok, "G21")
    }

    /// G22: hardCommit while mid-syllable returns false (don't auto-commit unfinished reading).
    func testG22_hardCommit_midSyllable_returnsFalse() {
        var state: InputState = InputState.Empty()
        typeKeys("su3cl3", state: &state)  // 你好 in grid
        typeKeys("su", state: &state)  // unfinished reading on top
        // If still Inputting with unfinished BPMF, hardCommit must refuse.
        if state is InputState.Inputting {
            let ok = handler.hardCommitSentence(state: state) { _ in } errorCallback: {}
            // Spec in KeyHandler: mid-syllable → return NO
            XCTAssertFalse(ok, "G22: mid-syllable hardCommit refused")
        }
    }

    /// G23: period-ON and Enter produce same stem text before punct.
    func testG23_periodCommit_stemMatchesEnterCommit() {
        remakeHandler()
        let (sEnter, stem) = composeNihao()
        let enterText = handle(enterKey(), state: sEnter).committingTexts.first ?? ""
        XCTAssertEqual(enterText, stem)
        XCTAssertFalse(enterText.isEmpty)

        Preferences.sentenceEndTriggerPeriod = true
        remakeHandler()
        var sPeriod: InputState = InputState.Empty()
        typeKeys("su3cl3", state: &sPeriod)
        let periodText = handle(shiftPeriod(), state: sPeriod).committingTexts.first ?? ""
        XCTAssertTrue(periodText.hasPrefix(enterText), "G23: \(periodText) vs \(enterText)")
    }

    /// G24: after 定案, composing buffer is cleared and commit text was emitted.
    func testG24_afterCommit_handlerBuildsEmptyInputting() {
        let (state, text) = composeNihao()
        XCTAssertFalse(text.isEmpty)
        let trace = handle(enterKey(), state: state)
        XCTAssertEqual(trace.committingTexts.first, text, "G24: must 定案 emit text")
        XCTAssertTrue(trace.sawEmpty, "G24: must reach Empty")
        // buildInputtingState after clear should be empty composing
        let after = handler.buildInputtingState()
        if let inputting = after as? InputState.Inputting {
            XCTAssertTrue(
                inputting.composingBuffer.isEmpty,
                "G24: buffer cleared after 定案; got \(inputting.composingBuffer)")
        } else {
            // Empty state object is also acceptable post-clear.
            XCTAssertTrue(after is InputState.Empty || after is InputState.EmptyIgnoringPreviousState)
        }
        // softFinalized must be false after hard commit (Path β).
        XCTAssertFalse(handler.softFinalized, "G24: softFinalized cleared")
    }
}

// MARK: - Test doubles for caret / replace matrix

/// selectedRange.location == NSNotFound (LINE/Telegram-style unreadable caret).
private final class UnreadableCaretDocument: PostCommitTextClient {
    private let storage: String
    init(text: String) { storage = text }
    func selectedRange() -> NSRange { NSRange(location: NSNotFound, length: 0) }
    func markedRange() -> NSRange { NSRange(location: NSNotFound, length: 0) }
    func attributedSubstring(from range: NSRange) -> NSAttributedString? {
        let ns = storage as NSString
        guard range.location != NSNotFound, range.location + range.length <= ns.length else {
            return nil
        }
        return NSAttributedString(string: ns.substring(with: range))
    }
    func setMarkedText(_ string: Any!, selectionRange: NSRange, replacementRange: NSRange) {}
    func insertText(_ string: Any!, replacementRange: NSRange) {}
}

/// Ignores every mutation — simulates host that cannot delete committed text.
private final class IgnoreReplaceDocument: PostCommitTextClient {
    private(set) var text: String
    private let caret: Int
    init(text: String, caret: Int) {
        self.text = text
        self.caret = caret
    }
    func selectedRange() -> NSRange { NSRange(location: caret, length: 0) }
    func markedRange() -> NSRange { NSRange(location: NSNotFound, length: 0) }
    func attributedSubstring(from range: NSRange) -> NSAttributedString? {
        let ns = text as NSString
        guard range.location != NSNotFound, range.location >= 0,
            range.location + range.length <= ns.length
        else { return nil }
        return NSAttributedString(string: ns.substring(with: range))
    }
    func setMarkedText(_ string: Any!, selectionRange: NSRange, replacementRange: NSRange) {
        // pretend mark failed
    }
    func insertText(_ string: Any!, replacementRange: NSRange) {
        // ignore — host refuses replace/delete
    }
}
