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

import Foundation
import OpenCCBridge

struct AICandidateRerankEntry: Equatable {
    let value: String
    let reading: String
}

struct AICandidateRerankContext: Equatable {
    let preceding: String
    let composingBuffer: String
    let cursorIndex: Int?
    let candidates: [AICandidateRerankEntry]

    init(
        preceding: String, composingBuffer: String, cursorIndex: Int? = nil,
        candidates: [AICandidateRerankEntry]
    ) {
        self.preceding = preceding
        self.composingBuffer = composingBuffer
        self.cursorIndex = cursorIndex
        self.candidates = candidates
    }
}

enum AICandidateReranker {

    static let maxCandidateCount = 8
    static let debounceInterval: TimeInterval = 0.15

    private static let ambiguousCharacters = Set("在再的得地做作知資麼摸裡裏裡哪那裡这這")

    /// 安全閘門：L1 rescorer 只在引擎合法候選中挑，絕不把符號/emoji 主動推到第一位。
    /// 除非原本 engine top-1 就是符號，否則跳過符號候選（符合 handoff 要求）。
    static func isSymbolOrEmoji(_ value: String) -> Bool {
        guard !value.isEmpty else { return false }
        // 含 CJK 漢字範圍 → 視為一般文字內容，不是純符號
        let hasCJK = value.unicodeScalars.contains { s in
            (0x4E00...0x9FFF).contains(s.value) ||
            (0x3400...0x4DBF).contains(s.value) ||
            (0xF900...0xFAFF).contains(s.value)
        }
        if hasCJK { return false }

        // Emoji presentation 或 OtherSymbol
        if value.unicodeScalars.contains(where: { $0.properties.isEmojiPresentation || $0.properties.generalCategory == .otherSymbol }) {
            return true
        }

        // 單一或短的非字母數字可見字元，常見符號
        if value.count <= 2 && value.allSatisfy({ !$0.isLetter && !$0.isNumber && !$0.isWhitespace }) {
            return true
        }
        return false
    }

    /// 是否值得啟動 L1（不檢查 server 就緒；暖機重試由 controller 處理）。
    static func shouldSchedule(for context: AICandidateRerankContext) -> Bool {
        guard Preferences.enableAICandidateRerank else { return false }
        guard context.composingBuffer.count >= 2 else { return false }
        return needsSemanticRerank(for: context)
    }

    static func needsSemanticRerank(for context: AICandidateRerankContext) -> Bool {
        let entries = Array(context.candidates.prefix(maxCandidateCount))
        guard !entries.isEmpty else { return false }

        if hasReadingCollision(in: entries) {
            return true
        }

        if hasPhraseAlternativeCollision(in: entries) {
            return true
        }

        if containsAmbiguity(in: context.composingBuffer), entries.count >= 2 {
            let distinctValues = Set(entries.map(\.value))
            if distinctValues.count >= 2 {
                return true
            }
        }

        return false
    }

    static func hasReadingCollision(in entries: [AICandidateRerankEntry]) -> Bool {
        var readingToValues: [String: Set<String>] = [:]
        for entry in entries {
            let reading = normalizedReading(entry.reading)
            guard !reading.isEmpty else { continue }
            readingToValues[reading, default: []].insert(entry.value)
        }
        return readingToValues.values.contains { $0.count >= 2 }
    }

    /// 多字候選彼此「近似同音」時才觸發:音節數相同、且僅差一個音節(其餘相同)。
    /// 例:資道(ㄗ/ㄉㄠˋ) vs 知道(ㄓ/ㄉㄠˋ) 只差首音節 → 觸發。
    ///
    /// 舊版只要候選裡有任兩個不同的多字詞就觸發,等同每次多字選字都打 server,
    /// 過度觸發、浪費本機推理。改為要求結構上接近的同音詞才送 server 判斷;
    /// 讀音完全相同的同音詞已由 `hasReadingCollision` 覆蓋,這裡專收「平翹舌/
    /// 捲舌不分」這類差一個音節的近似音詞。
    static func hasPhraseAlternativeCollision(in entries: [AICandidateRerankEntry]) -> Bool {
        let phrases = entries.filter { $0.value.count >= 2 }
        guard phrases.count >= 2 else { return false }

        for index in 0..<(phrases.count - 1) {
            for next in (index + 1)..<phrases.count {
                if phrases[index].value == phrases[next].value { continue }
                if areNearHomophonePhrases(phrases[index].reading, phrases[next].reading) {
                    return true
                }
            }
        }
        return false
    }

