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

import Cocoa
import CryptoKit

private let kKeyboardLayoutPreferenceKey = "KeyboardLayout"
/// alphanumeric ("ASCII") input basic keyboard layout.
private let kBasisKeyboardLayoutPreferenceKey = "BasisKeyboardLayout"
/// alphanumeric ("ASCII") input basic keyboard layout.
private let kFunctionKeyKeyboardLayoutPreferenceKey = "FunctionKeyKeyboardLayout"
/// whether include shift.
private let kFunctionKeyKeyboardLayoutOverrideIncludeShiftKey =
    "FunctionKeyKeyboardLayoutOverrideIncludeShift"
private let kCandidateListTextSizeKey = "CandidateListTextSize"
private let kSelectPhraseAfterCursorAsCandidateKey = "SelectPhraseAfterCursorAsCandidate"
private let kMoveCursorAfterSelectingCandidateKey = "MoveCursorAfterSelectingCandidate"
private let kUseHorizontalCandidateListPreferenceKey = "UseHorizontalCandidateList"
private let kChooseCandidateUsingSpaceKey = "ChooseCandidateUsingSpaceKey"
private let kChineseConversionEnabledKey = "ChineseConversionEnabled"
private let kHalfWidthPunctuationEnabledKey = "HalfWidthPunctuationEnable"
private let kEscToCleanInputBufferKey = "EscToCleanInputBuffer"
private let kKeepReadingUponCompositionError = "KeepReadingUponCompositionError"

private let kCandidateTextFontName = "CandidateTextFontName"
private let kCandidateKeyLabelFontName = "CandidateKeyLabelFontName"
private let kCandidateKeys = "CandidateKeys"
private let kAllowMovingCursorWhenChoosingCandidates = "AllowMovingCursorWhenChoosingCandidates"

private let kPhraseReplacementEnabledKey = "PhraseReplacementEnabled"
private let kChineseConversionStyleKey = "ChineseConversionStyle"
private let kAssociatedPhrasesEnabledKey = "AssociatedPhrasesEnabled"
private let kLetterBehaviorKey = "LetterBehavior"
private let kControlEnterOutputKey = "ControlEnterOutput"
private let kShiftEnterEnabledKey = "ShiftEnterEnabled"
private let kRepeatedPunctuationToSelectCandidateEnabledKey =
    "RepeatedPunctuationToSelectCandidateEnabled"
private let kUseCustomUserPhraseLocation = "UseCustomUserPhraseLocation"
private let kCustomUserPhraseLocation = "CustomUserPhraseLocation"
private let kEnableContextualWalkKey = "EnableContextualWalk"
private let kEnableNeuralPathRerankKey = "EnableNeuralPathRerank"
private let kNeuralPathRerankNuKey = "NeuralPathRerankNu"
private let kPrefsSchemaVersionKey = "PrefsSchemaVersion"
private let kEnableRerankDiffLogKey = "EnableRerankDiffLog"

// Sentence-end triggers for auto soft-finalize (智慧改字定案).
// Pause / comma / period / Enter are independent toggles (pause default ON).
private let kSentenceEndTriggerEnterKey = "SentenceEndTriggerEnter"
private let kSentenceEndTriggerPeriodKey = "SentenceEndTriggerPeriod"
private let kSentenceEndTriggerCommaKey = "SentenceEndTriggerComma"
private let kSentenceEndPauseEnabledKey = "SentenceEndPauseEnabled"
private let kSentenceEndPauseMsKey = "SentenceEndPauseMs"
private let kEnableManualCorrectionLogKey = "EnableManualCorrectionLog"

/// Code-level shipping constants (not UserDefaults — effective values for observability).
enum ShippingRerankConstants {
    static let contextualLambda = 0.75
    static let pathRerankNBest = 10
    /// v4: path β pause=auto-rerank only; 。/， default OFF (insert punct only).
    static let prefsSchemaVersion = 4
    /// Minimum idle pause before auto-rerank (ms).
    static let sentenceEndPauseMsMin = 200
    /// First-ship default idle pause (ms).
    static let sentenceEndPauseMsDefault = 800
}

private let kDefaultCandidateListTextSize: CGFloat = 16
private let kMinCandidateListTextSize: CGFloat = 12
private let kMaxCandidateListTextSize: CGFloat = 196

private let kDefaultKeys = "123456789"
private let kDefaultAssociatedPhrasesKeys = "!@#$%^&*("

private let kAddPhraseHookEnabledKey = "AddPhraseHookEnabled"
private let kAddPhraseHookPath = "AddPhraseHookPath"

private let kSelectCandidateWithNumericKeypad = "SelectCandidateWithNumericKeypad"
private let kBig5InputEnabledKey = "Big5InputEnabled"

// Need to be populated to true by default upon first start, so the key is not private.
let kBeepUponInputErrorKey = "BeepUponInputError"

