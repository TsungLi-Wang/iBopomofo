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

@Suite("AICandidateReranker Tests")
struct AICandidateRerankerTests {

    @Test("hasReadingCollision 偵測同音候選")
    func hasReadingCollisionDetectsHomophones() {
        let entries = [
            AICandidateRerankEntry(value: "在", reading: "ㄗㄞˋ"),
            AICandidateRerankEntry(value: "再", reading: "ㄗㄞˋ"),
            AICandidateRerankEntry(value: "載", reading: "ㄗㄞˋ"),
        ]
        #expect(AICandidateReranker.hasReadingCollision(in: entries))
    }

    @Test("needsSemanticRerank 對水果店案例會觸發")
    func needsSemanticRerankForFruitShopCase() {
        let context = AICandidateRerankContext(
            preceding: "水果店",
            composingBuffer: "我在去買",
            candidates: [
                .init(value: "我在去買", reading: "ㄨㄛˇ ㄗㄞˋ ㄑㄩˋ ㄇㄞˇ"),
                .init(value: "我再去買", reading: "ㄨㄛˇ ㄗㄞˋ ㄑㄩˋ ㄇㄞˇ"),
            ])
        #expect(AICandidateReranker.needsSemanticRerank(for: context))
    }

    @Test("needsSemanticRerank 對資道案例會觸發")
    func needsSemanticRerankForZiDaoCase() {
        let context = AICandidateRerankContext(
            preceding: "",
            composingBuffer: "資道",
            candidates: [
                .init(value: "資道", reading: "ㄗ ㄉㄠˋ"),
                .init(value: "知道", reading: "ㄓ ㄉㄠˋ"),
            ])
        #expect(AICandidateReranker.needsSemanticRerank(for: context))
    }

    @Test("needsSemanticRerank 對無歧義單候選不觸發")
    func needsSemanticRerankSkipsUnambiguousSingleCandidate() {
        let context = AICandidateRerankContext(
            preceding: "",
            composingBuffer: "你好",
            candidates: [.init(value: "你好", reading: "ㄋㄧˇ ㄏㄠˇ")])
        #expect(!AICandidateReranker.needsSemanticRerank(for: context))
    }

    @Test("hasPhraseAlternativeCollision 觸發近似同音多字詞(資道/知道)")
    func phraseAlternativeCollisionTriggersForNearHomophones() {
        let entries = [
            AICandidateRerankEntry(value: "資道", reading: "ㄗ ㄉㄠˋ"),
            AICandidateRerankEntry(value: "知道", reading: "ㄓ ㄉㄠˋ"),
        ]
        #expect(AICandidateReranker.hasPhraseAlternativeCollision(in: entries))
    }

    @Test("hasPhraseAlternativeCollision 不觸發無關多字詞")
    func phraseAlternativeCollisionSkipsUnrelatedPhrases() {
        let entries = [
            AICandidateRerankEntry(value: "你好", reading: "ㄋㄧˇ ㄏㄠˇ"),
            AICandidateRerankEntry(value: "天氣", reading: "ㄊㄧㄢ ㄑㄧˋ"),
        ]
        #expect(!AICandidateReranker.hasPhraseAlternativeCollision(in: entries))
    }

    @Test("needsSemanticRerank 不對無關多字候選過度觸發")
    func needsSemanticRerankSkipsUnrelatedMultiCharCandidates() {
        let context = AICandidateRerankContext(
            preceding: "",
            composingBuffer: "今天",
            candidates: [
                .init(value: "今天", reading: "ㄐㄧㄣ ㄊㄧㄢ"),
                .init(value: "明年", reading: "ㄇㄧㄥˊ ㄋㄧㄢˊ"),
            ])
        #expect(!AICandidateReranker.needsSemanticRerank(for: context))
    }

    @Test("shouldSchedule 會尊重新偏好設定")
    func shouldScheduleRespectsPreference() {
        let original = Preferences.enableAICandidateRerank
        Preferences.enableAICandidateRerank = false
        defer { Preferences.enableAICandidateRerank = original }

        let context = AICandidateRerankContext(
            preceding: "水果店",
            composingBuffer: "我在去買",
            candidates: [
                .init(value: "我在去買", reading: "ㄗㄞˋ"),
                .init(value: "我再去買", reading: "ㄗㄞˋ"),
            ])
        #expect(!AICandidateReranker.shouldSchedule(for: context))
    }

    @Test("reorderedCandidates 會把命中的 AI 建議移到第一位")
    func reorderedCandidatesMovesMatchedSuggestionToFront() {
        let original = [
            InputState.Candidate(reading: "ㄗㄞˋ", value: "在", displayText: "在", rawValue: "在"),
            InputState.Candidate(reading: "ㄗㄞˋ", value: "再", displayText: "再", rawValue: "再"),
            InputState.Candidate(reading: "ㄗㄞˋ", value: "載", displayText: "載", rawValue: "載"),
        ]

        let reordered = AICandidateReranker.reorderedCandidates(
            suggestion: "再", candidates: original)
        #expect(reordered?.map(\.value) == ["再", "在", "載"])
    }