    /// 兩個讀音是否「只差一個音節」(音節數相同、其餘音節一致)。
    static func areNearHomophonePhrases(_ lhs: String, _ rhs: String) -> Bool {
        let lhsSyllables = readingSyllables(lhs)
        let rhsSyllables = readingSyllables(rhs)
        guard lhsSyllables.count >= 2, lhsSyllables.count == rhsSyllables.count else {
            return false
        }
        let differing = zip(lhsSyllables, rhsSyllables).reduce(0) { $0 + ($1.0 == $1.1 ? 0 : 1) }
        return differing == 1
    }

    /// 把讀音字串切成音節(以空白分隔),例:"ㄗ ㄉㄠˋ" → ["ㄗ", "ㄉㄠˋ"]。
    static func readingSyllables(_ reading: String) -> [String] {
        reading.components(separatedBy: .whitespacesAndNewlines).filter { !$0.isEmpty }
    }

    /// 去除讀音內所有空白,讓「格式化差異」不會掩蓋同音(例:"ㄗㄞ ˋ" 與 "ㄗㄞˋ")。
    static func normalizedReading(_ reading: String) -> String {
        reading.components(separatedBy: .whitespacesAndNewlines).joined()
    }

    static func containsAmbiguity(in text: String) -> Bool {
        text.contains { ambiguousCharacters.contains($0) }
    }

    static func rerank(context: AICandidateRerankContext) -> Result<String, AICorrectionError> {
        guard let suggestion = AICandidateNGramScorer.shared.bestCandidateValue(for: context) else {
            return .failure(.malformedResponse(backend: AICorrectionBackendName.local))
        }
        return .success(suggestion)
    }

    static func reorderedCandidates(
        suggestion: String, candidates: [InputState.Candidate]
    ) -> [InputState.Candidate]? {
        guard let selectedIndex = candidates.firstIndex(where: {
            $0.value == suggestion || $0.displayText == suggestion
        }) else {
            return nil
        }
        guard selectedIndex > 0 else {
            return candidates
        }
        var reordered = candidates
        let selected = reordered.remove(at: selectedIndex)
        reordered.insert(selected, at: 0)
        return reordered
    }
}

struct AICandidateNGramScorer {
    static let shared = AICandidateNGramScorer()

    private static let alpha = 0.25
    private static let trigramWeight = 0.72
    private static let bigramWeight = 0.28
    private static let maxContextChars = 24

    private let model: Model

    init(lines: [String]? = nil) {
        if let lines {
            model = Model(lines: lines)
        } else {
            model = Model(bundleNGramResourceName: "rescorer-char-ngrams", fallbackDataResourceName: "data")
        }
    }

    init(modelLines: [String]) {
        model = Model(modelLines: modelLines)
    }

    func bestCandidateValue(for context: AICandidateRerankContext) -> String? {
        let candidates = Array(context.candidates.prefix(AICandidateReranker.maxCandidateCount))
        guard !candidates.isEmpty else { return nil }
        guard model.isReady else { return candidates.first?.value }

        let originalTop = candidates[0].value
        let originalTopIsSymbol = AICandidateReranker.isSymbolOrEmoji(originalTop)

        var best = originalTop
        var bestScore = -Double.infinity
        var considered = 0
        for (index, candidate) in candidates.enumerated() {
            if !originalTopIsSymbol && AICandidateReranker.isSymbolOrEmoji(candidate.value) {
                // 安全閘門：除非原 top-1 就是符號，否則不考慮符號/emoji 候選
                continue
            }
            considered += 1
            let text = Self.contextText(replacingWith: candidate.value, in: context)
            let score = model.score(text: text, candidateValue: candidate.value) - (Double(index) * 0.03)
            if score > bestScore {
                bestScore = score
                best = candidate.value
            }
        }
        if considered == 0 {
            // 極端情況（全為符號但原 top 不是），保險退回原 top
            return originalTop
        }
        return best
    }

    /// 把 composing buffer 沿 focus span(目前第一候選所在範圍)切成左右兩半。
    /// 找不到 span 回 nil。neural 右文 gate 與打分窗口都用這個切法。
    static func focusSplit(context: AICandidateRerankContext) -> (left: String, right: String)? {
        guard let current = context.candidates.first?.value, !current.isEmpty else { return nil }
        let composing = context.composingBuffer
        if composing == current {
            return (left: "", right: "")
        }
        guard let range = replacementRange(
            of: current, in: composing, cursorIndex: context.cursorIndex)
        else {
            return nil
        }
        return (
            left: String(composing[..<range.lowerBound]),
            right: String(composing[range.upperBound...])
        )
    }

