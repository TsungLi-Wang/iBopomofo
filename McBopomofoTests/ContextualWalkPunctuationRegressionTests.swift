// Regression proof: EnableContextualWalk ON must not flip multi-unigram
// punctuation readings away from the top unigram (fullwidth comma/period).
//
// Root cause under investigation: ContextModel DP re-picks among equal-score
// punctuation unigrams (e.g. ，〈《︿︽) and can surface ︽ instead of ，.
// This suite intentionally isolates the preference so host defaults cannot
// hide the failure.

import XCTest

@testable import McBopomofo

final class ContextualWalkPunctuationRegressionTests: XCTestCase {

    var handler = KeyHandler()
    var savedKeyboardLayout: KeyboardLayout = .standard
    var savedContextualWalk = false
    var savedHalfWidth = false

    override func setUpWithError() throws {
        savedKeyboardLayout = Preferences.keyboardLayout
        savedContextualWalk = Preferences.enableContextualWalk
        savedHalfWidth = Preferences.halfWidthPunctuationEnabled
        Preferences.keyboardLayout = .standard
        Preferences.halfWidthPunctuationEnabled = false
        LanguageModelManager.loadDataModels()
    }

    override func tearDownWithError() throws {
        Preferences.keyboardLayout = savedKeyboardLayout
        Preferences.enableContextualWalk = savedContextualWalk
        Preferences.halfWidthPunctuationEnabled = savedHalfWidth
    }

    private func remakeHandler() {
        handler = KeyHandler()
        handler.inputMode = .bopomofo
    }

    /// Shift+, on US layout yields charCode '<' → Standard fullwidth comma reading.
    private func typeShiftComma() -> String {
        let input = KeyHandlerInput(
            inputText: "<", keyCode: 0, charCode: charCode("<"), flags: .shift,
            isVerticalMode: false)
        var state: InputState = InputState.Empty()
        handler.handle(input: input, state: state) { newState in
            state = newState
        } errorCallback: {
        }
        return (state as? InputState.Inputting)?.composingBuffer ?? "<not-inputting:\(type(of: state))>"
    }

    private func typeShiftPeriod() -> String {
        let input = KeyHandlerInput(
            inputText: ">", keyCode: 0, charCode: charCode(">"), flags: .shift,
            isVerticalMode: false)
        var state: InputState = InputState.Empty()
        handler.handle(input: input, state: state) { newState in
            state = newState
        } errorCallback: {
        }
        return (state as? InputState.Inputting)?.composingBuffer ?? "<not-inputting:\(type(of: state))>"
    }

    /// Control: walk OFF must keep historical Shift+, → ，
    func testShiftComma_walkOff_isFullwidthComma() {
        Preferences.enableContextualWalk = false
        remakeHandler()
        let got = typeShiftComma()
        XCTAssertEqual(got, "，", "walk OFF baseline; got=\(got)")
    }

    /// Control: walk OFF Shift+. → 。
    func testShiftPeriod_walkOff_isFullwidthPeriod() {
        Preferences.enableContextualWalk = false
        remakeHandler()
        let got = typeShiftPeriod()
        XCTAssertEqual(got, "。", "walk OFF baseline; got=\(got)")
    }

    /// Bug repro: walk ON (v2.3 default) must still emit ， not ︽ / other book-title marks.
    /// Expected RED before fix.
    func testShiftComma_walkOn_mustStillBeFullwidthComma() {
        Preferences.enableContextualWalk = true
        remakeHandler()
        let got = typeShiftComma()
        XCTAssertEqual(
            got, "，",
            "ContextModel ON flipped punctuation; got=\(got) (bug if ︽/〈/《…)")
    }

    /// Bug repro: walk ON must still emit 。 not ︾.
    /// Expected RED before fix.
    func testShiftPeriod_walkOn_mustStillBeFullwidthPeriod() {
        Preferences.enableContextualWalk = true
        remakeHandler()
        let got = typeShiftPeriod()
        XCTAssertEqual(
            got, "。",
            "ContextModel ON flipped punctuation; got=\(got) (bug if ︾/〉/》…)")
    }
}
