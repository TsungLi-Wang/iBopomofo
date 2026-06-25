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

import CandidateUI
import Cocoa
import InputMethodKit
import InputSourceHelper
import NotifierUI
import OpenCCBridge
import SystemCharacterInfo
import TooltipUI

extension Bool {
    fileprivate var state: NSControl.StateValue {
        self ? .on : .off
    }
}

private let kMinKeyLabelSize: CGFloat = 10

internal var gCurrentCandidateController: CandidateController?

extension CandidateController {
    static let horizontal = HorizontalCandidateController()
    static let vertical = VerticalCandidateController()
}

@objc(McBopomofoInputMethodController)
class McBopomofoInputMethodController: IMKInputController {

    private static let tooltipController = TooltipController()

    // MARK: -

    var currentClient: Any?
    var keyHandler: KeyHandler = KeyHandler()
    var state: InputState = InputState.Empty()
    lazy var charInfo: SystemCharacterInfo? = try? SystemCharacterInfo()
    var aiCandidateSuggestion: AICandidateSuggestion?
    var aiCandidateRequestSerial: UInt = 0
    var aiCandidateDidNotifyLocalServerLoading = false
    var aiCandidateRerankedValue: String?
    var aiCandidateRerankWorkItem: DispatchWorkItem?
    var aiCandidateServerRetryWorkItem: DispatchWorkItem?
    // Phase 2:句末自動 L2 整句校正(只提示、不直接 commit)的狀態。
    var aiAutoCorrectionSuggestion: AICandidateSuggestion?
    var aiAutoCorrectionRequestSerial: UInt = 0
    var aiAutoCorrectionDidNotifyLocalServerLoading = false
    var aiAutoCorrectionWorkItem: DispatchWorkItem?
    var aiAutoCorrectionServerRetryWorkItem: DispatchWorkItem?

    // Phase 3:語音輸入 push-to-talk。連按兩下「右 Shift」開始/結束。改用右 Shift
    // 是因為 macOS 內建聽寫常綁「連按兩下 Control」,改一顆系統沒綁的鍵可永久零衝突、
    // 不必使用者改任何系統設定。只認「兩次乾淨的右 Shift 單擊」——兩擊之間不可夾雜
    // 其他按鍵,也不可同時按其他修飾鍵。
    var voicePTTRightShiftWasDown = false
    var voicePTTTapContaminated = false
    var voicePTTLastCleanTapTime: TimeInterval = 0
    var voiceInputStopNotificationPending = false
    static var voiceInputSourceIDPendingAuthorization: String?

    // Share the stored issues, so a set of issues is shown as notification only once.
    static var latestUserFileIssues: [String] = []

    // MARK: - IMKInputController methods

    override init!(server: IMKServer!, delegate: Any!, client inputClient: Any!) {
        super.init(server: server, delegate: delegate, client: inputClient)
        keyHandler.delegate = self
    }

