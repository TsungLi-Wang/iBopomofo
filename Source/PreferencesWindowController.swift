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

import Carbon
import Cocoa
import InfoCollector

extension NSToolbarItem.Identifier {
    fileprivate static let basic = NSToolbarItem.Identifier(rawValue: "basic")
    fileprivate static let userPhrases = NSToolbarItem.Identifier(rawValue: "user_phrases")
    fileprivate static let sentenceEnd = NSToolbarItem.Identifier(rawValue: "sentence_end")
    fileprivate static let advanced = NSToolbarItem.Identifier(rawValue: "advanced")
}

private let kWindowTitleHeight: CGFloat = 78

// Please note that the class should be exposed as "PreferencesWindowController"
// in Objective-C in order to let IMK to see the same class name as
// the "InputMethodServerPreferencesWindowControllerClass" in Info.plist.
@objc(PreferencesWindowController) class PreferencesWindowController: NSWindowController {
    @IBOutlet weak var fontSizePopUpButton: NSPopUpButton!
    @IBOutlet weak var basisKeyboardLayoutButton: NSPopUpButton!
    @IBOutlet weak var selectionKeyComboBox: NSComboBox!

    @IBOutlet weak var customUserPhraseLocationEnabledButton: NSPopUpButton!
    @IBOutlet weak var userPhrasesTextField: NSTextField!
    @IBOutlet weak var chooseUserPhrasesFolderButton: NSButton!
    @IBOutlet weak var openUserPhrasesFolderButton: NSButton!

    @IBOutlet weak var basicSettingsView: NSView!
    @IBOutlet weak var userPhrasesSettingsView: NSView!
    @IBOutlet weak var advancedSettingsView: NSView!

    @IBOutlet weak var addPhraseHookPathField: NSTextField!

    /// Built in code (not xib): sentence-end triggers + manual-correction log.
    private var sentenceEndSettingsView: NSView!
    private var pauseEnabledCheckbox: NSButton!
    private var pauseMsField: NSTextField!
    private var pauseMsLabel: NSTextField!
    private var commaCheckbox: NSButton!
    private var periodCheckbox: NSButton!
    private var enterCheckbox: NSButton!
    private var manualCorrectionLogCheckbox: NSButton!

    override func awakeFromNib() {
        buildSentenceEndSettingsView()

        let toolbar = NSToolbar(identifier: "preference toolbar")
        toolbar.allowsUserCustomization = false
        toolbar.autosavesConfiguration = false
        toolbar.sizeMode = .default
        toolbar.delegate = self
        toolbar.selectedItemIdentifier = .basic
        toolbar.showsBaselineSeparator = true
        window?.titlebarAppearsTransparent = false
        if #available(macOS 11.0, *) {
            window?.toolbarStyle = .preference
        }
        window?.toolbar = toolbar
        window?.title = NSLocalizedString("Basic", comment: "")
        use(view: basicSettingsView)

        // When the `CandidateListTextSize` is not yet populated, the pop up
        // button adds an empty item and selects that empty item. This code
        // correctly sets the default text size, and removes the empty item
        // at the end.
        let selectedSizeTitle = fontSizePopUpButton.selectedItem?.title ?? ""
        if selectedSizeTitle.isEmpty {
            let intFontSize = Int(Preferences.candidateListTextSize)
            let intFontSizeStr = String.init(format: "%d", intFontSize)

            var selected = false
            for item in fontSizePopUpButton.itemArray {
                if item.title == intFontSizeStr {
                    fontSizePopUpButton.select(item)
                    selected = true
                    break
                }
            }

            // If not selected, Preferences.candidateListTextSize is not set to
            // one of the options provided in the pop up button. Let's list the
            // option for the user.
            if !selected {
                var insertIndex = 0

                // Place the item in the right place. We take advantage of the
                // fact that Int("") returns nil, and so if the custom font size
                // is larger than the largest item in the list (say 96), this
                // code guarantees to place the custom font size item right below
                // that largest item and before the empty item (which will then
                // be removed by the code below).
                for (index, item) in fontSizePopUpButton.itemArray.enumerated() {
                    if intFontSize < (Int(item.title) ?? Int.max) {
                        insertIndex = index
                        break
                    }
                }
                fontSizePopUpButton.insertItem(withTitle: intFontSizeStr, at: insertIndex)
                fontSizePopUpButton.selectItem(at: insertIndex)
            }

            // Remove the last item if it's empty
            let items = fontSizePopUpButton.itemArray
            if let lastItem = items.last {
                if lastItem.title.isEmpty {
                    fontSizePopUpButton.removeItem(at: items.count - 1)
                }
            }
        }

