i注音 — 若雙擊「安裝i注音」出現「無法驗證開發者」
====================================================

這不是惡意軟體，是未付費 Apple 憑證的開源軟體都會遇到的提示。

【方法一】終端機一鍵安裝（推薦，完全不用打開 .app）
  1. 打開「終端機」(Terminal)
  2. 複製貼上下面整行，按 Enter：

curl -fsSL https://raw.githubusercontent.com/TsungLi-Wang/iBopomofo/master/scripts/install.sh | bash

  3. 完成後到「系統設定 → 鍵盤 → 文字輸入 → 輸入法 → 編輯」加入「i注音」

【方法二】右鍵打開（只需一次）
  對「安裝i注音」按右鍵 →「打開」→ 再按「打開」

【永久解法】
  需開發者付費加入 Apple Developer 並 notarize，目前尚未實作。