private let kEnableUserPhrasesInPlainBopomofo = "EnableUserPhrasesInPlainBopomofo"
private let kAllowChangingPriorTone = "AllowChangingPriorTone"

private let kBopomofoFontAnnotationSupportEnabled = "BopomofoFontAnnotationSupportEnabled"
private let kShowBopomofoFontAnnotationSupportItemInInputMenu =
    "ShowBopomofoFontAnnotationSupportItemInInputMenu"
private let kBopomofoFontAnnotationSupportMenuItemEnabledByInstalledFontsCheck_V1 =
    "BopomofoFontAnnotationSupportMenuItemEnabledByInstalledFontsCheck_V1"

// MARK: Property wrappers

@propertyWrapper
struct UserDefault<Value> {
    let key: String
    let defaultValue: Value
    var container: UserDefaults = .standard

    var wrappedValue: Value {
        get {
            container.object(forKey: key) as? Value ?? defaultValue
        }
        set {
            container.set(newValue, forKey: key)
        }
    }
}

@propertyWrapper
struct UserDefaultWithFunction<Value> {
    let key: String
    let defaultValueFunction: () -> Value
    var container: UserDefaults = .standard

    var wrappedValue: Value {
        get {
            container.object(forKey: key) as? Value ?? defaultValueFunction()
        }
        set {
            container.set(newValue, forKey: key)
        }
    }
}

@propertyWrapper
struct EnumUserDefault<T: RawRepresentable> {
    let key: String
    let defaultValue: T
    var container: UserDefaults = .standard

    var wrappedValue: T {
        get {
            if let value = container.object(forKey: key) as? T.RawValue {
                return T(rawValue: value) ?? defaultValue
            }
            return defaultValue
        }
        set {
            container.set(newValue.rawValue, forKey: key)
        }
    }
}

@propertyWrapper
struct CandidateListTextSize {
    let key: String
    let defaultValue: CGFloat = kDefaultCandidateListTextSize
    lazy var container: UserDefault = {
        UserDefault(key: key, defaultValue: defaultValue)
    }()

    var wrappedValue: CGFloat {
        mutating get {
            var value = container.wrappedValue
            if value < kMinCandidateListTextSize {
                value = kMinCandidateListTextSize
            } else if value > kMaxCandidateListTextSize {
                value = kMaxCandidateListTextSize
            }
            return value
        }
        set {
            var value = newValue
            if value < kMinCandidateListTextSize {
                value = kMinCandidateListTextSize
            } else if value > kMaxCandidateListTextSize {
                value = kMaxCandidateListTextSize
            }
            container.wrappedValue = value
        }
    }
}

// MARK: -

@objc enum KeyboardLayout: Int {
    case standard = 0
    case eten = 1
    case hsu = 2
    case eten26 = 3
    case hanyuPinyin = 4
    case IBM = 5

    var name: String {
        return switch self {
        case .standard:
            "Standard"
        case .eten:
            "ETen"
        case .hsu:
            "Hsu"
        case .eten26:
            "ETen26"
        case .hanyuPinyin:
            "HanyuPinyin"
        case .IBM:
            "IBM"
        }
    }
}

@objc enum ChineseConversionStyle: Int {
    case output
    case model

    var name: String {
        return switch self {
        case .output:
            "output"
        case .model:
            "model"
        }
    }
}

// MARK: -

class Preferences: NSObject {
    static var allKeys: [String] {
        [
            kKeyboardLayoutPreferenceKey,
            kBasisKeyboardLayoutPreferenceKey,
            kFunctionKeyKeyboardLayoutPreferenceKey,
            kFunctionKeyKeyboardLayoutOverrideIncludeShiftKey,
            kCandidateListTextSizeKey,
            kSelectPhraseAfterCursorAsCandidateKey,
            kUseHorizontalCandidateListPreferenceKey,
            kChooseCandidateUsingSpaceKey,
            kChineseConversionEnabledKey,
            kHalfWidthPunctuationEnabledKey,
            kEscToCleanInputBufferKey,
            kKeepReadingUponCompositionError,
            kCandidateTextFontName,
            kCandidateKeyLabelFontName,
            kCandidateKeys,
            kPhraseReplacementEnabledKey,
            kChineseConversionStyleKey,
            kAssociatedPhrasesEnabledKey,
            kControlEnterOutputKey,
            kShiftEnterEnabledKey,
            kRepeatedPunctuationToSelectCandidateEnabledKey,
            kUseCustomUserPhraseLocation,
            kCustomUserPhraseLocation,
            kEnableContextualWalkKey,
            kEnableNeuralPathRerankKey,
        ]
    }