        let list = TISCreateInputSourceList(nil, true).takeRetainedValue() as! [TISInputSource]
        var usKeyboardLayoutItem: NSMenuItem? = nil
        var chosenItem: NSMenuItem? = nil

        basisKeyboardLayoutButton.menu?.removeAllItems()

        let basisKeyboardLayoutID = Preferences.basisKeyboardLayout
        for source in list {

            func getString(_ key: CFString) -> String? {
                if let ptr = TISGetInputSourceProperty(source, key) {
                    return String(Unmanaged<CFString>.fromOpaque(ptr).takeUnretainedValue())
                }
                return nil
            }

            func getBool(_ key: CFString) -> Bool? {
                if let ptr = TISGetInputSourceProperty(source, key) {
                    return Unmanaged<CFBoolean>.fromOpaque(ptr).takeUnretainedValue()
                        == kCFBooleanTrue
                }
                return nil
            }

            if let category = getString(kTISPropertyInputSourceCategory) {
                if category != String(kTISCategoryKeyboardInputSource) {
                    continue
                }
            } else {
                continue
            }

            if let asciiCapable = getBool(kTISPropertyInputSourceIsASCIICapable) {
                if !asciiCapable {
                    continue
                }
            } else {
                continue
            }

            if let sourceType = getString(kTISPropertyInputSourceType) {
                if sourceType != String(kTISTypeKeyboardLayout) {
                    continue
                }
            } else {
                continue
            }

            guard let sourceID = getString(kTISPropertyInputSourceID),
                let localizedName = getString(kTISPropertyLocalizedName)
            else {
                continue
            }

            let menuItem = NSMenuItem()
            menuItem.title = localizedName
            menuItem.representedObject = sourceID

            if sourceID == "com.apple.keylayout.US" {
                usKeyboardLayoutItem = menuItem
            }
            if basisKeyboardLayoutID == sourceID {
                chosenItem = menuItem
            }
            basisKeyboardLayoutButton.menu?.addItem(menuItem)
        }

        basisKeyboardLayoutButton.select(chosenItem ?? usKeyboardLayoutItem)
        selectionKeyComboBox.usesDataSource = false
        selectionKeyComboBox.removeAllItems()
        selectionKeyComboBox.addItems(withObjectValues: Preferences.suggestedCandidateKeys)

        var candidateSelectionKeys = Preferences.candidateKeys
        if candidateSelectionKeys.isEmpty {
            candidateSelectionKeys = Preferences.defaultCandidateKeys
        }
        selectionKeyComboBox.stringValue = candidateSelectionKeys