    @Test("reorderedCandidates 未命中候選時回傳 nil")
    func reorderedCandidatesReturnsNilForOutOfListSuggestion() {
        let original = [
            InputState.Candidate(reading: "ㄇㄜ˙", value: "麼", displayText: "麼", rawValue: "麼")
        ]

        #expect(AICandidateReranker.reorderedCandidates(suggestion: "怎麼", candidates: original) == nil)
    }

    @Test("n-gram scorer 只從候選中依上下文選再說")
    func nGramScorerSelectsAgainForSayAgainContext() {
        let scorer = AICandidateNGramScorer(lines: [
            "ㄨㄛˇ-ㄗㄞˋ-ㄓㄜˋ-ㄌㄧˇ 我在這裡 2.8",
            "ㄨㄛˇ-ㄗㄞˋ-ㄕㄨㄛ-ㄧ-ㄘˋ 我再說一次 3.4",
            "ㄗㄞˋ-ㄕㄨㄛ 再說 3.0",
            "ㄗㄞˋ-ㄓㄜˋ-ㄌㄧˇ 在這裡 3.0",
        ])
        let context = AICandidateRerankContext(
            preceding: "",
            composingBuffer: "我在說一次",
            cursorIndex: 2,
            candidates: [
                .init(value: "在", reading: "ㄗㄞˋ"),
                .init(value: "再", reading: "ㄗㄞˋ"),
                .init(value: "載", reading: "ㄗㄞˋ"),
            ])

        #expect(scorer.bestCandidateValue(for: context) == "再")
    }

    @Test("n-gram scorer 依上下文保留在這裡")
    func nGramScorerKeepsAtForLocationContext() {
        let scorer = AICandidateNGramScorer(lines: [
            "ㄨㄛˇ-ㄗㄞˋ-ㄓㄜˋ-ㄌㄧˇ 我在這裡 3.4",
            "ㄨㄛˇ-ㄗㄞˋ-ㄕㄨㄛ-ㄧ-ㄘˋ 我再說一次 2.8",
            "ㄗㄞˋ-ㄕㄨㄛ 再說 3.0",
            "ㄗㄞˋ-ㄓㄜˋ-ㄌㄧˇ 在這裡 3.0",
        ])
        let context = AICandidateRerankContext(
            preceding: "",
            composingBuffer: "我在這裡",
            cursorIndex: 2,
            candidates: [
                .init(value: "在", reading: "ㄗㄞˋ"),
                .init(value: "再", reading: "ㄗㄞˋ"),
                .init(value: "載", reading: "ㄗㄞˋ"),
            ])

        #expect(scorer.bestCandidateValue(for: context) == "在")
    }

    @Test("n-gram scorer 可讀取外部 TSV trigram 模型")
    func nGramScorerLoadsExternalModelLines() {
        let scorer = AICandidateNGramScorer(modelLines: [
            "# laowang-char-ngram-v1",
            "U\t我\t10",
            "U\t在\t10",
            "U\t再\t10",
            "U\t說\t10",
            "B\t我\t再\t20",
            "B\t再\t說\t20",
            "T\t我\t再\t說\t20",
            "P\t再\t20",
        ])
        let context = AICandidateRerankContext(
            preceding: "",
            composingBuffer: "我在說",
            cursorIndex: 2,
            candidates: [
                .init(value: "在", reading: "ㄗㄞˋ"),
                .init(value: "再", reading: "ㄗㄞˋ"),
            ])

        #expect(scorer.bestCandidateValue(for: context) == "再")
    }

    @Test("isSymbolOrEmoji 偵測 emoji 與符號，但不誤殺 CJK 文字")
    func isSymbolOrEmojiDetection() {
        #expect(AICandidateReranker.isSymbolOrEmoji("📱"))
        #expect(AICandidateReranker.isSymbolOrEmoji("📁"))
        #expect(AICandidateReranker.isSymbolOrEmoji("📪"))
        #expect(AICandidateReranker.isSymbolOrEmoji("！"))
        #expect(AICandidateReranker.isSymbolOrEmoji("🔥"))
        #expect(!AICandidateReranker.isSymbolOrEmoji("在"))
        #expect(!AICandidateReranker.isSymbolOrEmoji("再去買"))
        #expect(!AICandidateReranker.isSymbolOrEmoji("研究生命"))
        #expect(!AICandidateReranker.isSymbolOrEmoji("今天天氣很好"))
    }