    @objc static func populateDefaults() {
        Preferences.keyboardLayout = Preferences.keyboardLayout
        Preferences.basisKeyboardLayout = Preferences.basisKeyboardLayout
        Preferences.functionKeyboardLayout = Preferences.functionKeyboardLayout
        Preferences.candidateKeys = Preferences.candidateKeys
        Preferences.selectPhraseAfterCursorAsCandidate =
            Preferences.selectPhraseAfterCursorAsCandidate
        Preferences.moveCursorAfterSelectingCandidate =
            Preferences.moveCursorAfterSelectingCandidate
        Preferences.useHorizontalCandidateList = Preferences.useHorizontalCandidateList
        Preferences.chineseConversionEnabled = Preferences.chineseConversionEnabled
        Preferences.halfWidthPunctuationEnabled = Preferences.halfWidthPunctuationEnabled
        Preferences.selectCandidateWithNumericKeypad = Preferences.selectCandidateWithNumericKeypad
        Preferences.big5InputEnabled = Preferences.big5InputEnabled
        Preferences.chineseConversionStyle = Preferences.chineseConversionStyle
        Preferences.phraseReplacementEnabled = Preferences.phraseReplacementEnabled
        Preferences.associatedPhrasesEnabled = Preferences.associatedPhrasesEnabled
        Preferences.letterBehavior = Preferences.letterBehavior
        Preferences.controlEnterOutput = Preferences.controlEnterOutput
        Preferences.shiftEnterEnabled = Preferences.shiftEnterEnabled
        Preferences.repeatedPunctuationToSelectCandidateEnabled =
            Preferences.repeatedPunctuationToSelectCandidateEnabled
        Preferences.addPhraseHookEnabled = Preferences.addPhraseHookEnabled
        Preferences.addPhraseHookPath = Preferences.addPhraseHookPath
        Preferences.beepUponInputError = Preferences.beepUponInputError
        Preferences.enableUserPhrasesInPlainBopomofo = Preferences.enableUserPhrasesInPlainBopomofo
        Preferences.allowMovingCursorWhenChoosingCandidates =
            Preferences.allowMovingCursorWhenChoosingCandidates
        Preferences.enableContextualWalk = Preferences.enableContextualWalk
    }


    /// Orphan keys from removed llama/Claude/AI features (v2.7.0+).
    /// Kept as the first prefsSchema migration step and re-run every launch for defense-in-depth.
    private static let removedPreferenceKeys: [String] = [
        "EnableAICandidateRerank",
        "EnableAIAutoCorrection",
        "EnableConfusionPairDisambiguation",
        "EnableGlobalNeuralRerank",
        "AICorrectionBackend",
        "AICorrectionClaudeEndpoint",
        "AICorrectionClaudeOpusModel",
        "NeuralDeferredDiagnostics",
    ]

    /// Accumulative preference migrations. v2.7 purge was every-launch orphan removal but did
    /// not version the store — future default flips need numbered steps so old values cannot
    /// silently cover new defaults (v2.6 residual-flag class of bug).
    @objc static func migratePreferencesIfNeeded() {
        let d = UserDefaults.standard
        var version = d.object(forKey: kPrefsSchemaVersionKey) as? Int ?? 0
        while version < ShippingRerankConstants.prefsSchemaVersion {
            switch version {
            case 0:
                // v1: drop removed AI/llama preference keys (safe if already gone).
                migratePrefsToV1_PurgeRemovedAIKeys()
                version = 1
            case 1:
                // v2: sentence-end soft-finalize prefs (defaults via @UserDefault).
                NSLog(
                    "Preferences: migrated prefsSchemaVersion → 2 (sentence-end soft finalize)")
                version = 2
            case 2:
                // v3: pause becomes a user toggle (default ON; ms still 800).
                NSLog(
                    "Preferences: migrated prefsSchemaVersion → 3 (sentence-end pause toggle)")
                version = 3
            case 3:
                // v4: path β — pause/。/， no longer hard-commit; 。/， default OFF.
                // Force period off so old "定案 on 。" does not keep auto-firing.
                d.set(false, forKey: kSentenceEndTriggerPeriodKey)
                d.set(false, forKey: kSentenceEndTriggerCommaKey)
                NSLog(
                    "Preferences: migrated prefsSchemaVersion → 4 (pause=auto-rerank; punct default off)")
                version = 4
            default:
                version = ShippingRerankConstants.prefsSchemaVersion
            }
        }
        d.set(version, forKey: kPrefsSchemaVersionKey)
        // Defense-in-depth: re-purge orphans every launch (idempotent).
        purgeRemovedFeaturePreferences()
    }

    private static func migratePrefsToV1_PurgeRemovedAIKeys() {
        purgeRemovedFeaturePreferences()
        NSLog("Preferences: migrated prefsSchemaVersion → 1 (orphan AI keys purge)")
    }

    @objc static func purgeRemovedFeaturePreferences() {
        let d = UserDefaults.standard
        var purged: [String] = []
        for key in removedPreferenceKeys {
            if d.object(forKey: key) != nil {
                d.removeObject(forKey: key)
                purged.append(key)
            }
        }
        if !purged.isEmpty {
            d.synchronize()
            NSLog("Preferences: purged removed-feature keys: \(purged.joined(separator: ", "))")
        }
    }

