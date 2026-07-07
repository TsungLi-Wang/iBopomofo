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
import Security

// MARK: - AI 整句修正:使用者可設定的設定層
//
// 從 git clone 下來的任何人都應該能從 UI 自行填入金鑰/端點/模型,不必改原始碼。
// 所以這裡把先前寫死的值全部抽成:
//   - API key   → 存 macOS Keychain(加密、不落明文、不會被 commit 進 git)。
//   - 其餘設定   → 存 UserDefaults,各有合理預設值。
// InputMethodController 的 AI 後端只讀這裡,不再出現任何寫死的路徑/金鑰/模型名。

/// AI 修正的所有可設定項目。預設值 = 先前寫死在程式裡的值,所以「沒設定也能跑」。
enum AICorrectionConfig {

    // MARK: UserDefaults keys
    private static let kClaudeEndpoint = "AICorrectionClaudeEndpoint"
    private static let kClaudeOpusModel = "AICorrectionClaudeOpusModel"
    private static let kOpenAITranscribeModel = "AIVoiceOpenAITranscribeModel"

    // MARK: 預設值(= 原本寫死的值)
    static let defaultClaudeEndpoint = "https://api.anthropic.com/v1/messages"
    static let defaultClaudeOpusModel = "claude-opus-4-8"
    // OpenAI 語音辨識模型。預設 whisper-1(任何 OpenAI key 都能用);想換 gpt-4o-transcribe
    // 等更新的模型,從「AI 修正設定…」填即可,不必改程式。
    static let defaultOpenAITranscribeModel = "whisper-1"

    // MARK: 取值(空字串 → 退回預設,避免使用者清空欄位後整個壞掉)
    private static func value(_ key: String, default def: String) -> String {
        let v = (UserDefaults.standard.string(forKey: key) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return v.isEmpty ? def : v
    }

    static var claudeEndpoint: String { value(kClaudeEndpoint, default: defaultClaudeEndpoint) }
    static var claudeOpusModel: String { value(kClaudeOpusModel, default: defaultClaudeOpusModel) }
    static var openAITranscribeModel: String {
        value(kOpenAITranscribeModel, default: defaultOpenAITranscribeModel)
    }

    /// 設定視窗存檔時呼叫:空字串代表「用預設」,所以把 key 移除而不是寫空字串進去。
    static func save(
        claudeEndpoint: String, claudeOpusModel: String, openAITranscribeModel: String
    ) {
        let d = UserDefaults.standard
        func set(_ key: String, _ raw: String) {
            let v = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if v.isEmpty { d.removeObject(forKey: key) } else { d.set(v, forKey: key) }
        }
        set(kClaudeEndpoint, claudeEndpoint)
        set(kClaudeOpusModel, claudeOpusModel)
        set(kOpenAITranscribeModel, openAITranscribeModel)
        d.synchronize()
    }

    // MARK: API keys — 存 Keychain(不落明文、不進 git、不進 plist)
    private static let claudeAccount = "ClaudeAPIKey"
    private static let openAIAccount = "OpenAIAPIKey"

    static var claudeAPIKey: String? { AIKeychain.read(account: claudeAccount) }
    static func setClaudeAPIKey(_ key: String) { setKey(key, account: claudeAccount) }

    static var openAIAPIKey: String? { AIKeychain.read(account: openAIAccount) }
    static func setOpenAIAPIKey(_ key: String) { setKey(key, account: openAIAccount) }

    private static func setKey(_ key: String, account: String) {
        let trimmed = key.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            AIKeychain.delete(account: account)
        } else {
            AIKeychain.write(trimmed, account: account)
        }
    }
}

/// 極簡 Keychain 封裝:每個 account 存一筆 generic-password。
/// 目前用兩個 account:`ClaudeAPIKey`(Claude 整句修正)、`OpenAIAPIKey`(OpenAI 語音辨識)。
private enum AIKeychain {
    private static let service = "com.openvanilla.McBopomofo.AICorrection"

    private static func baseQuery(_ account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }

    static func read(account: String) -> String? {
        var query = baseQuery(account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
            let data = item as? Data,
            let s = String(data: data, encoding: .utf8)
        else { return nil }
        let key = s.trimmingCharacters(in: .whitespacesAndNewlines)
        return key.isEmpty ? nil : key
    }

    static func write(_ value: String, account: String) {
        let data = Data(value.utf8)
        // 先試更新,沒有才新增(避免重複)。
        let attrs: [String: Any] = [kSecValueData as String: data]
        let status = SecItemUpdate(baseQuery(account) as CFDictionary, attrs as CFDictionary)
        if status == errSecItemNotFound {
            var add = baseQuery(account)
            add[kSecValueData as String] = data
            SecItemAdd(add as CFDictionary, nil)
        }
    }

    static func delete(account: String) {
        SecItemDelete(baseQuery(account) as CFDictionary)
    }
}

// MARK: - AI 修正設定視窗(純程式碼建立,不碰 preferences.xib)
//
// 為什麼不掛進現有的 preferences.xib:那是 Interface Builder 的 XML,手改極脆弱且難 review。
// 這裡用程式碼建一個獨立 NSWindow,從輸入法選單的「AI 修正設定…」開啟,自成一塊好維護。
@objc(AISettingsWindowController)
final class AISettingsWindowController: NSWindowController {

