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

enum AICorrectionPrompt {

    static func taggedPrompt(guess: String, preceding: String) -> String {
        """
        你是專為「注音輸入法」設計的中文校正引擎。下面「待修正」這句中文是注音輸入法依字詞頻率\
        猜測產生的,常因下列三類原因出現錯別字。請依「前文」與本句的上下文語意,把整句修正成使用者\
        真正想表達的正確中文。

        要積極修正的三類錯誤:
        1. 同音字選錯(最常見):依語意選對「在/再」「的/得/地」「做/作」等。
           例:「我在去買」→「我再去買」;「期待在相遇」→「期待再相遇」。
        2. 平翹舌/捲舌不分造成的錯字:ㄓㄔㄕ 與 ㄗㄘㄙ、ㄈ/ㄏ、ㄌ/ㄋ、ㄣ/ㄥ、ㄢ/ㄤ、ㄧㄣ/ㄧㄥ 等混淆。
           例:「資道」→「知道」;「老蘇」→「老師」。
        3. 注音鍵在鍵盤上相鄰、手誤打到旁邊鍵造成的錯字。
           例:「怎摸」→「怎麼」。

        規則:
        - 只輸出修正後的整句,放在 <<<R>>> 與 <<<E>>> 之間,中間不要任何解釋、引號或其他文字。
        - 只修正上述錯別字,不要改寫語氣、不要增刪內容、不要過度潤飾。
        - 若整句已正確,原樣輸出。前文僅供判斷語意,不要輸出前文。
        前文(僅供語意參考,不要輸出):\(preceding)
        待修正:\(guess)
        """
    }

    static let localSystemPrompt = """
        你是中文注音輸入法的校正引擎。使用者給你一句注音輸入法依字詞頻率猜測產生的中文,\
        可能含三類錯字:①同音字選錯②平翹舌捲舌不分(資道→知道、老蘇→老師)\
        ③注音鍵相鄰手誤(怎摸→怎麼)。請依語意把整句修正成使用者真正想表達的正確中文。
        特別注意以下最常選錯的同音虛字,務必依語意逐一判斷:
        - 「在」表位置或正在進行(我在家、正在吃飯);「再」表又一次或「之後才」(再來一次、吃完再說、\
        改天再聊)。例:我吃完飯在去買→我吃完飯再去買;期待在相遇→期待再相遇。
        - 「的」接名詞或表所屬(我的書、紅色的花);「得」接在動詞後表程度或可能(跑得快、做得好、\
        看得見);「地」接在修飾語後接動作(慢慢地走、開心地笑)。例:他跑的很快→他跑得很快;\
        我慢慢的走過去→我慢慢地走過去。
        嚴格規則:只回覆修正後的「整句」中文,一個字都不要多。不要解釋、不要引號、不要標點符號以外的符號、\
        不要接續造句、不要回答句子內容。若整句已正確就原樣回覆。
        """

    static let rerankSystemPrompt = """
        你是中文注音輸入法的即時候選語意判斷器。請依前文、目前組字與候選,判斷使用者最可能想輸入的\
        繁體中文。只修正注音輸入常見錯字:同音字、平翹舌捲舌不分、鄰鍵手誤。不要改寫語氣,不要增刪內容。
        判斷同音虛字時依語意:「在」表位置或正在(我在家);「再」表又一次或之後才(再去買、吃完再說)。\
        「的」接名詞(我的書);「得」接在動詞後表程度(跑得快、做得好);「地」接在動作前修飾(慢慢地走)。
        嚴格規則:只把建議文字放在 <<<R>>> 與 <<<E>>> 中間,不要解釋。
        """

    static func rerankPrompt(context: AICandidateRerankContext) -> String {
        let candidateLines = context.candidates.map { entry in
            if entry.reading.isEmpty {
                entry.value
            } else {
                "\(entry.value)(\(entry.reading))"
            }
        }.joined(separator: "|")
        return """
        前文:\(context.preceding)
        目前組字:\(context.composingBuffer)
        候選:\(candidateLines)
        請輸出最合適的目前組字或候選。若目前組字已正確,原樣輸出。
        輸出格式:<<<R>>>建議文字<<<E>>>
        """
    }

    static func extractTaggedResult(from raw: String) -> String? {
        if let r = raw.range(of: "<<<R>>>"), let e = raw.range(of: "<<<E>>>"),
            r.upperBound <= e.lowerBound
        {
            let s = String(raw[r.upperBound..<e.lowerBound])
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return s.isEmpty ? nil : s
        }
        return raw.split(separator: "\n")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .last(where: { !$0.isEmpty })
    }

    static func cleanLocalResult(_ text: String) -> String? {
        var cleaned = text.trimmingCharacters(in: .whitespacesAndNewlines)
        for label in ["待修正:", "待修正：", "前文:", "前文："] {
            if let r = cleaned.range(of: label, options: .backwards) {
                cleaned = String(cleaned[r.upperBound...])
            }
        }
        cleaned = cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "「」\"'。 "))
        return cleaned.isEmpty ? nil : cleaned
    }

    static func extractRerankSuggestion(from raw: String) -> String? {
        let tagged = extractTaggedResult(from: raw) ?? raw
        var cleaned = tagged.trimmingCharacters(in: .whitespacesAndNewlines)
        for label in ["AI建議:", "AI建議：", "建議:", "建議："] {
            if cleaned.hasPrefix(label) {
                cleaned = String(cleaned.dropFirst(label.count))
            }
        }
        cleaned = cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "「」\"'。 "))
        return cleaned.isEmpty ? nil : cleaned
    }
}