    /// Effective (live) shipping configuration — not raw plist dump.
    @objc static func effectiveShippingConfigurationSummary() -> String {
        let neural = Preferences.enableNeuralPathRerank
        let nu = Preferences.neuralPathRerankNu
        let contextual = Preferences.enableContextualWalk
        let lambda = ShippingRerankConstants.contextualLambda
        let n = ShippingRerankConstants.pathRerankNBest
        let schema = UserDefaults.standard.object(forKey: kPrefsSchemaVersionKey) as? Int ?? 0
        let model = Preferences.shippingModelFingerprint()
        let diffLog = Preferences.enableRerankDiffLog ? "ON" : "OFF"
        let path = RerankDiffLog.logFilePath
        let shortVer =
            Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "?"
        let gitRev = Bundle.main.infoDictionary?["GitRevision"] as? String ?? "?"
        return """
        生效設定 (effective, not raw plist):
          version: \(shortVer) (build \(build))  GitRevision: \(gitRev)
          contextualWalk: \(contextual ? "ON" : "OFF")  (λ=\(String(format: "%.2f", lambda)) code constant)
          neuralPathRerank: \(neural ? "ON" : "OFF")
          ν: \(String(format: "%.2f", nu))
          N: \(n)
          model: \(model)
          prefsSchemaVersion: \(schema)
          rerankDiffLog: \(diffLog)
          rerankDiffLogPath: \(path)
          sentenceEnd: pause=\(sentenceEndPauseEnabled ? "ON" : "OFF")@\(sentenceEndPauseMs)ms enter=\(sentenceEndTriggerEnter ? "ON" : "OFF") period=\(sentenceEndTriggerPeriod ? "ON" : "OFF") comma=\(sentenceEndTriggerComma ? "ON" : "OFF")
          manualCorrectionLog: \(enableManualCorrectionLog ? "ON" : "OFF")
        """
    }

    @objc static func logShippingConfiguration() {
        NSLog("%@", Preferences.effectiveShippingConfigurationSummary().replacingOccurrences(of: "\n", with: " | "))
    }

    /// Short fingerprint of bundled path-char-lstm.bin (size + SHA256 prefix).
    static func shippingModelFingerprint() -> String {
        guard let url = Bundle.main.url(forResource: "path-char-lstm", withExtension: "bin"),
            let data = try? Data(contentsOf: url)
        else {
            return "missing"
        }
        let digest = SHA256.hash(data: data)
        let hex = digest.prefix(8).map { String(format: "%02x", $0) }.joined()
        return "path-char-lstm.bin size=\(data.count) sha256_8=\(hex)"
    }

    @UserDefault(key: kEnableRerankDiffLogKey, defaultValue: true)
    @objc static var enableRerankDiffLog: Bool

    @objc static func toggleRerankDiffLogEnabled() -> Bool {
        enableRerankDiffLog = !enableRerankDiffLog
        return enableRerankDiffLog
    }

    @EnumUserDefault(key: kKeyboardLayoutPreferenceKey, defaultValue: KeyboardLayout.standard)
    @objc static var keyboardLayout: KeyboardLayout

    @objc static var keyboardLayoutName: String {
        keyboardLayout.name
    }

    @UserDefault(key: kBasisKeyboardLayoutPreferenceKey, defaultValue: "com.apple.keylayout.US")
    @objc static var basisKeyboardLayout: String

    @UserDefault(
        key: kFunctionKeyKeyboardLayoutPreferenceKey, defaultValue: "com.apple.keylayout.US")
    @objc static var functionKeyboardLayout: String

    @UserDefault(key: kFunctionKeyKeyboardLayoutOverrideIncludeShiftKey, defaultValue: false)
    @objc static var functionKeyKeyboardLayoutOverrideIncludeShiftKey: Bool

    @CandidateListTextSize(key: kCandidateListTextSizeKey)
    @objc static var candidateListTextSize: CGFloat

    @UserDefault(key: kSelectPhraseAfterCursorAsCandidateKey, defaultValue: false)
    @objc static var selectPhraseAfterCursorAsCandidate: Bool

    @UserDefault(key: kMoveCursorAfterSelectingCandidateKey, defaultValue: false)
    @objc static var moveCursorAfterSelectingCandidate: Bool

    @UserDefault(key: kUseHorizontalCandidateListPreferenceKey, defaultValue: false)
    @objc static var useHorizontalCandidateList: Bool

    @UserDefault(key: kChooseCandidateUsingSpaceKey, defaultValue: true)
    @objc static var chooseCandidateUsingSpace: Bool

    @UserDefault(key: kChineseConversionEnabledKey, defaultValue: false)
    @objc static var chineseConversionEnabled: Bool

