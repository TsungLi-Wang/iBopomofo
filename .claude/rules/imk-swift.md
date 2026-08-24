---
paths:
  - "Source/*.swift"
  - "Source/**/*.swift"
  - "McBopomofoTests/**"
---

# Swift／InputMethodKit 層（動到 Swift 才載入）

## 輸入法選單是跨 process 代管的

`InputMethodController.menu()` 建出來的 `NSMenuItem` **不是**點擊時 IMK 回傳的那個物件。

- action 收到的 `sender` 不是你的 item → `guard let item = sender as? NSMenuItem` 會轉型失敗
  直接 return，症狀就是**「點了沒反應」**。
- **每個選項要有各自獨立的 `@objc` selector**（selector 本身就代表選擇），完全不要讀 sender。
  檔內所有正常運作的選項（`toggleXXX`、`showAbout`…）都是這個模式。
- 不可靠的是「從回傳的 sender 讀狀態」；在 `menu()` 裡建 item 時**直接設 `item.state = .on`
  是正常渲染的**——勾勾可以用，不要改成圓點（2026-06-17 定案用勾勾）。

## 改了常駐程式，先證明新碼在跑

「沒反應／沒生效」時**第一步不是生程式假設**，是比對三個時間戳：
原始碼 mtime、`~/Library/Input Methods/iBopomofo.app/Contents/MacOS/iBopomofo` mtime、
`ps aux` 的 process 啟動時間。只要執行檔或 process 比原始碼舊，跑的就是舊碼，
後面所有程式層推理都是沙上城堡（2026-06-17 為此白繞了好幾版）。

只「重開 App」不夠：`xcodebuild` → 覆蓋安裝 → `pkill iBopomofo` 重啟。

## 改打字當下的行為 → 一定要跑實機端到端驗證

```bash
./scripts/e2e-typing-check.sh "<美式鍵序>"
```

用 AppleScript `key code` 送真實鍵碼進 TextEdit，回報 IME 實際 commit 出來的字。
**不需要等人在場確認。** 方法、對照表、陷阱在 `docs/e2e-typing-verification.md`。

- **絕對不能用 `keystroke`**：數字鍵事件 IME 吃不到聲調。
- 單元測試／模擬全綠 ≠ 實機會動（v2.1.1 教訓：詞典的多字詞節點吞掉了歧義字）。
- 實際使用多為短句頻繁送出 → deferred 路徑天然難觸發，驗證句要一口氣整句打完。

## 出口約定

辨識／校正結果一律走既有的 `InputState.Committing` 出口，不要繞過 KeyHandler／InputState
自己拼一條路。新增「會寫使用者資料檔」的程式碼前先看 AGENTS 那一節（棒㉓ 踩過）。
