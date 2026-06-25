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

import Testing

@testable import McBopomofo

@Suite("AIAutoCorrector Tests")
struct AIAutoCorrectorTests {

    // MARK: - endsWithSentencePunctuation

    @Test("句末標點:全形句號、驚嘆號、問號、刪節號都算句末")
    func detectsFullWidthSentenceEndings() {
        #expect(AIAutoCorrector.endsWithSentencePunctuation("你好嗎。"))
        #expect(AIAutoCorrector.endsWithSentencePunctuation("太好了！"))
        #expect(AIAutoCorrector.endsWithSentencePunctuation("是嗎？"))
        #expect(AIAutoCorrector.endsWithSentencePunctuation("等等…"))
    }

    @Test("句末標點:半形 ! 與 ? 也算句末")
    func detectsHalfWidthSentenceEndings() {
        #expect(AIAutoCorrector.endsWithSentencePunctuation("really?"))
        #expect(AIAutoCorrector.endsWithSentencePunctuation("wow!"))
    }

    @Test("非句末:逗號、頓號、無標點、空字串都不算")
    func rejectsNonSentenceEndings() {
        #expect(!AIAutoCorrector.endsWithSentencePunctuation("我在家，"))
        #expect(!AIAutoCorrector.endsWithSentencePunctuation("蘋果、香蕉"))
        #expect(!AIAutoCorrector.endsWithSentencePunctuation("我知道你在哪裡"))
        #expect(!AIAutoCorrector.endsWithSentencePunctuation(""))
    }

    // MARK: - isCorrectableSentence

    @Test("可校正:長度達標、游標在句尾、以句末標點結束")
    func acceptsWellFormedSentence() {
        #expect(
            AIAutoCorrector.isCorrectableSentence(
                composingBuffer: "你好嗎。", cursorIndex: 4))
        #expect(
            AIAutoCorrector.isCorrectableSentence(
                composingBuffer: "我知道你在資哪裡。", cursorIndex: 9))
    }

    @Test("不校正:沒有句末標點")
    func rejectsSentenceWithoutPunctuation() {
        #expect(
            !AIAutoCorrector.isCorrectableSentence(
                composingBuffer: "我知道你在哪裡", cursorIndex: 7))
    }

    @Test("不校正:句子太短(含標點仍低於門檻)")
    func rejectsTooShortSentence() {
        #expect(
            !AIAutoCorrector.isCorrectableSentence(
                composingBuffer: "好。", cursorIndex: 2))
    }

    @Test("不校正:游標不在句尾(使用者把游標移回句中)")
    func rejectsWhenCursorNotAtEnd() {
        #expect(
            !AIAutoCorrector.isCorrectableSentence(
                composingBuffer: "你好嗎。", cursorIndex: 2))
    }

    @Test("不校正:句中標點(逗號、頓號)不觸發")
    func rejectsMidSentencePunctuation() {
        #expect(
            !AIAutoCorrector.isCorrectableSentence(
                composingBuffer: "我在家，準備", cursorIndex: 6))
        #expect(
            !AIAutoCorrector.isCorrectableSentence(
                composingBuffer: "蘋果、香蕉、橘子、", cursorIndex: 9))
    }

    @Test("門檻長度剛好滿足時可校正")
    func acceptsAtExactMinimumLength() {
        let buffer = String(repeating: "字", count: AIAutoCorrector.minComposingLength - 1) + "。"
        #expect(
            AIAutoCorrector.isCorrectableSentence(
                composingBuffer: buffer, cursorIndex: buffer.count))
    }
}