    @objc static func toggleChineseConversionEnabled() -> Bool {
        chineseConversionEnabled = !chineseConversionEnabled
        return chineseConversionEnabled
    }

    @UserDefault(key: kHalfWidthPunctuationEnabledKey, defaultValue: false)
    @objc static var halfWidthPunctuationEnabled: Bool

    @objc static func toggleHalfWidthPunctuationEnabled() -> Bool {
        halfWidthPunctuationEnabled = !halfWidthPunctuationEnabled
        return halfWidthPunctuationEnabled
    }

    @UserDefault(key: kEscToCleanInputBufferKey, defaultValue: false)
    @objc static var escToCleanInputBuffer: Bool

    @UserDefault(key: kKeepReadingUponCompositionError, defaultValue: false)
    @objc static var keepReadingUponCompositionError: Bool

    // MARK: Optional settings

    @UserDefault(key: kCandidateTextFontName, defaultValue: nil)
    @objc static var candidateTextFontName: String?

    @UserDefault(key: kCandidateKeyLabelFontName, defaultValue: nil)
    @objc static var candidateKeyLabelFontName: String?

    @UserDefault(key: kCandidateKeys, defaultValue: kDefaultKeys)
    @objc static var candidateKeys: String

    @objc static var defaultCandidateKeys: String {
        kDefaultKeys
    }
    @objc static var suggestedCandidateKeys: [String] {
        [kDefaultKeys, "asdfghjkl", "asdfzxcvb"]
    }

    static func validate(candidateKeys: String) throws {
        let trimmed = candidateKeys.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            throw CandidateKeyError.empty
        }
        if !trimmed.canBeConverted(to: .ascii) {
            throw CandidateKeyError.invalidCharacters
        }
        if trimmed.contains(" ") {
            throw CandidateKeyError.containSpace
        }
        if trimmed.count < 4 {
            throw CandidateKeyError.tooShort
        }
        if trimmed.count > 15 {
            throw CandidateKeyError.tooLong
        }
        let set = Set(Array(trimmed))
        if set.count != trimmed.count {
            throw CandidateKeyError.duplicatedCharacters
        }
    }

    enum CandidateKeyError: Error, LocalizedError {
        case empty
        case invalidCharacters
        case containSpace
        case duplicatedCharacters
        case tooShort
        case tooLong

        var errorDescription: String? {
            switch self {
            case .empty:
                return NSLocalizedString("Candidates keys cannot be empty.", comment: "")
            case .invalidCharacters:
                return NSLocalizedString(
                    "Candidate keys can only contain Latin characters and numbers.", comment: "")
            case .containSpace:
                return NSLocalizedString("Candidate keys cannot contain space.", comment: "")
            case .duplicatedCharacters:
                return NSLocalizedString("There should not be duplicated keys.", comment: "")
            case .tooShort:
                return NSLocalizedString(
                    "Candidate keys cannot be shorter than 4 characters.", comment: "")
            case .tooLong:
                return NSLocalizedString(
                    "Candidate keys cannot be longer than 15 characters.", comment: "")
            }
        }
    }
}

/// An enumeration representing keys used for moving the cursor in the
/// application.
@objc enum MovingCursorKey: Int {
    case disabled = 0
    case useJK = 1
    case useHL = 2
}

extension MovingCursorKey {
    var name: String {
        switch self {
        case .disabled: "Disabled"
        case .useJK: "J/K"
        case .useHL: "H/L"
        }
    }
}

extension Preferences {
    /// Whether allows moving the cursor by J/K or H/L keys, when the candidate
    /// window is presented.
    @EnumUserDefault(key: kAllowMovingCursorWhenChoosingCandidates, defaultValue: .disabled)
    @objc static var allowMovingCursorWhenChoosingCandidates: MovingCursorKey
}

extension Preferences {
    /// The conversion style.
    ///
    /// - 0: convert the output
    /// - 1: convert the phrase models.
    @EnumUserDefault(key: kChineseConversionStyleKey, defaultValue: ChineseConversionStyle.output)
    @objc static var chineseConversionStyle: ChineseConversionStyle

    @objc static var chineseConversionStyleName: String {
        chineseConversionStyle.name
    }
}

extension Preferences {

    @UserDefault(key: kPhraseReplacementEnabledKey, defaultValue: false)
    @objc static var phraseReplacementEnabled: Bool

    @objc static func togglePhraseReplacementEnabled() -> Bool {
        phraseReplacementEnabled = !phraseReplacementEnabled
        return phraseReplacementEnabled
    }

    @UserDefault(key: kAssociatedPhrasesEnabledKey, defaultValue: false)
    @objc static var associatedPhrasesEnabled: Bool

    @objc static func toggleAssociatedPhrasesEnabled() -> Bool {
        associatedPhrasesEnabled = !associatedPhrasesEnabled
        return associatedPhrasesEnabled
    }

