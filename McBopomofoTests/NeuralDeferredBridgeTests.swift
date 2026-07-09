// Copyright (c) 2022 and onwards The McBopomofo Authors.
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

import XCTest

@testable import McBopomofo

/// 延遲神經重審橋的引擎級測試:用標準注音鍵序真打字,驗 snapshot 列舉與
/// applyNeuralOverride 軟覆寫在真實 walk 上的行為。
///
/// v2.3 起 `EnableContextualWalk` 預設 YES,「跑的很快」會被 bigram 翻成「跑得很快」。
/// 未隔離時,以「的」為 current 的斷言會誤紅。本 suite 在 unigram 路徑案例強制關
/// 情境化;另有一案在 walk ON 下驗 hybrid reselect(得→的)。
final class NeuralDeferredBridgeTests: XCTestCase {

    var handler = KeyHandler()
    var savedKeyboardLayout: KeyboardLayout = .standard
    var savedAssociatedPhrases = false
    var savedContextualWalk = false

    override func setUpWithError() throws {
        savedKeyboardLayout = Preferences.keyboardLayout
        savedAssociatedPhrases = Preferences.associatedPhrasesEnabled
        savedContextualWalk = Preferences.enableContextualWalk
        Preferences.keyboardLayout = .standard
        Preferences.associatedPhrasesEnabled = false
        // Default for most cases: unigram path so 「的」still surfaces.
        Preferences.enableContextualWalk = false
        LanguageModelManager.loadDataModels()
        handler = KeyHandler()
        handler.inputMode = .bopomofo
    }

    override func tearDownWithError() throws {
        Preferences.keyboardLayout = savedKeyboardLayout
        Preferences.associatedPhrasesEnabled = savedAssociatedPhrases
        Preferences.enableContextualWalk = savedContextualWalk
    }

    private func remakeHandler() {
        handler = KeyHandler()
        handler.inputMode = .bopomofo
    }

    private func type(_ keys: String) -> InputState {
        var state: InputState = InputState.Empty()
        for key in keys.map({ String($0) }) {
            let input = KeyHandlerInput(
                inputText: key, keyCode: 0, charCode: charCode(key), flags: [],
                isVerticalMode: false)
            handler.handle(input: input, state: state) { newState in
                state = newState
            } errorCallback: {
            }
        }
        return state
    }

    private func snapshot() -> (text: String, spans: [[String: Any]]) {
        guard
            let dict = handler.neuralRerankSnapshot(
                characters: McBopomofoInputMethodController.neuralDeferredCharacters,
                maxAlternatives: 4) as? [String: Any],
            let text = dict["text"] as? String,
            let spans = dict["spans"] as? [[String: Any]]
        else {
            return ("", [])
        }
        return (text, spans)
    }

    /// 跑的很快(ㄆㄠˇ ㄉㄜ˙ ㄏㄣˇ ㄎㄨㄞˋ):的 應為 span-1 節點且被列入 spans。
    /// 強制 unigram 路徑(情境化關)。
    func testSnapshotListsSpanOneDeNode() {
        let state = type("ql32k7cp3dj94")
        XCTAssertTrue(state is InputState.Inputting, "\(state)")
        let composing = (state as? InputState.Inputting)?.composingBuffer ?? ""

        let snap = snapshot()
        XCTAssertEqual(snap.text, composing, "walk 攤平字串應等於 composing buffer")
        XCTAssertFalse(snap.spans.isEmpty, "跑的很快 的「的」應被列為歧義 span;spans=\(snap.spans) text=\(snap.text)")

        guard let deSpan = snap.spans.first(where: { ($0["current"] as? String) == "的" }) else {
            XCTFail("找不到「的」span;spans=\(snap.spans) text=\(snap.text)")
            return
        }
        XCTAssertEqual(deSpan["location"] as? Int, 1)
        let alternatives = deSpan["alternatives"] as? [String] ?? []
        XCTAssertTrue(alternatives.contains("得"), "alternatives=\(alternatives)")
    }