    /// 單例:輸入法選單每次點都重用同一個視窗。
    @objc static let shared = AISettingsWindowController()

    private let apiKeyField = NSSecureTextField()
    private let claudeEndpointField = NSTextField()
    private let claudeOpusField = NSTextField()
    private let openAIKeyField = NSSecureTextField()
    private let openAIModelField = NSTextField()

    private init() {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 560, height: 0),
            styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "AI 整句修正設定"
        window.isReleasedWhenClosed = false
        super.init(window: window)
        buildUI()
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    private func makeLabel(_ text: String) -> NSTextField {
        let l = NSTextField(labelWithString: text)
        l.alignment = .right
        return l
    }

    private func buildUI() {
        guard let window = window, let content = window.contentView else { return }

        func row(_ title: String, _ field: NSTextField, placeholder: String) -> [NSView] {
            field.placeholderString = placeholder
            field.translatesAutoresizingMaskIntoConstraints = false
            return [makeLabel(title), field]
        }

        let grid = NSGridView(views: [
            row("Claude API key:", apiKeyField, placeholder: "sk-ant-…(存進 Keychain,留空=不用 Claude)"),
            row("Claude 端點:", claudeEndpointField, placeholder: AICorrectionConfig.defaultClaudeEndpoint),
            row("Claude Opus 模型:", claudeOpusField, placeholder: AICorrectionConfig.defaultClaudeOpusModel),
            row("OpenAI 語音 API key:", openAIKeyField, placeholder: "sk-…(語音來源選 OpenAI Whisper 時用,存 Keychain)"),
            row("OpenAI 語音模型:", openAIModelField, placeholder: AICorrectionConfig.defaultOpenAITranscribeModel),
        ])
        grid.translatesAutoresizingMaskIntoConstraints = false
        grid.rowSpacing = 10
        grid.columnSpacing = 10
        grid.column(at: 0).xPlacement = .trailing
        grid.column(at: 1).xPlacement = .fill

        let hint = NSTextField(wrappingLabelWithString:
            "留空的欄位會自動使用預設值(灰字)。API key 加密存放在 macOS Keychain,不會寫進設定檔或上傳到 git。")
        hint.translatesAutoresizingMaskIntoConstraints = false
        hint.textColor = .secondaryLabelColor
        hint.font = .systemFont(ofSize: 11)

        let saveButton = NSButton(title: "儲存", target: self, action: #selector(saveSettings))
        saveButton.keyEquivalent = "\r"
        let closeButton = NSButton(title: "關閉", target: self, action: #selector(closeWindow))
        let buttons = NSStackView(views: [closeButton, saveButton])
        buttons.translatesAutoresizingMaskIntoConstraints = false
        buttons.orientation = .horizontal
        buttons.spacing = 10

        let stack = NSStackView(views: [grid, hint, buttons])
        stack.translatesAutoresizingMaskIntoConstraints = false
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 16
        stack.edgeInsets = NSEdgeInsets(top: 20, left: 20, bottom: 20, right: 20)
        content.addSubview(stack)

        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            stack.topAnchor.constraint(equalTo: content.topAnchor),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor),
            grid.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -40),
            buttons.trailingAnchor.constraint(equalTo: grid.trailingAnchor),
        ])
    }

    /// 開窗前把目前設定灌進欄位。輸入法是背景 agent,要強制把視窗拉到前景。
    @objc func showSettings() {
        apiKeyField.stringValue = AICorrectionConfig.claudeAPIKey ?? ""
        claudeEndpointField.stringValue = AICorrectionConfig.claudeEndpoint
        claudeOpusField.stringValue = AICorrectionConfig.claudeOpusModel
        openAIKeyField.stringValue = AICorrectionConfig.openAIAPIKey ?? ""
        openAIModelField.stringValue = AICorrectionConfig.openAITranscribeModel
        window?.center()
        NSApp.activate(ignoringOtherApps: true)
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
    }

    @objc private func saveSettings() {
        AICorrectionConfig.setClaudeAPIKey(apiKeyField.stringValue)
        AICorrectionConfig.setOpenAIAPIKey(openAIKeyField.stringValue)
        AICorrectionConfig.save(
            claudeEndpoint: claudeEndpointField.stringValue,
            claudeOpusModel: claudeOpusField.stringValue,
            openAITranscribeModel: openAIModelField.stringValue)
        window?.performClose(nil)
    }

    @objc private func closeWindow() {
        window?.performClose(nil)
    }
}