    @Test("bestCandidateValue 安全閘門：原 top 非符號時不推 emoji/符號")
    func ngramScorerSafetyGatePreventsSymbolPromotion() {
        // 構造 context：原 top 是文字，候選含符號。即使 ngram 可能給符號高分，也應被閘門擋住。
        let context = AICandidateRerankContext(
            preceding: "打電話",
            composingBuffer: "我的手機",
            candidates: [
                .init(value: "我的手機", reading: "ㄨㄛˇ ㄉㄜ˙ ㄕㄡˇ ㄐㄧ"),
                .init(value: "📱", reading: "ㄕㄡˇ ㄐㄧ"),
            ]
        )
        let suggestion = AICandidateNGramScorer.shared.bestCandidateValue(for: context)
        #expect(suggestion == "我的手機" || suggestion == nil)
        if let s = suggestion {
            #expect(!AICandidateReranker.isSymbolOrEmoji(s))
        }
    }
}

/// Coordinator 階段二：把 accept 配對與善後（serial bump、清狀態）這些純決策搬進
/// AIAssistCoordinator 後可單獨測試，不需要 IMK / controller。
@Suite("AIAssistCoordinator Decisions")
struct AIAssistCoordinatorTests {

    private func makeCoordinator() -> AIAssistCoordinator {
        AIAssistCoordinator(controller: nil)
    }

    @Test("L1：buffer 相符回傳建議文字，不符或無建議回 nil")
    func candidateSuggestionMatching() {
        let coordinator = makeCoordinator()
        #expect(coordinator.candidateSuggestion(matching: "你好嗎") == nil)

        coordinator.aiCandidateSuggestion = AICandidateSuggestion(
            originalComposingBuffer: "你好嗎", suggestion: "你好嘛")
        #expect(coordinator.candidateSuggestion(matching: "你好嗎") == "你好嘛")
        #expect(coordinator.candidateSuggestion(matching: "別的句子") == nil)
    }

    @Test("L2：buffer 相符回傳建議文字，不符或無建議回 nil")
    func autoCorrectionSuggestionMatching() {
        let coordinator = makeCoordinator()
        #expect(coordinator.autoCorrectionSuggestion(matching: "我吃完飯在去買") == nil)

        coordinator.aiAutoCorrectionSuggestion = AICandidateSuggestion(
            originalComposingBuffer: "我吃完飯在去買", suggestion: "我吃完飯再去買")
        #expect(coordinator.autoCorrectionSuggestion(matching: "我吃完飯在去買") == "我吃完飯再去買")
        #expect(coordinator.autoCorrectionSuggestion(matching: "其他") == nil)
    }

    @Test("L1：consume 清掉建議與重排值並 bump serial（讓 in-flight 結果作廢）")
    func consumeCandidateSuggestion() {
        let coordinator = makeCoordinator()
        coordinator.aiCandidateSuggestion = AICandidateSuggestion(
            originalComposingBuffer: "你好嗎", suggestion: "你好嘛")
        coordinator.aiCandidateRerankedValue = "你好嘛"
        let before = coordinator.aiCandidateRequestSerial

        coordinator.consumeCandidateSuggestion()

        #expect(coordinator.aiCandidateSuggestion == nil)
        #expect(coordinator.aiCandidateRerankedValue == nil)
        #expect(coordinator.aiCandidateRequestSerial == before + 1)
        // 善後後再配對應失敗
        #expect(coordinator.candidateSuggestion(matching: "你好嗎") == nil)
    }

    @Test("L2：consume 清掉建議並 bump serial")
    func consumeAutoCorrectionSuggestion() {
        let coordinator = makeCoordinator()
        coordinator.aiAutoCorrectionSuggestion = AICandidateSuggestion(
            originalComposingBuffer: "我吃完飯在去買", suggestion: "我吃完飯再去買")
        let before = coordinator.aiAutoCorrectionRequestSerial

        coordinator.consumeAutoCorrectionSuggestion()

        #expect(coordinator.aiAutoCorrectionSuggestion == nil)
        #expect(coordinator.aiAutoCorrectionRequestSerial == before + 1)
        #expect(coordinator.autoCorrectionSuggestion(matching: "我吃完飯在去買") == nil)
    }

    @Test("reset 清空 L1/L2 建議狀態")
    func resetClearsState() {
        let coordinator = makeCoordinator()
        coordinator.aiCandidateSuggestion = AICandidateSuggestion(
            originalComposingBuffer: "a", suggestion: "b")
        coordinator.aiAutoCorrectionSuggestion = AICandidateSuggestion(
            originalComposingBuffer: "c", suggestion: "d")
        coordinator.aiCandidateRerankedValue = "b"

        coordinator.reset()

        #expect(coordinator.aiCandidateSuggestion == nil)
        #expect(coordinator.aiAutoCorrectionSuggestion == nil)
        #expect(coordinator.aiCandidateRerankedValue == nil)
    }
}