    /// applyNeuralOverride 應把「的」軟覆寫成「得」並反映在重建的 Inputting。
    /// 強制 unigram 路徑。
    func testApplyNeuralOverrideFlipsDe() {
        _ = type("ql32k7cp3dj94")
        let snap = snapshot()
        guard let deSpan = snap.spans.first(where: { ($0["current"] as? String) == "的" }),
            let location = deSpan["location"] as? Int,
            let reading = deSpan["reading"] as? String
        else {
            XCTFail("前置條件失敗:找不到「的」span;text=\(snap.text) spans=\(snap.spans)")
            return
        }
        let applied = handler.applyNeuralOverride(
            location: UInt(location), reading: reading, expectedCurrent: "的", value: "得")
        XCTAssertTrue(applied, "applyNeuralOverride 應成功")

        let rebuilt = handler.buildInputtingState()
        let buffer = (rebuilt as? InputState.Inputting)?.composingBuffer ?? ""
        XCTAssertTrue(buffer.contains("得"), "重建後 buffer 應含「得」;buffer=\(buffer)")
    }

    /// 情境化 walk ON: bigram 選「寫得很好」(多字節點 寫得, ug 含 寫的/寫得)後,
    /// RNN 仍可 reselect 成「寫的」並反映到 buffer。
    /// 注意:「跑得很快」在 walk ON 時是 跑得(ug=1)+很快,沒有孿生 unigram,snapshot
    /// 本來就列不出 span——那是切詞結果不是 reselect bug。本案用有孿生的 寫得。
    func testContextualWalkOnNeuralReselectStillVisible() {
        Preferences.enableContextualWalk = true
        remakeHandler()

        // ㄒㄧㄝˇ ㄉㄜ˙ ㄏㄣˇ ㄏㄠˇ
        _ = type("vu,32k7cp3cl3")
        let snap = snapshot()
        XCTAssertTrue(
            snap.text.contains("寫得") || snap.text.contains("寫的"),
            "應組成 寫X很好;text=\(snap.text)")

        let deFamily = snap.spans.first { span in
            let cur = span["current"] as? String
            return cur == "得" || cur == "的"
        }
        guard let span = deFamily,
            let location = span["location"] as? Int,
            let reading = span["reading"] as? String,
            let current = span["current"] as? String
        else {
            XCTFail("找不到 的/得 span;text=\(snap.text) spans=\(snap.spans)")
            return
        }

        let target = current == "得" ? "的" : "得"
        let applied = handler.applyNeuralOverride(
            location: UInt(location), reading: reading, expectedCurrent: current, value: target)
        XCTAssertTrue(applied, "walk ON 時 neural reselect \(current)→\(target) 應成功")

        let rebuilt = handler.buildInputtingState()
        let buffer = (rebuilt as? InputState.Inputting)?.composingBuffer ?? ""
        XCTAssertTrue(
            buffer.contains("寫\(target)"),
            "hybrid reselect 後 buffer 應含「寫\(target)」;buffer=\(buffer) textWas=\(snap.text)")
    }

    /// 慢慢的走過來:「的」在多字詞節點(慢慢的)內 —— v1 span-1 限制的已知缺口,
    /// 本測試記錄目前行為(修好孿生節點後改斷言)。
    func testSnapshotMultiSyllableTwinNode() {
        let state = type("a04a042k7y.3eji4x96")
        let composing = (state as? InputState.Inputting)?.composingBuffer ?? ""
        let snap = snapshot()
        XCTAssertEqual(snap.text, composing)
        let hasDe = snap.spans.contains { span in
            (span["alternatives"] as? [String])?.contains("地") == true
        }
        XCTAssertTrue(
            hasDe,
            "慢慢的(孿生 unigram 慢慢地 存在)應可列入 spans;composing=\(composing) spans=\(snap.spans)")
    }
}