    static func contextText(replacingWith value: String, in context: AICandidateRerankContext) -> String {
        let composing = context.composingBuffer
        guard let current = context.candidates.first?.value, !current.isEmpty else {
            return suffix(context.preceding, count: maxContextChars) + value
        }

        if composing == current {
            return suffix(context.preceding, count: maxContextChars) + value
        }

        if let range = replacementRange(of: current, in: composing, cursorIndex: context.cursorIndex) {
            let replaced = composing.replacingCharacters(in: range, with: value)
            return suffix(context.preceding, count: maxContextChars) + replaced
        }

        return suffix(context.preceding, count: maxContextChars) + composing + value
    }

    private static func replacementRange(
        of current: String, in composing: String, cursorIndex: Int?
    ) -> Range<String.Index>? {
        guard !current.isEmpty else { return nil }
        let searchEnd: String.Index
        if let cursorIndex {
            let bounded = max(0, min(cursorIndex, composing.count))
            searchEnd = composing.index(composing.startIndex, offsetBy: bounded)
        } else {
            searchEnd = composing.endIndex
        }

        if searchEnd >= composing.startIndex,
            let start = composing[..<searchEnd].range(of: current, options: .backwards)?.lowerBound
        {
            let end = composing.index(start, offsetBy: current.count)
            return start..<end
        }

        return composing.range(of: current, options: .backwards)
    }

    private static func suffix(_ text: String, count: Int) -> String {
        guard text.count > count else { return text }
        return String(text.suffix(count))
    }

    private struct Model {
        private var unigrams: [Character: Double] = [:]
        private var bigrams: [String: Double] = [:]
        private var bigramLeftTotals: [Character: Double] = [:]
        private var trigrams: [String: Double] = [:]
        private var trigramLeftTotals: [String: Double] = [:]
        private var phraseWeights: [String: Double] = [:]
        private var totalPhraseWeight = 0.0
        private var vocabularySize = 1.0

        var isReady: Bool {
            !unigrams.isEmpty
        }

        init(bundleNGramResourceName: String, fallbackDataResourceName: String) {
            let bundle = Bundle(for: McBopomofoInputMethodController.self)
            if let url = bundle.url(forResource: bundleNGramResourceName, withExtension: "tsv"),
                let content = try? String(contentsOf: url, encoding: .utf8)
            {
                self.init(modelLines: content.components(separatedBy: .newlines))
                return
            }
            guard let url = bundle.url(forResource: fallbackDataResourceName, withExtension: "txt"),
                let content = try? String(contentsOf: url, encoding: .utf8)
            else {
                self.init(dataLines: [])
                return
            }
            self.init(dataLines: content.components(separatedBy: .newlines))
        }

        init(lines: [String]) {
            self.init(dataLines: lines)
        }

        init(dataLines: [String]) {
            for line in dataLines {
                addDataLine(line)
            }
            vocabularySize = max(1.0, Double(unigrams.count))
        }

        init(modelLines: [String]) {
            for line in modelLines {
                addModelLine(line)
            }
            vocabularySize = max(1.0, Double(unigrams.count))
        }

        mutating private func addModelLine(_ line: String) {
            guard !line.isEmpty, !line.hasPrefix("#") else { return }
            let fields = line.split(separator: "\t", omittingEmptySubsequences: false)
            guard let tag = fields.first, let countText = fields.last,
                let count = Double(countText), count > 0
            else {
                return
            }

            if tag == "U", fields.count == 3, let char = fields[1].first {
                unigrams[char, default: 0] += count
            } else if tag == "B", fields.count == 4,
                let left = fields[1].first, let right = fields[2].first
            {
                let key = String(left) + String(right)
                bigrams[key, default: 0] += count
                bigramLeftTotals[left, default: 0] += count
            } else if tag == "T", fields.count == 5,
                let first = fields[1].first, let second = fields[2].first,
                let third = fields[3].first
            {
                let left = String(first) + String(second)
                let key = left + String(third)
                trigrams[key, default: 0] += count
                trigramLeftTotals[left, default: 0] += count
            } else if tag == "P", fields.count == 3 {
                phraseWeights[String(fields[1]), default: 0] += count
                totalPhraseWeight += count
            }
        }