    override func menu() -> NSMenu! {
        let menu = NSMenu(title: "Input Method Menu")

        let chineseConversionItem = menu.addItem(
            withTitle: NSLocalizedString("Convert to Simplified Chinese", comment: ""),
            action: #selector(toggleChineseConverter(_:)), keyEquivalent: "g")
        chineseConversionItem.keyEquivalentModifierMask = [.command, .control]
        chineseConversionItem.state = Preferences.chineseConversionEnabled.state

        let halfWidthPunctuationItem = menu.addItem(
            withTitle: NSLocalizedString("Use Half-Width Punctuations", comment: ""),
            action: #selector(toggleHalfWidthPunctuation(_:)), keyEquivalent: "h")
        halfWidthPunctuationItem.keyEquivalentModifierMask = [.command, .control]
        halfWidthPunctuationItem.state = Preferences.halfWidthPunctuationEnabled.state
        let associatedPhrasesItem = menu.addItem(
            withTitle: NSLocalizedString("Associated Phrases", comment: ""),
            action: #selector(toggleAssociatedPhrasesEnabled(_:)), keyEquivalent: "")
        associatedPhrasesItem.state = Preferences.associatedPhrasesEnabled.state

        let aiCandidateRerankItem = menu.addItem(
            withTitle: NSLocalizedString("AI Candidate Suggestions", comment: ""),
            action: #selector(toggleAICandidateRerankEnabled(_:)), keyEquivalent: "")
        aiCandidateRerankItem.state = Preferences.enableAICandidateRerank.state

        let aiAutoCorrectionItem = menu.addItem(
            withTitle: NSLocalizedString("AI Auto-Correction (Experimental)", comment: ""),
            action: #selector(toggleAIAutoCorrectionEnabled(_:)), keyEquivalent: "")
        aiAutoCorrectionItem.state = Preferences.enableAIAutoCorrection.state

        let voiceInputTitle =
            VoiceInputManager.shared.isRecording
            ? NSLocalizedString("Stop Voice Input", comment: "")
            : NSLocalizedString("Voice Input (Experimental)", comment: "")
        menu.addItem(
            withTitle: voiceInputTitle,
            action: #selector(toggleVoiceInput(_:)), keyEquivalent: "")

        // AI 整句修正模型切換器(⌘↵ 觸發時使用;可隨時切換)
        menu.addItem(NSMenuItem.separator())
        let aiNames = [
            "Codex(較慢)", "Claude Haiku(快)", "Claude Opus(最準)",
            "本機 AI(內建・離線)",
        ]
        let currentBackend = McBopomofoInputMethodController.aiBackend
        let currentName =
            (currentBackend >= 0 && currentBackend < aiNames.count)
            ? aiNames[currentBackend] : "?"
        // 標題直接顯示目前選的模型,不靠勾勾(輸入法選單的勾勾渲染不一定可靠)。
        let aiHeader = menu.addItem(
            withTitle: "AI 修正模型:目前【\(currentName)】", action: nil, keyEquivalent: "")
        aiHeader.isEnabled = false
        // 每個後端用各自的 selector,不靠 sender.tag。輸入法選單跨 process 代管,
        // 回傳的 sender 不是我們建立的 NSMenuItem,讀 tag 會失敗(這也是勾勾/圖示不可靠的同一個原因)。
        let aiSelectors: [Selector] = [
            #selector(selectAIBackendCodex(_:)),
            #selector(selectAIBackendHaiku(_:)),
            #selector(selectAIBackendOpus(_:)),
            #selector(selectAIBackendLocal(_:)),
        ]
        for (tag, name) in aiNames.enumerated() {
            // 用標準勾勾(.state)標示目前選用的後端。選單項是我們自己在開選單時建的
            // NSMenuItem,直接設 .state 渲染正常(先前不可靠的是「讀回 sender 的狀態」,非設定本身)。
            let item = menu.addItem(
                withTitle: name, action: aiSelectors[tag],
                keyEquivalent: "")
            item.state = (currentBackend == tag) ? .on : .off
            item.tag = tag
        }
        // 開啟 AI 修正設定視窗(填 API key / 端點 / 模型;任何 clone 下來的人自行設定)。
        menu.addItem(
            withTitle: "AI 修正設定…", action: #selector(openAISettings(_:)), keyEquivalent: "")

        let inputMode = keyHandler.inputMode

        // Only Bopomofo mode supports Bopomofo Font Annotation. If support is
        // on, ensure that the user has a way to disable it. Otherwise, only
        // show the item when it is set to show in the input menu.
        if inputMode == .bopomofo
            && (Preferences.showBopomofoFontAnnotationSupportItemInInputMenu
                || Preferences.bopomofoFontAnnotationSupportEnabled)
        {
            let bopomofoFontAnnotationSupportItem = menu.addItem(
                withTitle: NSLocalizedString("Bopomofo Font Annotation Support", comment: ""),
                action: #selector(toggleBopomofoFontAnnotationSupport(_:)), keyEquivalent: "")
            bopomofoFontAnnotationSupportItem.state =
                Preferences.bopomofoFontAnnotationSupportEnabled.state
        }

        let optionKeyPressed = NSEvent.modifierFlags.contains(.option)
        if inputMode == .bopomofo && optionKeyPressed {
            let phaseReplacementItem = menu.addItem(
                withTitle: NSLocalizedString("Use Phrase Replacement", comment: ""),
                action: #selector(togglePhraseReplacement(_:)), keyEquivalent: "")
            phaseReplacementItem.state = Preferences.phraseReplacementEnabled.state
        }

        menu.addItem(NSMenuItem.separator())
        menu.addItem(
            withTitle: NSLocalizedString("User Phrases", comment: ""), action: nil,
            keyEquivalent: "")

        if inputMode == .plainBopomofo {
            if Preferences.enableUserPhrasesInPlainBopomofo {
                menu.addItem(
                    withTitle: NSLocalizedString("Edit User Phrases", comment: ""),
                    action: #selector(openUserPhrasesPlainBopomofo(_:)), keyEquivalent: "")
            }
            menu.addItem(
                withTitle: NSLocalizedString("Edit Excluded Phrases", comment: ""),
                action: #selector(openExcludedPhrasesPlainBopomofo(_:)), keyEquivalent: "")
        } else {
            menu.addItem(
                withTitle: NSLocalizedString("Edit User Phrases", comment: ""),
                action: #selector(openUserPhrases(_:)), keyEquivalent: "")
            menu.addItem(
                withTitle: NSLocalizedString("Edit Excluded Phrases", comment: ""),
                action: #selector(openExcludedPhrasesMcBopomofo(_:)), keyEquivalent: "")
            if optionKeyPressed {
                menu.addItem(
                    withTitle: NSLocalizedString("Edit Phrase Replacement Table", comment: ""),
                    action: #selector(openPhraseReplacementMcBopomofo(_:)), keyEquivalent: "")
            }
        }

        menu.addItem(
            withTitle: NSLocalizedString("Reload User Phrases", comment: ""),
            action: #selector(reloadUserPhrases(_:)), keyEquivalent: "")

        if !McBopomofoInputMethodController.latestUserFileIssues.isEmpty {
            // Setting menuItem.image does not work in input method menus even on macOS 26,
            // so we just use the alert emoji in the menu item title.
            let menuItem = NSMenuItem(
                title: NSLocalizedString("Show Issues in User Files ⚠️", comment: ""),
                action: #selector(showUserFileIssues(_:)), keyEquivalent: "")
            menu.addItem(menuItem)
        }

        menu.addItem(NSMenuItem.separator())

        menu.addItem(
            withTitle: NSLocalizedString("McBopomofo Preferences", comment: ""),
            action: #selector(showPreferences(_:)), keyEquivalent: "")
        menu.addItem(
            withTitle: NSLocalizedString("Check for Updates…", comment: ""),
            action: #selector(checkForUpdate(_:)), keyEquivalent: "")
        menu.addItem(
            withTitle: NSLocalizedString("About McBopomofo…", comment: ""),
            action: #selector(showAbout(_:)), keyEquivalent: "")
        return menu
    }

    // MARK: - IMKStateSetting protocol methods

    override func activateServer(_ client: Any!) {
        UserDefaults.standard.synchronize()

        // Override the keyboard layout. Use US if not set.
        (client as? IMKTextInput)?.overrideKeyboard(
            withKeyboardNamed: Preferences.basisKeyboardLayout)
        // reset the state
        currentClient = client

        keyHandler.clear()
        keyHandler.syncWithPreferences()

        (NSApp.delegate as? AppDelegate)?.checkForUpdate()
    }

    override func deactivateServer(_ client: Any!) {
        currentClient = nil
        keyHandler.clear()
        self.handle(state: .Deactivated(), client: client)
    }

    override func setValue(_ value: Any!, forTag tag: Int, client: Any!) {
        let newInputMode = InputMode(rawValue: value as? String ?? InputMode.bopomofo.rawValue)
        LanguageModelManager.loadDataModel(newInputMode)
        if keyHandler.inputMode != newInputMode {
            UserDefaults.standard.synchronize()
            // Remember to override the keyboard layout again -- treat this as an activate event.
            (client as? IMKTextInput)?.overrideKeyboard(
                withKeyboardNamed: Preferences.basisKeyboardLayout)
            keyHandler.clear()
            keyHandler.inputMode = newInputMode
            self.handle(state: .Empty(), client: client)
        }

        // Since setValue is called after activateServer, show user file issues here, if any.
        checkUserFileIssues()
    }

    // MARK: - IMKServerInput protocol methods

    override func commitComposition(_ client: Any!) {
        keyHandler.handleForceCommit(stateCallback: { newState in
            self.handle(state: newState, client: client)
        })
    }

    override func recognizedEvents(_ sender: Any!) -> Int {
        let events: NSEvent.EventTypeMask = [.keyDown, .keyUp, .flagsChanged]
        return Int(events.rawValue)
    }

    override func handle(_ maybeEvent: NSEvent!, client: Any!) -> Bool {
        // nil may be passed, applefeedback://FB11472618
        guard let event = maybeEvent else {
            commitComposition(client)
            return false
        }

        // Phase 3 push-to-talk:任何實體按鍵都中斷「連按兩下右 Shift」的判定:
        // 在右 Shift 按住期間打字讓本次點擊不乾淨(排除 ⇧+字母打大寫等),
        // 兩次右 Shift 點擊之間打字則清掉前一擊(必須是連續兩下純右 Shift)。
        if event.type == .keyDown {
            if voicePTTRightShiftWasDown {
                voicePTTTapContaminated = true
            }
            voicePTTLastCleanTapTime = 0
        }

        // Phase 3 push-to-talk:偵測「連按兩下乾淨的右 Shift」以開始/結束語音輸入。
        if event.type == .flagsChanged {
            detectVoicePushToTalkRightShiftDoubleTap(event, client: client)
        }

        // AI 整句修正熱鍵:⌘ + Return(keyCode 36)。只在有 composing 內容時觸發。
        if event.modifierFlags.contains(.command), event.keyCode == 36,
            let inputting = state as? InputState.Inputting,
            !inputting.composingBuffer.isEmpty
        {
            triggerAICorrection(guess: inputting.composingBuffer, client: client)
            return true
        }

        if event.keyCode == 48,
            acceptAICandidateSuggestionFromCandidateWindowIfAvailable(client: client)
                || acceptAICandidateSuggestionIfAvailable(client: client)
                || acceptAIAutoCorrectionSuggestionIfAvailable(client: client)
        {
            return true
        }

        if event.type == .flagsChanged {
            if state is InputState.Empty {
                return false
            }
            // Handle key up events during active input state.
            //
            // This prevents double-space from affecting the current input.
            // While macOS may normally insert a period on double space, this
            // should be suppressed when there is an active composing buffer or
            // candidate window.
            return true
        }

        if event.type == .flagsChanged {
            let functionKeyKeyboardLayoutID = Preferences.functionKeyboardLayout
            let basisKeyboardLayoutID = Preferences.basisKeyboardLayout

            if functionKeyKeyboardLayoutID == basisKeyboardLayoutID {
                return false
            }

            let includeShift = Preferences.functionKeyKeyboardLayoutOverrideIncludeShiftKey
            let notShift = NSEvent.ModifierFlags(rawValue: ~(NSEvent.ModifierFlags.shift.rawValue))
            if event.modifierFlags.contains(notShift)
                || (event.modifierFlags.contains(.shift) && includeShift)
            {
                (client as? IMKTextInput)?.overrideKeyboard(
                    withKeyboardNamed: functionKeyKeyboardLayoutID)
                return false
            }
            (client as? IMKTextInput)?.overrideKeyboard(withKeyboardNamed: basisKeyboardLayoutID)
            return false
        }

        var textFrame = NSRect.zero
        let attributes: [AnyHashable: Any]? = (client as? IMKTextInput)?.attributes(
            forCharacterIndex: 0, lineHeightRectangle: &textFrame)
        let useVerticalMode =
            (attributes?["IMKTextOrientation"] as? NSNumber)?.intValue == 0 || false
        let input = KeyHandlerInput(event: event, isVerticalMode: useVerticalMode)

        let result = keyHandler.handle(input: input, state: state) { newState in
            self.handle(state: newState, client: client)
        } errorCallback: {
            if Preferences.beepUponInputError {
                NSSound.beep()
            }
        }
        return result
    }

    // MARK: - Menu Items

    @objc override func showPreferences(_ sender: Any?) {
        super.showPreferences(sender)
    }

    @objc func toggleChineseConverter(_ sender: Any?) {
        let enabled = Preferences.toggleChineseConversionEnabled()
        NotifierController.notify(
            message: enabled
                ? NSLocalizedString("Chinese Conversion On", comment: "")
                : NSLocalizedString("Chinese Conversion Off", comment: ""))
        if let currentClient = currentClient {
            keyHandler.clear()
            self.handle(state: InputState.Empty(), client: currentClient)
        }
    }

    @objc func toggleHalfWidthPunctuation(_ sender: Any?) {
        let enabled = Preferences.toggleHalfWidthPunctuationEnabled()
        NotifierController.notify(
            message: enabled
                ? NSLocalizedString("Half-Width Punctuation On", comment: "")
                : NSLocalizedString("Half-Width Punctuation Off", comment: ""))
        if let currentClient = currentClient {
            keyHandler.clear()
            self.handle(state: InputState.Empty(), client: currentClient)
        }
    }

    @objc func toggleAssociatedPhrasesEnabled(_ sender: Any?) {
        _ = Preferences.toggleAssociatedPhrasesEnabled()
    }

    @objc func toggleAICandidateRerankEnabled(_ sender: Any?) {
        _ = Preferences.toggleAICandidateRerankEnabled()
    }

    @objc func toggleAIAutoCorrectionEnabled(_ sender: Any?) {
        let enabled = Preferences.toggleAIAutoCorrectionEnabled()
        if !enabled {
            resetAIAutoCorrectionState()
        }
    }

    /// Phase 3 push-to-talk:偵測「連按兩下乾淨的右 Shift」(keyCode 60)。乾淨 = 兩次
    /// 單擊之間不夾其他按鍵、也不同時按其他修飾鍵。改用右 Shift 而非 Control,是為了
    /// 永久避開 macOS 內建聽寫常綁的「連按兩下 Control」,使用者不必改任何系統設定。
    private func detectVoicePushToTalkRightShiftDoubleTap(_ event: NSEvent, client: Any!) {
        let rightShiftKeyCode: UInt16 = 60
        let otherModifiers: NSEvent.ModifierFlags = [.command, .option, .control, .function, .capsLock]
        let hasOther = !event.modifierFlags.isDisjoint(with: otherModifiers)

        // 等待第二擊期間若再按下其他修飾鍵,本次點擊視為不乾淨。
        if voicePTTRightShiftWasDown && hasOther {
            voicePTTTapContaminated = true
        }

        // 只處理「右 Shift」這顆鍵的 flagsChanged;其他修飾鍵不改變 wasDown 狀態。
        guard event.keyCode == rightShiftKeyCode else { return }

        let shiftDown = event.modifierFlags.contains(.shift)
        if shiftDown && !voicePTTRightShiftWasDown {
            // Rising edge:右 Shift 按下,開始一次點擊判定。
            voicePTTTapContaminated = hasOther
        } else if !shiftDown && voicePTTRightShiftWasDown {
            // Falling edge:右 Shift 放開,完成一次點擊。
            if voicePTTTapContaminated {
                voicePTTLastCleanTapTime = 0
            } else {
                let now = event.timestamp
                if voicePTTLastCleanTapTime > 0, now - voicePTTLastCleanTapTime <= 0.5 {
                    voicePTTLastCleanTapTime = 0
                    toggleVoiceInput(nil)
                } else {
                    voicePTTLastCleanTapTime = now
                }
            }
        }
        voicePTTRightShiftWasDown = shiftDown
    }

    // Phase 3:語音輸入。選單或「連按兩下右 Shift」push-to-talk 觸發,獨立於打字流程。
    // 辨識出的最終文字走既有 commit 出口落地,不繞 KeyHandler / InputState。
    @objc func toggleVoiceInput(_ sender: Any?) {
        let manager = VoiceInputManager.shared
        if manager.isRecording {
            voiceInputStopNotificationPending = true
            manager.stop()
            return
        }
        manager.onError = { [weak self] message in
            self?.voiceInputStopNotificationPending = false
            NotifierController.notify(message: message)
        }
        manager.onFinalText = { [weak self] text in
            guard let self else { return }
            guard !text.isEmpty else {
                self.voiceInputStopNotificationPending = false
                NotifierController.notify(
                    message: NSLocalizedString("No speech detected", comment: ""))
                return
            }
            let client = self.currentClient
            self.keyHandler.clear()
            self.handle(state: InputState.Committing(poppedText: text), client: client)
            self.handle(state: InputState.Empty(), client: client)
            if self.voiceInputStopNotificationPending {
                self.voiceInputStopNotificationPending = false
                NotifierController.notify(
                    message: NSLocalizedString("Voice input stopped", comment: ""))
            }
        }
        let wasAuthorizedBeforeRequest = manager.hasRequiredAuthorization
        rememberCurrentInputSourceForVoiceAuthorization()
        manager.requestAuthorization { granted in
            Self.restoreInputSourceAfterVoiceAuthorizationIfNeeded()
            guard granted else {
                self.voiceInputStopNotificationPending = false
                NotifierController.notify(
                    message: NSLocalizedString(
                        "Microphone or speech recognition permission denied", comment: ""))
                return
            }
            guard wasAuthorizedBeforeRequest else {
                NotifierController.notify(
                    message: NSLocalizedString(
                        "Voice input is ready. Double-tap right Shift again to start speaking", comment: ""))
                return
            }
            NotifierController.notify(
                message: NSLocalizedString("Listening… double-tap right Shift to stop", comment: ""))
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                manager.start()
            }
        }
    }

    private func rememberCurrentInputSourceForVoiceAuthorization() {
        guard let bundleID = Bundle.main.bundleIdentifier,
            let source = InputSourceHelper.currentKeyboardInputSource(),
            let sourceID = InputSourceHelper.inputSourceID(for: source),
            sourceID == bundleID || sourceID.hasPrefix("\(bundleID).")
        else {
            Self.voiceInputSourceIDPendingAuthorization = nil
            return
        }
        Self.voiceInputSourceIDPendingAuthorization = sourceID
    }

    private static func restoreInputSourceAfterVoiceAuthorizationIfNeeded() {
        guard let sourceID = voiceInputSourceIDPendingAuthorization else {
            return
        }
        voiceInputSourceIDPendingAuthorization = nil

        // macOS permission panels can temporarily activate UserNotificationCenter
        // and move the active input source to ABC. Restore only when the current
        // source is still an Apple keyboard layout, and only for the source that
        // was active immediately before the authorization flow.
        restoreInputSourceAfterVoiceAuthorization(sourceID: sourceID)
        for delay in [0.0, 0.2, 0.6, 1.0, 1.6] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
                restoreInputSourceAfterVoiceAuthorization(sourceID: sourceID)
            }
        }
    }

    private static func restoreInputSourceAfterVoiceAuthorization(sourceID: String) {
        guard let current = InputSourceHelper.currentKeyboardInputSource() else {
            _ = InputSourceHelper.select(inputSourceID: sourceID)
            return
        }
        let currentID = InputSourceHelper.inputSourceID(for: current) ?? ""
        if currentID == sourceID {
            return
        }
        let currentBundle = InputSourceHelper.bundleID(for: current) ?? ""
        guard currentID.hasPrefix("com.apple.keylayout.")
            || currentBundle == "com.apple.keyboardlayout.all"
        else {
            return
        }
        _ = InputSourceHelper.select(inputSourceID: sourceID)
    }

    @objc func toggleBopomofoFontAnnotationSupport(_ sender: Any?) {
        let enabled = Preferences.toggleBopomofoFontAnnotationSupportEnabled()
        NotifierController.notify(
            message: enabled
                ? NSLocalizedString("Bopomofo Font Annotation Support On", comment: "")
                : NSLocalizedString("Bopomofo Font Annotation Support Off", comment: ""))
    }

    @objc func togglePhraseReplacement(_ sender: Any?) {
        let enabled = Preferences.togglePhraseReplacementEnabled()
        LanguageModelManager.phraseReplacementEnabled = enabled
    }

    // AI 修正模型切換:定義在主 class 本體(與其他能用的選單 action 同層),
    // 不放 extension —— IMK 選單 action 派送對 extension 裡的 @objc 不一定找得到。
    @objc func selectAIBackendCodex(_ sender: Any?) { setAIBackend(0) }
    @objc func selectAIBackendHaiku(_ sender: Any?) { setAIBackend(1) }
    @objc func selectAIBackendOpus(_ sender: Any?) { setAIBackend(2) }
    @objc func selectAIBackendLocal(_ sender: Any?) { setAIBackend(3) }

    // 開啟 AI 修正設定視窗。action 同樣放主 class 本體(IMK 選單派送對 extension 的 @objc 不一定找得到)。
    @objc func openAISettings(_ sender: Any?) {
        AISettingsWindowController.shared.showSettings()
    }

    private func setAIBackend(_ index: Int) {
        McBopomofoInputMethodController.aiBackend = index
        UserDefaults.standard.synchronize()
        // 切到本機後端:模型在就暖 server;不在就觸發首次下載(會跳通知)。切走就收掉 server 釋放 ~2GB 記憶體。
        if index == 3 {
            if LlamaServerManager.shared.isModelInstalled {
                LlamaServerManager.shared.startIfNeeded()
            } else {
                LlamaServerManager.shared.ensureModelDownloaded()
            }
        } else {
            LlamaServerManager.shared.stop()
        }
        let names = ["Codex", "Claude Haiku", "Claude Opus", "本機 AI"]
        let name = (index >= 0 && index < names.count) ? names[index] : "?"
        NotifierController.notify(message: "已切換 AI 修正模型:" + name)
    }

    @objc func checkForUpdate(_ sender: Any?) {
        (NSApp.delegate as? AppDelegate)?.checkForUpdate(forced: true)
    }

    @objc func openUserPhrases(_ sender: Any?) {
        (NSApp.delegate as? AppDelegate)?.openUserPhrases(sender)
    }

    @objc func openUserPhrasesPlainBopomofo(_ sender: Any?) {
        (NSApp.delegate as? AppDelegate)?.openUserPhrasesPlainBopomofo(sender)
    }

    @objc func openExcludedPhrasesPlainBopomofo(_ sender: Any?) {
        (NSApp.delegate as? AppDelegate)?.openExcludedPhrasesPlainBopomofo(sender)
    }

    @objc func openExcludedPhrasesMcBopomofo(_ sender: Any?) {
        (NSApp.delegate as? AppDelegate)?.openExcludedPhrasesMcBopomofo(sender)
    }

    @objc func openPhraseReplacementMcBopomofo(_ sender: Any?) {
        (NSApp.delegate as? AppDelegate)?.openPhraseReplacementMcBopomofo(sender)
    }

    @objc func reloadUserPhrases(_ sender: Any?) {
        LanguageModelManager.loadUserPhrases(
            enableForPlainBopomofo: Preferences.enableUserPhrasesInPlainBopomofo)
        LanguageModelManager.loadUserPhraseReplacement()

        // Empty the issues so that if there are still the same issues, a
        // notification will be shown.
        McBopomofoInputMethodController.latestUserFileIssues = []
        checkUserFileIssues()
    }

    @objc func showUserFileIssues(_ sender: Any?) {
        let header = NSLocalizedString(
            "Issues were found in the following user phrase files:", comment: "")
        let report =
            header + "\n\n"
            + McBopomofoInputMethodController.latestUserFileIssues.joined(separator: "\n")
        let tempDir = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
        let now = Date()
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd-HHmmss.SSS"
        let dateString = formatter.string(from: now)
        let fileName = "UserFileIssues-\(dateString).txt"
        let fileURL = tempDir.appendingPathComponent(fileName)
        do {
            try report.write(to: fileURL, atomically: true, encoding: .utf8)
            NSWorkspace.shared.open(fileURL)
        } catch {
            NSLog("Failed to write report to temporary file: \(error)")
            return
        }
    }

    @objc func showAbout(_ sender: Any?) {
        NSApp.orderFrontStandardAboutPanel(sender)
        NSApp.activate(ignoringOtherApps: true)
    }

}

// MARK: - State Handling

extension McBopomofoInputMethodController {

    func handle(state newState: InputState, client: Any?) {
        let previous = state
        state = newState

        switch newState {
        case let newState as InputState.Deactivated:
            handle(state: newState, previous: previous, client: client)
            state = .Empty()
        case let newState as InputState.Empty:
            resetAICandidateAssistState()
            resetAIAutoCorrectionState()
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.EmptyIgnoringPreviousState:
            resetAICandidateAssistState()
            resetAIAutoCorrectionState()
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.Committing:
            resetAICandidateAssistState()
            resetAIAutoCorrectionState()
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.Inputting:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.Marking:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.ChoosingCandidate:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.AssociatedPhrases:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.AssociatedPhrasesPlain:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.SelectingFeature:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.SelectingDateMacro:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.Number:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.Big5:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.IrohaKana:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.IrohaKanaCandidates:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.SelectingDictionary:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.ShowingCharInfo:
            handle(state: newState, previous: previous, client: client)
        case let newState as InputState.CustomMenu:
            handle(state: newState, previous: previous, client: client)
        default:
            break
        }
    }

    private func commit(text: String, client: Any!) {

        func convertToSimplifiedChineseIfRequired(_ text: String) -> String {
            if !Preferences.chineseConversionEnabled {
                return text
            }
            if Preferences.chineseConversionStyle == .model {
                return text
            }
            return OpenCCBridge.shared.convertToSimplified(text) ?? ""
        }

        let buffer = convertToSimplifiedChineseIfRequired(text)
        if buffer.isEmpty {
            return
        }
        (client as? IMKTextInput)?.insertText(
            buffer, replacementRange: NSRange(location: NSNotFound, length: NSNotFound))
    }

    private func handle(state: InputState.Deactivated, previous: InputState, client: Any?) {
        currentClient = nil

        gCurrentCandidateController?.delegate = nil
        gCurrentCandidateController?.visible = false
        hideTooltip()

        guard let client = client as? IMKTextInput else {
            return
        }

        switch previous {
        case let previous as InputState.NotEmpty:
            commit(text: previous.composingBuffer, client: client)
        case is InputState.Big5,
            is InputState.Number,
            is InputState.IrohaKana,
            is InputState.IrohaKanaCandidates:
            client.setMarkedText(
                "", selectionRange: NSMakeRange(0, 0), replacementRange: NSMakeRange(0, 0))
        default:
            break
        }

        // Unlike the Empty state handler, we don't call client.setMarkedText() here:
        // there's no point calling setMarkedText() with an empty string as the session
        // is being deactivated anyway, and we have found issues with how certains app
        // could not handle setMarkedText() at this point (see GitHub issue #346).
    }

    private func handle(state: InputState.Empty, previous: InputState, client: Any?) {
        gCurrentCandidateController?.visible = false
        hideTooltip()

        guard let client = client as? IMKTextInput else {
            return
        }

        if let previous = previous as? InputState.NotEmpty {
            commit(text: previous.composingBuffer, client: client)
        }
        client.setMarkedText(
            "", selectionRange: NSMakeRange(0, 0),
            replacementRange: NSMakeRange(NSNotFound, NSNotFound))
    }

    private func handle(
        state: InputState.EmptyIgnoringPreviousState, previous: InputState, client: Any!
    ) {
        gCurrentCandidateController?.visible = false
        hideTooltip()

        guard let client = client as? IMKTextInput else {
            return
        }

        client.setMarkedText(
            "", selectionRange: NSMakeRange(0, 0),
            replacementRange: NSMakeRange(NSNotFound, NSNotFound))
    }

    private func handle(state: InputState.Committing, previous: InputState, client: Any?) {
        gCurrentCandidateController?.visible = false
        hideTooltip()

        guard let client = client as? IMKTextInput else {
            return
        }

        let poppedText = state.poppedText
        if !poppedText.isEmpty {
            commit(text: poppedText, client: client)
        }
        client.setMarkedText(
            "", selectionRange: NSMakeRange(0, 0),
            replacementRange: NSMakeRange(NSNotFound, NSNotFound))
    }

    private func handle(state: InputState.Inputting, previous: InputState, client: Any?) {
        gCurrentCandidateController?.visible = false
        hideTooltip()

        guard let client = client as? IMKTextInput else {
            return
        }

        // the selection range is where the cursor is, with the length being 0 and replacement range NSNotFound,
        // i.e. the client app needs to take care of where to put this composing buffer
        client.setMarkedText(
            state.attributedString, selectionRange: NSMakeRange(Int(state.cursorIndex), 0),
            replacementRange: NSMakeRange(NSNotFound, NSNotFound))
        if !state.tooltip.isEmpty {
            show(
                tooltip: state.tooltip, composingBuffer: state.composingBuffer,
                cursorIndex: state.cursorIndex, client: client)
        }
        scheduleAIAutoCorrectionIfNeeded(for: state, client: client)
    }

    private func handle(state: InputState.Marking, previous: InputState, client: Any?) {
        gCurrentCandidateController?.visible = false
        guard let client = client as? IMKTextInput else {
            hideTooltip()
            return
        }

        // the selection range is where the cursor is, with the length being 0 and replacement range NSNotFound,
        // i.e. the client app needs to take care of where to put this composing buffer
        client.setMarkedText(
            state.attributedString, selectionRange: NSMakeRange(Int(state.cursorIndex), 0),
            replacementRange: NSMakeRange(NSNotFound, NSNotFound))

        if state.tooltip.isEmpty {
            hideTooltip()
        } else {
            show(
                tooltip: state.tooltip, composingBuffer: state.composingBuffer,
                cursorIndex: state.markerIndex, client: client)
        }
    }

    private func handle(state: InputState.ChoosingCandidate, previous: InputState, client: Any?) {
        hideTooltip()
        guard let client = client as? IMKTextInput else {
            gCurrentCandidateController?.visible = false
            return
        }

        // the selection range is where the cursor is, with the length being 0 and replacement range NSNotFound,
        // i.e. the client app needs to take care of where to put this composing buffer
        client.setMarkedText(
            state.attributedString, selectionRange: NSMakeRange(Int(state.cursorIndex), 0),
            replacementRange: NSMakeRange(NSNotFound, NSNotFound))
        show(candidateWindowWith: state, client: client)
        scheduleAICandidateRerankIfNeeded(for: state, client: client)
    }

    private func handle(state: InputState.AssociatedPhrases, previous: InputState, client: Any?) {
        hideTooltip()
        guard let client = client as? IMKTextInput else {
            gCurrentCandidateController?.visible = false
            return
        }

        let previousState = state.previousState
        // the selection range is where the cursor is, with the length being 0 and replacement range NSNotFound,
        // i.e. the client app needs to take care of where to put this composing buffer
        switch previousState {
        case let previousState as InputState.ChoosingCandidate:
            client.setMarkedText(
                previousState.attributedString,
                selectionRange: NSMakeRange(Int(previousState.cursorIndex), 0),
                replacementRange: NSMakeRange(NSNotFound, NSNotFound))
        case let previousState as InputState.Inputting:
            client.setMarkedText(
                previousState.attributedString,
                selectionRange: NSMakeRange(Int(previousState.cursorIndex), 0),
                replacementRange: NSMakeRange(NSNotFound, NSNotFound))
        default:
            break
        }
        show(candidateWindowWith: state, client: client)
    }

    private func handle(
        state: InputState.AssociatedPhrasesPlain, previous: InputState, client: Any?
    ) {
        hideTooltip()
        guard let client = client as? IMKTextInput else {
            gCurrentCandidateController?.visible = false
            return
        }
        client.setMarkedText(
            "", selectionRange: NSMakeRange(0, 0),
            replacementRange: NSMakeRange(NSNotFound, NSNotFound))
        show(candidateWindowWith: state, client: client)
    }

    private func handle(state: InputState.SelectingFeature, previous: InputState, client: Any?) {
        handleStateWithSimpleCandidateWindow(state: state, previous: previous, client: client)
    }

    private func handle(state: InputState.SelectingDateMacro, previous: InputState, client: Any?) {
        handleStateWithSimpleCandidateWindow(state: state, previous: previous, client: client)
    }

    private func handle(state: InputState.Number, previous: InputState, client: Any?) {

        gCurrentCandidateController?.visible = false
        hideTooltip()

        guard let client = client as? IMKTextInput else {
            return
        }

        client.setMarkedText(
            state.composingBuffer,
            selectionRange: NSMakeRange(
                (state.composingBuffer as NSString).length,
                0
            ),
            replacementRange: NSMakeRange(NSNotFound, NSNotFound)
        )
        if state.candidateCount > 0 {
            show(candidateWindowWith: state, client: client)
        }
    }

    private func handle(state: InputState.Big5, previous: InputState, client: Any?) {
        handleStateForCustomInput(
            composingBuffer: state.composingBuffer, previous: previous, client: client)
    }

    private func handle(state: InputState.IrohaKana, previous: InputState, client: Any?) {
        handleStateForCustomInput(
            composingBuffer: state.composingBuffer, previous: previous, client: client)
    }

    private func handle(state: InputState.IrohaKanaCandidates, previous: InputState, client: Any?) {
        handleStateWithSimpleCandidateWindow(state: state, previous: previous, client: client)
    }

    private func handle(state: InputState.SelectingDictionary, previous: InputState, client: Any?) {
        hideTooltip()
        guard let client = client as? IMKTextInput else {
            gCurrentCandidateController?.visible = false
            return
        }
        let previousState = state.previousState
        // the selection range is where the cursor is, with the length being 0 and replacement range NSNotFound,
        // i.e. the client app needs to take care of where to put this composing buffer

        switch previousState {
        case let previousState as InputState.ChoosingCandidate:
            client.setMarkedText(
                previousState.attributedString,
                selectionRange: NSMakeRange(Int(previousState.cursorIndex), 0),
                replacementRange: NSMakeRange(NSNotFound, NSNotFound))
        case let previousState as InputState.Marking:
            client.setMarkedText(
                previousState.attributedString,
                selectionRange: NSMakeRange(Int(previousState.cursorIndex), 0),
                replacementRange: NSMakeRange(NSNotFound, NSNotFound))
        default:
            break
        }
        show(candidateWindowWith: state, client: client)
    }

    private func handle(state: InputState.ShowingCharInfo, previous: InputState, client: Any?) {

        hideTooltip()
        guard let client = client as? IMKTextInput else {
            gCurrentCandidateController?.visible = false
            return
        }
        let previousState = state.previousState.previousState
        // the selection range is where the cursor is, with the length being 0 and replacement range NSNotFound,
        // i.e. the client app needs to take care of where to put this composing buffer
        switch previousState {
        case let previousState as InputState.ChoosingCandidate:
            client.setMarkedText(
                previousState.attributedString,
                selectionRange: NSMakeRange(Int(previousState.cursorIndex), 0),
                replacementRange: NSMakeRange(NSNotFound, NSNotFound))
        case let previousState as InputState.Marking:
            client.setMarkedText(
                previousState.attributedString,
                selectionRange: NSMakeRange(Int(previousState.cursorIndex), 0),
                replacementRange: NSMakeRange(NSNotFound, NSNotFound))
        default:
            break
        }
        show(candidateWindowWith: state, client: client)
    }

    private func handle(state: InputState.CustomMenu, previous: InputState, client: Any?) {
        hideTooltip()
        guard let client = client as? IMKTextInput else {
            gCurrentCandidateController?.visible = false
            return
        }
        show(candidateWindowWith: state, client: client)
    }
}

// MARK: -

extension McBopomofoInputMethodController {
    private func handleStateForCustomInput(
        composingBuffer: String, previous: InputState, client: Any?
    ) {
        gCurrentCandidateController?.visible = false
        hideTooltip()

        guard let client = client as? IMKTextInput else {
            return
        }

        if let previous = previous as? InputState.NotEmpty {
            commit(text: previous.composingBuffer, client: client)
        }
        client.setMarkedText(
            composingBuffer, selectionRange: NSMakeRange(composingBuffer.utf16.count, 0),
            replacementRange: NSMakeRange(NSNotFound, NSNotFound))
    }

    private func handleStateWithSimpleCandidateWindow(
        state: InputState, previous: InputState, client: Any?
    ) {
        gCurrentCandidateController?.visible = false
        hideTooltip()

        guard let client = client as? IMKTextInput else {
            return
        }

        if let previous = previous as? InputState.NotEmpty {
            commit(text: previous.composingBuffer, client: client)
        }
        // the selection range is where the cursor is, with the length being 0 and replacement range NSNotFound,
        // i.e. the client app needs to take care of where to put this composing buffer
        client.setMarkedText(
            "", selectionRange: NSMakeRange(0, 0),
            replacementRange: NSMakeRange(NSNotFound, NSNotFound))
        show(candidateWindowWith: state, client: client)
    }

    private func show(candidateWindowWith state: InputState, client: Any!) {
        let useVerticalMode: Bool = {
            var useVerticalMode = false
            var candidates: [InputState.Candidate] = []
            switch state {
            case let state as InputState.ChoosingCandidate:
                useVerticalMode = state.useVerticalMode
                candidates = state.candidates
            case let state as InputState.AssociatedPhrasesPlain:
                useVerticalMode = state.useVerticalMode
                candidates = state.candidates
            case let state as InputState.AssociatedPhrases:
                useVerticalMode = state.useVerticalMode
                candidates = state.candidates
            case is InputState.SelectingFeature,
                is InputState.SelectingDateMacro,
                is InputState.SelectingDictionary,
                is InputState.ShowingCharInfo,
                is InputState.Number:
                return true
            default:
                break
            }

            if useVerticalMode == true {
                return true
            }
            candidates.sort {
                return $0.displayText.count > $1.displayText.count
            }
            // If there is a candidate which is too long, we use the vertical
            // candidate list window automatically.
            if candidates.first?.displayText.count ?? 0 > 8 {
                return true
            }
            return false
        }()

        gCurrentCandidateController?.delegate = nil
        gCurrentCandidateController?.visible = false

        if useVerticalMode {
            gCurrentCandidateController = .vertical
        } else if Preferences.useHorizontalCandidateList {
            gCurrentCandidateController = .horizontal
        } else {
            gCurrentCandidateController = .vertical
        }

        gCurrentCandidateController?.tooltip =
            switch state {
            case let state as InputState.ChoosingCandidate
                where aiCandidateSuggestion?.originalComposingBuffer == state.composingBuffer:
                String(
                    format: NSLocalizedString("AI Suggestion: %@ (Tab)", comment: ""),
                    aiCandidateSuggestion?.suggestion ?? "")
            case let state as InputState.SelectingDictionary:
                String(format: NSLocalizedString("Look up %@", comment: ""), state.selectedPhrase)
            case let state as InputState.AssociatedPhrases:
                String(format: NSLocalizedString("%@…", comment: ""), state.prefixValue)
            case let state as InputState.CustomMenu:
                state.title
            default:
                ""
            }

        // set the attributes for the candidate panel (which uses NSAttributedString)
        let textSize = Preferences.candidateListTextSize
        let keyLabelSize = max(textSize / 2, kMinKeyLabelSize)

        func font(name: String?, size: CGFloat) -> NSFont {
            if let name = name {
                return NSFont(name: name, size: size) ?? NSFont.systemFont(ofSize: size)
            }
            return NSFont.systemFont(ofSize: size)
        }

        gCurrentCandidateController?.keyLabelFont = font(
            name: Preferences.candidateKeyLabelFontName, size: keyLabelSize)
        gCurrentCandidateController?.candidateFont = font(
            name: Preferences.candidateTextFontName, size: textSize)

        let candidateKeys = Preferences.candidateKeys
        let keyLabels =
            candidateKeys.count >= 4
            ? Array(candidateKeys) : Array(Preferences.defaultCandidateKeys)

        let keyLabelFormat: (String)->String = switch state {
        case let state as InputState.AssociatedPhrases where state.autoTriggered:
            { _ in "⇧ ⏎" }
        case is InputState.AssociatedPhrasesPlain,
            is InputState.Number:
            { "⇧ " + $0 }
        default:
            { $0 }
        }
        gCurrentCandidateController?.keyLabels = keyLabels.map {
            CandidateKeyLabel(key: String($0), displayedText: keyLabelFormat(String($0)))
        }

        gCurrentCandidateController?.delegate = self
        gCurrentCandidateController?.reloadData()
        currentClient = client

        var lineHeightRect = NSMakeRect(0.0, 0.0, 16.0, 16.0)
        var cursor: Int = 0

        if let state = state as? InputState.NotEmpty {
            cursor = Int(state.cursorIndex)
            if cursor == state.composingBuffer.count && cursor != 0 {
                cursor -= 1
            }
        }

        while lineHeightRect.origin.x == 0 && lineHeightRect.origin.y == 0 && cursor >= 0 {
            (client as? IMKTextInput)?.attributes(
                forCharacterIndex: cursor, lineHeightRectangle: &lineHeightRect)
            cursor -= 1
        }

        if useVerticalMode {
            gCurrentCandidateController?.set(
                windowTopLeftPoint: NSMakePoint(
                    lineHeightRect.origin.x + lineHeightRect.size.width + 4.0,
                    lineHeightRect.origin.y - 4.0),
                bottomOutOfScreenAdjustmentHeight: lineHeightRect.size.height + 4.0)
        } else {
            gCurrentCandidateController?.set(
                windowTopLeftPoint: NSMakePoint(
                    lineHeightRect.origin.x, lineHeightRect.origin.y - 4.0),
                bottomOutOfScreenAdjustmentHeight: lineHeightRect.size.height + 4.0)
        }

        gCurrentCandidateController?.visible = true
    }

    func show(tooltip: String, composingBuffer: String, cursorIndex: UInt, client: Any!) {
        var lineHeightRect = NSMakeRect(0.0, 0.0, 16.0, 16.0)
        var cursor: Int = Int(cursorIndex)
        if cursor == composingBuffer.count && cursor != 0 {
            cursor -= 1
        }

        var isVerticalMode = false
        while lineHeightRect.origin.x == 0 && lineHeightRect.origin.y == 0 && cursor >= 0 {
            let attributes: [AnyHashable: Any]? = (client as? IMKTextInput)?.attributes(
                forCharacterIndex: cursor, lineHeightRectangle: &lineHeightRect)
            let useVerticalMode =
                (attributes?["IMKTextOrientation"] as? NSNumber)?.intValue == 0 || false
            isVerticalMode = isVerticalMode || useVerticalMode
            cursor -= 1
        }

        // Make sure that tooltip hovers next to the vertical text.
        if isVerticalMode && lineHeightRect.size.height > 0 {
            lineHeightRect.origin.x += (lineHeightRect.size.width + 1.0)
        }

        McBopomofoInputMethodController.tooltipController.show(
            tooltip: tooltip, at: lineHeightRect.origin)
    }

    private func hideTooltip() {
        McBopomofoInputMethodController.tooltipController.hide()
    }

    private func checkUserFileIssues() {
        let issues: [String] = keyHandler.collectUserFileIssues()

        // McBopomofoLM caps the maximum number of issues collected, and so
        // we'll just do this O(n) comparison since n is small.
        if McBopomofoInputMethodController.latestUserFileIssues != issues {
            McBopomofoInputMethodController.latestUserFileIssues = issues

            if !McBopomofoInputMethodController.latestUserFileIssues.isEmpty {
                NotifierController.notify(
                    message: NSLocalizedString(
                        "Check McBopomofo menu for user file issues", comment: ""), stay: true)
            }
        }
    }
}