    @UserDefault(key: kShiftEnterEnabledKey, defaultValue: true)
    @objc static var shiftEnterEnabled: Bool

    @UserDefault(key: kRepeatedPunctuationToSelectCandidateEnabledKey, defaultValue: false)
    @objc static var repeatedPunctuationToSelectCandidateEnabled: Bool


    // Phase 2:句末自動 L2 整句校正。實驗功能,預設關閉。


    // 引擎層情境化 walk:語料詞 bigram ContextModel 讓上下文參與 walk 的路徑競爭
    // (只重排既有候選,不生成)。v2.3.0 起預設開啟;需 bundle 內有
    // word-bigrams.tsv 才會生效。個人化 soft 分數與此開關獨立(有 cache 才掛)。
    @UserDefault(key: kEnableContextualWalkKey, defaultValue: true)
    @objc static var enableContextualWalk: Bool

    @objc static func toggleContextualWalkEnabled() -> Bool {
        enableContextualWalk = !enableContextualWalk
        return enableContextualWalk
    }

    /// Mozc-style n-best + PathScorer fusion after ContextModel walk.
    /// Default ON since v2.6.0: candidate A = v2c int8 char-LSTM reranker with
    /// prefix-trie + BLAS batched scoring (tw538 387/537 @ ~45ms, N=10, ν=0.75).
    /// Set to false (or toggle via the menu) to fall back to the pre-rerank
    /// walk path bit-identically.
    @UserDefault(key: kEnableNeuralPathRerankKey, defaultValue: true)
    @objc static var enableNeuralPathRerank: Bool

    @objc static func toggleNeuralPathRerankEnabled() -> Bool {
        enableNeuralPathRerank = !enableNeuralPathRerank
        return enableNeuralPathRerank
    }

    /// Interpolation weight ν for final_score = walk_score + ν · path_scorer.
    /// Default 0.75 since v2.6.0: peak on tw538 for the shipped v2c reranker
    /// (nu 0.5→386, 0.75→387, 1.0→385; see shipping-latency-pareto-tw538.md).
    @UserDefault(key: kNeuralPathRerankNuKey, defaultValue: 0.75)
    @objc static var neuralPathRerankNu: Double

    // MARK: - Sentence-end 定案 triggers (canonical product rule)
    // Enabled trigger / Enter while underlined → 改字 + 收底線 (hard commit), 不送出.
    // Enter after 定案 (no underline) → 送出 (pass key to host).
    // Enter is not a toggle in this group.

    /// Legacy unused for Enter gating (Enter always 定案 when composing).
    @UserDefault(key: kSentenceEndTriggerEnterKey, defaultValue: true)
    @objc static var sentenceEndTriggerEnter: Bool

    @objc static func toggleSentenceEndTriggerEnter() -> Bool {
        sentenceEndTriggerEnter = !sentenceEndTriggerEnter
        return sentenceEndTriggerEnter
    }

    /// Full-width period （。） → 定案 (改字 + 收底線). Default OFF: insert punct only.
    @UserDefault(key: kSentenceEndTriggerPeriodKey, defaultValue: false)
    @objc static var sentenceEndTriggerPeriod: Bool

    @objc static func toggleSentenceEndTriggerPeriod() -> Bool {
        sentenceEndTriggerPeriod = !sentenceEndTriggerPeriod
        return sentenceEndTriggerPeriod
    }

    /// Full-width comma （，） → 定案 (改字 + 收底線). Default OFF: insert punct only.
    @UserDefault(key: kSentenceEndTriggerCommaKey, defaultValue: false)
    @objc static var sentenceEndTriggerComma: Bool

    @objc static func toggleSentenceEndTriggerComma() -> Bool {
        sentenceEndTriggerComma = !sentenceEndTriggerComma
        return sentenceEndTriggerComma
    }

    /// Idle pause → 定案 (改字 + 收底線, 不送出). Default ON.
    @UserDefault(key: kSentenceEndPauseEnabledKey, defaultValue: true)
    @objc static var sentenceEndPauseEnabled: Bool

    @objc static func toggleSentenceEndPauseEnabled() -> Bool {
        sentenceEndPauseEnabled = !sentenceEndPauseEnabled
        return sentenceEndPauseEnabled
    }

    /// Idle pause (ms) before 定案 when pause is enabled.
    /// Default 800ms; stored value is always clamped to ≥ 200ms.
    @UserDefault(key: kSentenceEndPauseMsKey, defaultValue: 800)
    private static var _sentenceEndPauseMsRaw: Int

    @objc static var sentenceEndPauseMs: Int {
        get {
            max(ShippingRerankConstants.sentenceEndPauseMsMin, _sentenceEndPauseMsRaw)
        }
        set {
            _sentenceEndPauseMsRaw = max(
                ShippingRerankConstants.sentenceEndPauseMsMin, newValue)
        }
    }