        mutating private func addDataLine(_ line: String) {
            guard !line.isEmpty, !line.hasPrefix("#") else { return }
            let parts = line.split(whereSeparator: { $0 == " " || $0 == "\t" })
            guard parts.count >= 3 else { return }

            let value = String(parts[1])
            guard value.count >= 1 else { return }
            let score = Double(parts[2]).map { exp($0) } ?? 1.0
            let weight = max(score, 1e-12)
            let chars = Array(value)

            phraseWeights[value, default: 0] += weight
            totalPhraseWeight += weight

            for char in chars {
                unigrams[char, default: 0] += weight
            }
            guard chars.count >= 2 else { return }
            for index in 0..<(chars.count - 1) {
                let key = String(chars[index]) + String(chars[index + 1])
                bigrams[key, default: 0] += weight
                bigramLeftTotals[chars[index], default: 0] += weight
            }
            guard chars.count >= 3 else { return }
            for index in 0..<(chars.count - 2) {
                let left = String(chars[index]) + String(chars[index + 1])
                let key = left + String(chars[index + 2])
                trigrams[key, default: 0] += weight
                trigramLeftTotals[left, default: 0] += weight
            }
        }

        func score(text: String, candidateValue: String) -> Double {
            let chars = Array(text)
            guard !chars.isEmpty else { return -Double.infinity }

            var total = phraseLogProbability(candidateValue) * 0.12
            for index in chars.indices {
                if index >= 2 {
                    total += AICandidateNGramScorer.trigramWeight * trigramLogProbability(
                        chars[index - 2], chars[index - 1], chars[index])
                    total += AICandidateNGramScorer.bigramWeight * bigramLogProbability(
                        chars[index - 1], chars[index])
                } else if index >= 1 {
                    total += bigramLogProbability(chars[index - 1], chars[index])
                } else {
                    total += unigramLogProbability(chars[index])
                }
            }
            return total
        }

        private func unigramLogProbability(_ char: Character) -> Double {
            let total = unigrams.values.reduce(0, +)
            let count = unigrams[char] ?? 0
            return log(
                (count + AICandidateNGramScorer.alpha)
                    / (total + AICandidateNGramScorer.alpha * vocabularySize))
        }

        private func bigramLogProbability(_ left: Character, _ right: Character) -> Double {
            let key = String(left) + String(right)
            let count = bigrams[key] ?? 0
            let leftTotal = bigramLeftTotals[left] ?? 0
            return log(
                (count + AICandidateNGramScorer.alpha)
                    / (leftTotal + AICandidateNGramScorer.alpha * vocabularySize))
        }

        private func trigramLogProbability(
            _ first: Character, _ second: Character, _ third: Character
        ) -> Double {
            let left = String(first) + String(second)
            let key = left + String(third)
            let count = trigrams[key] ?? 0
            let leftTotal = trigramLeftTotals[left] ?? 0
            return log(
                (count + AICandidateNGramScorer.alpha)
                    / (leftTotal + AICandidateNGramScorer.alpha * vocabularySize))
        }

        private func phraseLogProbability(_ value: String) -> Double {
            let count = phraseWeights[value] ?? 0
            return log(
                (count + AICandidateNGramScorer.alpha)
                    / (totalPhraseWeight + AICandidateNGramScorer.alpha * vocabularySize))
        }
    }
}

// Phase 1 refactor per design report: 明確協議層，把 n-gram 標為「快速層」。
// Coordinator 之後可用這些協議來統一 L1/L2 呼叫。
protocol CandidateRescorer {
    func shouldRescore(_ context: AICandidateRerankContext) -> Bool
    func rescore(context: AICandidateRerankContext) async -> Result<String, AICorrectionError>
}

/// 快速層實作：目前就是字元 n-gram，不依賴 server。
struct NgramCandidateRescorer: CandidateRescorer {
    func shouldRescore(_ context: AICandidateRerankContext) -> Bool {
        AICandidateReranker.shouldSchedule(for: context)
    }

    func rescore(context: AICandidateRerankContext) async -> Result<String, AICorrectionError> {
        // n-gram 目前同步且即時；async 包裝以符合協議，方便 Coordinator 統一呼叫。
        AICandidateReranker.rerank(context: context)
    }
}

protocol SentenceCorrector {
    func correct(guess: String, preceding: String) async -> Result<String, AICorrectionError>
}

/// 目前 L2 後端（本機 llama）的包裝。設計報告階段二建議把內部 semaphore 換 async/await。
struct LocalServerSentenceCorrector: SentenceCorrector {
    func correct(guess: String, preceding: String) async -> Result<String, AICorrectionError> {
        await withCheckedContinuation { continuation in
            let result = LocalServerAICorrector.correct(guess: guess, preceding: preceding)
            continuation.resume(returning: result)
        }
    }
}