        if #available(macOS 11.0, *) {
            chooseUserPhrasesFolderButton.image = NSImage(
                systemSymbolName: "folder", accessibilityDescription: "Folder")
        }
        let index = Preferences.useCustomUserPhraseLocation ? 1 : 0
        customUserPhraseLocationEnabledButton.selectItem(at: index)
        updateUserPhraseLocation()
        addPhraseHookPathField.stringValue = Preferences.addPhraseHookPath
    }

    // MARK: - Sentence-end preferences (programmatic pane)

    private func buildSentenceEndSettingsView() {
        let width: CGFloat = 480
        let view = NSView(frame: NSRect(x: 0, y: 0, width: width, height: 360))
        view.autoresizesSubviews = false

        var y: CGFloat = 360 - 28
        let left: CGFloat = 24
        let contentWidth = width - left * 2

        func place(_ control: NSView, height: CGFloat = 22) {
            control.frame = NSRect(x: left, y: y - height, width: contentWidth, height: height)
            view.addSubview(control)
            y -= height + 8
        }

        func sectionTitle(_ text: String) {
            y -= 6
            let label = NSTextField(labelWithString: text)
            label.font = NSFont.boldSystemFont(ofSize: NSFont.systemFontSize)
            place(label, height: 20)
        }

        sectionTitle(NSLocalizedString("Auto-correct while composing", comment: ""))

        let help = NSTextField(wrappingLabelWithString: NSLocalizedString(
            "Pause: auto-correct homophones only — underline stays, text not sent. Enter: remove underline, hard-commit, and deliver Enter to the app (send/newline). Period/comma (if enabled): one auto-correct like pause; default is insert punct only.",
            comment: ""))
        help.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        help.textColor = .secondaryLabelColor
        help.frame = NSRect(x: left, y: y - 56, width: contentWidth, height: 56)
        view.addSubview(help)
        y -= 64

        pauseEnabledCheckbox = NSButton(
            checkboxWithTitle: NSLocalizedString("Pause (idle): auto-correct, keep underline", comment: ""),
            target: self, action: #selector(sentenceEndPrefChanged(_:)))
        place(pauseEnabledCheckbox)

        let msRow = NSView(frame: NSRect(x: left, y: y - 24, width: contentWidth, height: 24))
        pauseMsLabel = NSTextField(labelWithString: NSLocalizedString("Pause duration (ms):", comment: ""))
        pauseMsLabel.frame = NSRect(x: 20, y: 2, width: 160, height: 20)
        pauseMsField = NSTextField(frame: NSRect(x: 180, y: 0, width: 80, height: 24))
        pauseMsField.alignment = .right
        pauseMsField.formatter = {
            let f = NumberFormatter()
            f.numberStyle = .none
            f.minimum = NSNumber(value: ShippingRerankConstants.sentenceEndPauseMsMin)
            f.maximum = 10_000
            f.allowsFloats = false
            return f
        }()
        pauseMsField.target = self
        pauseMsField.action = #selector(pauseMsEdited(_:))
        pauseMsField.delegate = self
        let unit = NSTextField(labelWithString: "ms")
        unit.frame = NSRect(x: 268, y: 2, width: 30, height: 20)
        msRow.addSubview(pauseMsLabel)
        msRow.addSubview(pauseMsField)
        msRow.addSubview(unit)
        view.addSubview(msRow)
        y -= 32

        periodCheckbox = NSButton(
            checkboxWithTitle: NSLocalizedString("Period (。): also auto-correct (keep underline)", comment: ""),
            target: self, action: #selector(sentenceEndPrefChanged(_:)))
        place(periodCheckbox)

        commaCheckbox = NSButton(
            checkboxWithTitle: NSLocalizedString("Comma (，): also auto-correct (keep underline)", comment: ""),
            target: self, action: #selector(sentenceEndPrefChanged(_:)))
        place(commaCheckbox)

        enterCheckbox = NSButton(
            checkboxWithTitle: NSLocalizedString(
                "Enter: always hard-commit + send (path β; toggle kept for settings)", comment: ""),
            target: self, action: #selector(sentenceEndPrefChanged(_:)))
        place(enterCheckbox)

        y -= 8
        sectionTitle(NSLocalizedString("Manual correction samples", comment: ""))

        let corrHelp = NSTextField(wrappingLabelWithString: NSLocalizedString(
            "Log each manual candidate pick as a hard-fork training sample (local only).",
            comment: ""))
        corrHelp.font = NSFont.systemFont(ofSize: NSFont.smallSystemFontSize)
        corrHelp.textColor = .secondaryLabelColor
        corrHelp.frame = NSRect(x: left, y: y - 36, width: contentWidth, height: 36)
        view.addSubview(corrHelp)
        y -= 44

        manualCorrectionLogCheckbox = NSButton(
            checkboxWithTitle: NSLocalizedString("Record manual corrections", comment: ""),
            target: self, action: #selector(sentenceEndPrefChanged(_:)))
        place(manualCorrectionLogCheckbox)

        let clearBtn = NSButton(
            title: NSLocalizedString("Clear correction log…", comment: ""),
            target: self, action: #selector(clearManualCorrectionLog(_:)))
        clearBtn.bezelStyle = .rounded
        place(clearBtn, height: 28)

        let effectiveBtn = NSButton(
            title: NSLocalizedString("Show effective settings…", comment: ""),
            target: self, action: #selector(showEffectiveShippingSettings(_:)))
        effectiveBtn.bezelStyle = .rounded
        place(effectiveBtn, height: 28)

        // Fit height to used space (keep bottom padding).
        let usedHeight = 360 - y + 16
        view.frame.size.height = max(320, usedHeight)
        // Reposition subviews were laid from top of fixed 360; shift if height grew.
        // They are already placed from top of original frame — if we shrink/grow,
        // keep top-aligned by adjusting frames relative to new height.
        let delta = view.frame.height - 360
        if abs(delta) > 0.5 {
            for sub in view.subviews {
                sub.frame.origin.y += delta
            }
        }

        sentenceEndSettingsView = view
        reloadSentenceEndControlsFromPreferences()
    }

    private func reloadSentenceEndControlsFromPreferences() {
        pauseEnabledCheckbox.state = Preferences.sentenceEndPauseEnabled ? .on : .off
        pauseMsField.integerValue = Preferences.sentenceEndPauseMs
        periodCheckbox.state = Preferences.sentenceEndTriggerPeriod ? .on : .off
        commaCheckbox.state = Preferences.sentenceEndTriggerComma ? .on : .off
        enterCheckbox.state = Preferences.sentenceEndTriggerEnter ? .on : .off
        manualCorrectionLogCheckbox.state = Preferences.enableManualCorrectionLog ? .on : .off
        updatePauseMsEnabledState()
    }

    private func updatePauseMsEnabledState() {
        let on = pauseEnabledCheckbox.state == .on
        pauseMsField.isEnabled = on
        pauseMsLabel.textColor = on ? .labelColor : .disabledControlTextColor
    }

    @objc private func sentenceEndPrefChanged(_ sender: Any?) {
        Preferences.sentenceEndPauseEnabled = pauseEnabledCheckbox.state == .on
        Preferences.sentenceEndTriggerPeriod = periodCheckbox.state == .on
        Preferences.sentenceEndTriggerComma = commaCheckbox.state == .on
        Preferences.sentenceEndTriggerEnter = enterCheckbox.state == .on
        Preferences.enableManualCorrectionLog = manualCorrectionLogCheckbox.state == .on
        updatePauseMsEnabledState()
    }

    @objc private func pauseMsEdited(_ sender: Any?) {
        let raw = pauseMsField.integerValue
        Preferences.sentenceEndPauseMs = raw > 0 ? raw : ShippingRerankConstants.sentenceEndPauseMsDefault
        pauseMsField.integerValue = Preferences.sentenceEndPauseMs
    }

    @objc private func clearManualCorrectionLog(_ sender: Any?) {
        ManualCorrectionLog.clearLog()
        let alert = NSAlert()
        alert.messageText = NSLocalizedString("Manual correction log cleared", comment: "")
        alert.alertStyle = .informational
        if let window = window {
            alert.beginSheetModal(for: window, completionHandler: nil)
        } else {
            alert.runModal()
        }
    }

    @objc private func showEffectiveShippingSettings(_ sender: Any?) {
        let text = Preferences.effectiveShippingConfigurationSummary()
        let alert = NSAlert()
        alert.messageText = NSLocalizedString("Effective settings", comment: "")
        alert.informativeText = text
        alert.alertStyle = .informational
        if let window = window {
            alert.beginSheetModal(for: window, completionHandler: nil)
        } else {
            alert.runModal()
        }
    }

    @IBAction func updateBasisKeyboardLayoutAction(_ sender: Any) {
        if let sourceID = basisKeyboardLayoutButton.selectedItem?.representedObject as? String {
            Preferences.basisKeyboardLayout = sourceID
        }
    }

    @IBAction func changeSelectionKeyAction(_ sender: Any) {
        guard
            let keys = (sender as AnyObject).stringValue?
                .trimmingCharacters(in: .whitespacesAndNewlines)
                .lowercased()
        else {
            return
        }
        do {
            try Preferences.validate(candidateKeys: keys)
            Preferences.candidateKeys = keys
        } catch Preferences.CandidateKeyError.empty {
            selectionKeyComboBox.stringValue = Preferences.candidateKeys
        } catch {
            if let window = window {
                let alert = NSAlert(error: error)
                alert.beginSheetModal(for: window) { response in
                    self.selectionKeyComboBox.stringValue = Preferences.candidateKeys
                }
            }
        }
    }

    func updateUserPhraseLocation() {
        if Preferences.useCustomUserPhraseLocation {
            userPhrasesTextField.stringValue = Preferences.customUserPhraseLocation
            openUserPhrasesFolderButton.title = Preferences.customUserPhraseLocation
        } else {
            userPhrasesTextField.stringValue = ""
            openUserPhrasesFolderButton.title = UserPhraseLocationHelper.defaultUserPhraseLocation
        }
    }

    @IBAction func changeCustomUserPhraseLocationEnabledAction(_ sender: Any) {
        guard let control = sender as? NSPopUpButton else {
            return
        }
        let enabled = control.selectedTag() > 0
        Preferences.useCustomUserPhraseLocation = enabled
        if enabled {
            if Preferences.customUserPhraseLocation.isEmpty {
                Preferences.customUserPhraseLocation =
                    UserPhraseLocationHelper.defaultUserPhraseLocation
            }
        }
        updateUserPhraseLocation()
    }

    @IBAction func changeUserPhraseLocationAction(_ sender: Any) {
        guard let control = sender as? NSControl else {
            return
        }
        let path = control.stringValue.trimmingCharacters(in: .whitespaces)
        if FileManager.default.fileExists(atPath: path) == false {
            try? FileManager.default.createDirectory(
                atPath: path, withIntermediateDirectories: true)
        }
        Preferences.customUserPhraseLocation = path
        updateUserPhraseLocation()
    }

    @IBAction func openUserPhrasedFolderAction(_ sender: Any) {
        let path =
            Preferences.useCustomUserPhraseLocation
            ? Preferences.customUserPhraseLocation
            : UserPhraseLocationHelper.defaultUserPhraseLocation
        let url = URL(fileURLWithPath: path)
        NSWorkspace.shared.open(url)
    }

    @IBAction func changeUserPhraseLocationFromPanelAction(_ sender: Any) {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        let result = panel.runModal()

        if result == .OK, let url = panel.urls.first {
            let path = url.path
            Preferences.customUserPhraseLocation = path
            updateUserPhraseLocation()
        }
    }

    @IBAction func openSystemInfoReport(_ sender: Any) {
        Task { @MainActor in
            await openSystemInfoReportAsync()
        }
    }
}

extension PreferencesWindowController {
    func openSystemInfoReportAsync() async {
        var report = ""
        report += await InfoCollector.generate()
        report += Preferences.createReport()
        // Write report to a temporary file
        let tempDir = URL(fileURLWithPath: NSTemporaryDirectory(), isDirectory: true)
        let randomName = "SystemInfoReport-\(UUID().uuidString).txt"
        let fileURL = tempDir.appendingPathComponent(randomName)
        do {
            try report.write(to: fileURL, atomically: true, encoding: .utf8)
            NSWorkspace.shared.open(fileURL)
        } catch {
            NSLog("Failed to write report to temporary file: \(error)")
            return
        }
    }
}

extension PreferencesWindowController: NSToolbarDelegate {
    func use(view: NSView) {
        guard let window = window else {
            return
        }
        window.contentView?.subviews.first?.removeFromSuperview()
        let viewFrame = view.frame
        var windowRect = window.frame
        windowRect.size.height = kWindowTitleHeight + viewFrame.height
        windowRect.size.width = viewFrame.width
        windowRect.origin.y = window.frame.maxY - (viewFrame.height + kWindowTitleHeight)
        window.setFrame(windowRect, display: true, animate: true)
        window.contentView?.frame = view.bounds
        window.contentView?.addSubview(view)
    }

    @objc func showBasicView(_ sender: Any?) {
        use(view: basicSettingsView)
        window?.toolbar?.selectedItemIdentifier = .basic
        window?.title = NSLocalizedString("Basic", comment: "")
    }

    @objc func showUserPhrasesView(_ sender: Any?) {
        use(view: userPhrasesSettingsView)
        window?.toolbar?.selectedItemIdentifier = .userPhrases
        window?.title = NSLocalizedString("User Phrases", comment: "")
    }

    @objc func showSentenceEndView(_ sender: Any?) {
        reloadSentenceEndControlsFromPreferences()
        use(view: sentenceEndSettingsView)
        window?.toolbar?.selectedItemIdentifier = .sentenceEnd
        window?.title = NSLocalizedString("Sentence End", comment: "")
    }

    @objc func showAdvancedView(_ sender: Any?) {
        use(view: advancedSettingsView)
        window?.toolbar?.selectedItemIdentifier = .advanced
        window?.title = NSLocalizedString("Advanced", comment: "")
    }

    func toolbarDefaultItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [.basic, .userPhrases, .sentenceEnd, .advanced]
    }

    func toolbarAllowedItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [.basic, .userPhrases, .sentenceEnd, .advanced]
    }

    func toolbarSelectableItemIdentifiers(_ toolbar: NSToolbar) -> [NSToolbarItem.Identifier] {
        [.basic, .userPhrases, .sentenceEnd, .advanced]
    }

    func toolbar(
        _ toolbar: NSToolbar, itemForItemIdentifier itemIdentifier: NSToolbarItem.Identifier,
        willBeInsertedIntoToolbar flag: Bool
    ) -> NSToolbarItem? {
        let item = NSToolbarItem(itemIdentifier: itemIdentifier)
        item.target = self
        switch itemIdentifier {
        case .basic:
            let title = NSLocalizedString("Basic", comment: "")
            item.label = title
            if #available(macOS 11.0, *) {
                item.image = NSImage(systemSymbolName: "switch.2", accessibilityDescription: title)
            } else {
                item.image = NSImage(named: NSImage.preferencesGeneralName)
            }
            item.action = #selector(showBasicView(_:))
        case .userPhrases:
            let title = NSLocalizedString("User Phrases", comment: "")
            item.label = title
            if #available(macOS 11.0, *) {
                item.image = NSImage(systemSymbolName: "folder", accessibilityDescription: title)
            } else {
                item.image = NSImage(named: NSImage.folderName)
            }
            item.action = #selector(showUserPhrasesView(_:))
        case .sentenceEnd:
            // zh:「定案」— keep short for toolbar; full name is in Localizable.
            let title = NSLocalizedString("Sentence End", comment: "")
            item.label = title
            item.paletteLabel = title
            item.toolTip = NSLocalizedString("Auto-finalize on sentence end", comment: "")
            if #available(macOS 11.0, *) {
                // text.badge.checkmark may be missing on some OS builds; fall back.
                let img =
                    NSImage(systemSymbolName: "text.badge.checkmark", accessibilityDescription: title)
                    ?? NSImage(systemSymbolName: "checkmark.circle", accessibilityDescription: title)
                    ?? NSImage(systemSymbolName: "text.alignleft", accessibilityDescription: title)
                item.image = img
            } else {
                item.image = NSImage(named: NSImage.advancedName)
            }
            item.action = #selector(showSentenceEndView(_:))
        case .advanced:
            let title = NSLocalizedString("Advanced", comment: "")
            item.label = title
            if #available(macOS 11.0, *) {
                item.image = NSImage(systemSymbolName: "gear", accessibilityDescription: title)
            } else {
                item.image = NSImage(named: NSImage.advancedName)
            }
            item.action = #selector(showAdvancedView(_:))
        default:
            return nil
        }
        return item
    }
}

extension PreferencesWindowController: NSTextFieldDelegate {
    func controlTextDidEndEditing(_ obj: Notification) {
        if obj.object as? NSTextField === pauseMsField {
            pauseMsEdited(pauseMsField as Any)
        }
    }
}