    /// Collect manual candidate picks as training samples (difficult forks).
    @UserDefault(key: kEnableManualCorrectionLogKey, defaultValue: true)
    @objc static var enableManualCorrectionLog: Bool

    @objc static func toggleManualCorrectionLog() -> Bool {
        enableManualCorrectionLog = !enableManualCorrectionLog
        return enableManualCorrectionLog
    }

}

@objc enum ControlEnterOutput: Int {
    case off = 0
    case bpmfReading = 1
    case htmlRuby = 2
    case brailleUnicode = 3
    case hanyuPinyin = 4
    case brailleAscii = 5
}

extension ControlEnterOutput {
    var name: String {
        switch self {
        case .off: "Off"
        case .bpmfReading: "Bopomofo Reading"
        case .htmlRuby: "HTML Ruby Text"
        case .brailleUnicode: "Taiwanese Braille (Unicode)"
        case .brailleAscii: "Taiwanese Braille (ASCII)"
        case .hanyuPinyin: "Hanyu Pinyin"
        }
    }
}

extension Preferences {
    /// The behavior of pressing letter keys.
    ///
    /// - 0: Output upper-cased letters directly.
    /// - 1: Output lower-cased letters in the composing buffer.
    @UserDefault(key: kLetterBehaviorKey, defaultValue: 0)
    @objc static var letterBehavior: Int

    /// The behavior of pressing Ctrl + Enter.
    ///
    /// - 0: Disabled.
    /// - 1: Output BPMF readings.
    @EnumUserDefault(key: kControlEnterOutputKey, defaultValue: .off)
    @objc static var controlEnterOutput: ControlEnterOutput
}

@objc class UserPhraseLocationHelper: NSObject {
    @objc static var defaultUserPhraseLocation: String {
        let paths = NSSearchPathForDirectoriesInDomains(
            .applicationSupportDirectory, .userDomainMask, true)
        let appSupportPath = paths.first!
        return (appSupportPath as NSString).appendingPathComponent("iBopomofo")
    }
}

extension NSNotification.Name {
    static var userPhraseLocationDidChange = NSNotification.Name(
        rawValue: "UserPhraseLocationDidChangeNotification")
}

extension Preferences {

    static func postUserPhraseLocationNotification() {
        let location: String = {
            if !useCustomUserPhraseLocation {
                return UserPhraseLocationHelper.defaultUserPhraseLocation
            }
            if customUserPhraseLocation.isEmpty {
                return UserPhraseLocationHelper.defaultUserPhraseLocation
            }
            return customUserPhraseLocation
        }()
        let notification = Notification(
            name: .userPhraseLocationDidChange, object: self,
            userInfo: [
                "location": location
            ])
        NotificationQueue.default.dequeueNotifications(matching: notification, coalesceMask: 0)
        NotificationQueue.default.enqueue(notification, postingStyle: .now)
    }

    @UserDefault(key: kUseCustomUserPhraseLocation, defaultValue: false)
    @objc static var useCustomUserPhraseLocation: Bool {
        didSet {
            postUserPhraseLocationNotification()
        }
    }

    @UserDefault(key: kCustomUserPhraseLocation, defaultValue: "")
    @objc static var customUserPhraseLocation: String {
        didSet {
            postUserPhraseLocationNotification()
        }
    }
}

extension Preferences {
    static func defaultAddPhraseHookPath() -> String {
        let bundle = Bundle.main
        let hookPath = bundle.path(forResource: "add-phrase-hook", ofType: "sh")
        return hookPath!
    }

    @UserDefault(key: kAddPhraseHookEnabledKey, defaultValue: false)
    @objc static var addPhraseHookEnabled: Bool

    @UserDefaultWithFunction(
        key: kAddPhraseHookPath, defaultValueFunction: defaultAddPhraseHookPath)
    @objc static var addPhraseHookPath: String
}

extension Preferences {
    @UserDefault(key: kSelectCandidateWithNumericKeypad, defaultValue: false)
    @objc static var selectCandidateWithNumericKeypad: Bool
}

extension Preferences {
    @UserDefault(key: kBig5InputEnabledKey, defaultValue: true)
    @objc static var big5InputEnabled: Bool
}

extension Preferences {
    @UserDefault(key: kBeepUponInputErrorKey, defaultValue: true)
    @objc static var beepUponInputError: Bool
}

extension Preferences {
    @UserDefault(key: kEnableUserPhrasesInPlainBopomofo, defaultValue: false)
    @objc static var enableUserPhrasesInPlainBopomofo: Bool
}

extension Preferences {
    @UserDefault(key: kAllowChangingPriorTone, defaultValue: false)
    @objc static var allowChangingPriorTone: Bool
}

