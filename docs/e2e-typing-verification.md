# 實機端到端打字驗證（不需使用者在鍵盤前）

最後更新：2026-07-08T12:10:00+08:00

改動 L1 重排、延遲神經重審、消歧器、或任何「打字當下」行為後，**不必等使用者
實機驗收**：用 AppleScript 送真實虛擬鍵碼進 TextEdit，讓已安裝的輸入法真的處理
按鍵，直接觀察出字結果。這是 2026-07-08 v2.1.1 破案時建立的方法——當時單元測試
128 顆全綠、模擬打分 100% 正確，但實機零翻字；只有這種真按鍵驗證抓得到那類落差。

**快速用法**（推薦，細節都封裝好了）：

```bash
./scripts/e2e-typing-check.sh "a04a042k7y.3eji4x96"   # 慢慢的走過來
# 輸出:輸入法實際 commit 的文字,例如「慢慢地走過來」(延遲重審翻字成功)
```

## 原理與鐵則

1. **必須用 `key code`，不能用 `keystroke`**。`keystroke` 產生的數字鍵事件
   輸入法吃不到（聲調鍵 3/4/6/7 與 ㄢ0/ㄞ9 全部變成字面數字，出「ㄇ04ㄇ04…」
   亂碼）。`key code` 送 ANSI 虛擬鍵碼，與真鍵盤等價。
2. **打完要等**：延遲神經重審 = debounce 0.6s + 打分 ~1-2s，送出（Return）前
   `delay 3.5` 左右。
3. **TextEdit 的 `text of document` 只含已 commit 的文字**，組字中的 marked
   text 讀不到；要看「commit 前有沒有翻」用診斷開關（見下）。
4. AppleScript 變數**不可命名 `result`**（保留字，會炸）。
5. killall 重裝輸入法後，第一輪打字前多等幾秒（IMK 重新接上 client 需要時間），
   第一輪若吃字為空屬正常，重跑一次。
6. 跑之前確認目前輸入法是i注音：
   ```bash
   swift -e 'import Carbon; let s = TISCopyCurrentKeyboardInputSource().takeRetainedValue(); if let p = TISGetInputSourceProperty(s, kTISPropertyInputSourceID) { print(Unmanaged<CFString>.fromOpaque(p).takeUnretainedValue()) }'
   # 應輸出 org.openvanilla.inputmethod.McBopomofo.McBopomofo.Bopomofo
   ```
7. 終端機（跑 osascript 的程序）需有「輔助使用」權限；本機已設定過。

## 注音 → 美式鍵序（標準大千鍵盤）

| 鍵 | 注音 | 鍵 | 注音 | 鍵 | 注音 | 鍵 | 注音 |
|----|------|----|------|----|------|----|------|
| 1 | ㄅ | q | ㄆ | a | ㄇ | z | ㄈ |
| 2 | ㄉ | w | ㄊ | s | ㄋ | x | ㄌ |
| e | ㄍ | d | ㄎ | c | ㄏ | r | ㄐ |
| f | ㄑ | v | ㄒ | 5 | ㄓ | t | ㄔ |
| g | ㄕ | b | ㄖ | y | ㄗ | h | ㄘ |
| n | ㄙ | u | ㄧ | j | ㄨ | m | ㄩ |
| 8 | ㄚ | i | ㄛ | k | ㄜ | , | ㄝ |
| 9 | ㄞ | o | ㄟ | l | ㄠ | . | ㄡ |
| 0 | ㄢ | p | ㄣ | ; | ㄤ | / | ㄥ |
| - | ㄦ | 3 | ˇ | 4 | ˋ | 6 | ˊ |
| 7 | ˙ | space | 一聲/確認 | | | | |

例：慢慢的走過來 = ㄇㄢˋ ㄇㄢˋ ㄉㄜ˙ ㄗㄡˇ ㄍㄨㄛˋ ㄌㄞˊ = `a04 a04 2k7 y.3 eji4 x96`。

## 美式鍵 → ANSI 虛擬鍵碼（`key code` 用）

a=0 s=1 d=2 f=3 h=4 g=5 z=6 x=7 c=8 v=9 b=11 q=12 w=13 e=14 r=15 y=16 t=17
1=18 2=19 3=20 4=21 6=22 5=23 9=25 7=26 -=27 8=28 0=29 o=31 u=32 i=34 p=35
return=36 l=37 j=38 k=40 ;=41 ,=43 /=44 n=45 m=46 .=47 space=49 delete=51

## AppleScript 模板（scripts/e2e-typing-check.sh 內部即此流程）

```applescript
tell application "TextEdit"
    activate
    make new document
end tell
delay 1.5
tell application "System Events"
    key code {0, 29, 21, 0, 29, 21, 19, 40, 26}  -- 前半句
    delay 0.5
    key code {16, 47, 20, 14, 38, 34, 21, 7, 25, 22}  -- 後半句
end tell
delay 4  -- 等延遲重審(debounce + 打分)
tell application "System Events" to key code 36  -- Return commit
delay 0.5
tell application "TextEdit"
    set docText to text of document 1
    close document 1 saving no  -- 不留垃圾文件
end tell
return docText
```

## 診斷開關（看 commit 前的內部決策）

```bash
defaults write org.openvanilla.inputmethod.McBopomofo NeuralDeferredDiagnostics -bool YES
# 打字後看:
tail -30 ~/Library/Logs/laowang-neural-deferred.log
# 每個決策點都有:scheduled / perform / span gate / score(含各候選分數) / apply
# 查完務必關掉並刪 log(內含使用者輸入內容):
defaults delete org.openvanilla.inputmethod.McBopomofo NeuralDeferredDiagnostics
rm ~/Library/Logs/laowang-neural-deferred.log
```

IME 程序的 NSLog 在 unified log 幾乎撈不到（交班日誌 2026-06-25 的教訓），
固定檔診斷才可靠。