extension Preferences {
    // Whether to enable Bopomofo Font Annotation Support.
    @UserDefault(key: kBopomofoFontAnnotationSupportEnabled, defaultValue: false)
    @objc static var bopomofoFontAnnotationSupportEnabled: Bool

    @objc static func toggleBopomofoFontAnnotationSupportEnabled() -> Bool {
        bopomofoFontAnnotationSupportEnabled = !bopomofoFontAnnotationSupportEnabled
        return bopomofoFontAnnotationSupportEnabled
    }

    // Whether to show the "Bopomofo Font Annotation Support" toggle in the input menu.
    @UserDefault(key: kShowBopomofoFontAnnotationSupportItemInInputMenu, defaultValue: false)
    @objc static var showBopomofoFontAnnotationSupportItemInInputMenu: Bool

    // Whether at first launch, we have checked if there are any bpmfvs-supporting fonts installed,
    // and enable showBopomofoFontAnnotationSupportItemInInputMenu as a result. No more check is
    // performed once this flag is turned to true.
    @UserDefault(
        key: kBopomofoFontAnnotationSupportMenuItemEnabledByInstalledFontsCheck_V1,
        defaultValue: false)
    @objc static var bopomofoFontAnnotationSupportMenuItemEnabledByInstalledFontsCheck_V1: Bool
}

extension Preferences {
    static func createReport() -> String {
        var lines: [String] = []
        lines.append("- iBopomofo Settings")
        lines.append("  - Keyboard Layout: \(Preferences.keyboardLayout.name)")
        lines.append("  - Basis Keyboard Layout: \(Preferences.basisKeyboardLayout)")
        lines.append("  - Function Keyboard Layout: \(Preferences.functionKeyboardLayout)")
        lines.append("  - Candidate Keys: \(Preferences.candidateKeys)")
        lines.append(
            "  - Selection Mode: \(Preferences.selectPhraseAfterCursorAsCandidate ? "After Cursor" : "Before Cursor")"
        )
        lines.append(
            "  - Move Cursor After Selecting Candidate: \(Preferences.moveCursorAfterSelectingCandidate ? "Enabled" : "Disabled")"
        )
        lines.append(
            "  - Candidate Window: \(Preferences.useHorizontalCandidateList ? "Horizontal" : "Vertical")"
        )
        lines.append(
            "  - Chinese Conversion: \(Preferences.chineseConversionEnabled ? "Enabled" : "Disabled")"
        )
        lines
            .append(
                "  - Chinese Conversion Style: \(Preferences.chineseConversionStyle.name)"
            )
        lines.append(
            "  - Punctuations: \(Preferences.halfWidthPunctuationEnabled ? "Half-width" : "Full-width")"
        )
        lines.append(
            "  - Select Candidate With Numeric Keyboard: \(Preferences.selectCandidateWithNumericKeypad ? "Enabled" : "Disabled")"
        )
        lines.append(
            "  - Allow Ctrl + ` For Big5 Input: \(Preferences.big5InputEnabled ? "Enabled" : "Disabled")"
        )
        lines.append(
            "  - Phrase Replacement: \(Preferences.phraseReplacementEnabled ? "Enabled" : "Disabled")"
        )
        lines.append(
            "  - Associated Phrases (iBopomofo): \(Preferences.associatedPhrasesEnabled ? "Enabled" : "Disabled")"
        )
        lines.append(
            "  - Associated Phrases (Plain Bopomofo): \(Preferences.enableUserPhrasesInPlainBopomofo ? "Enabled" : "Disabled")"
        )

        lines.append("  - Letter Keys: \(Preferences.letterBehavior)")
        lines.append("  - Ctrl + Enter Key: \(Preferences.controlEnterOutput.name)")
        lines.append(
            "  - Shift + Enter Key For Associated Phrases: \(Preferences.shiftEnterEnabled ? "Enabled" : "Disabled")"
        )
        lines.append(
            "  - Repeated Keys For Next Candidate: \(Preferences.repeatedPunctuationToSelectCandidateEnabled ? "Enabled" : "Disabled")"
        )
        lines.append(
            "  - Add Phrase Hook: \(Preferences.addPhraseHookEnabled ? "Enabled" : "Disabled")")
        lines.append("  - Add Phrase Hook Path: \(Preferences.addPhraseHookPath)")
        lines.append(
            "  - Beep Upon Errors: \(Preferences.beepUponInputError ? "Enabled" : "Disabled")")
        lines.append(
            "  - Moving Cursor When Choosing Candidates: \(Preferences.allowMovingCursorWhenChoosingCandidates)"
        )
        lines.append(
            "  - Contextual Walk: \(Preferences.enableContextualWalk ? "Enabled" : "Disabled")"
        )
        lines.append(
            "  - Neural Path Rerank: \(Preferences.enableNeuralPathRerank ? "Enabled" : "Disabled") ν=\(Preferences.neuralPathRerankNu)"
        )
        return lines.joined(separator: "\n")
    }
}
