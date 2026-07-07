#!/bin/bash
# 重建本機語音辨識 runtime(bin/ + models/)。這些是大型二進位產物,不入一般 git(見 .gitignore)。
# clone 後跑這支腳本:
#   - bin/    = 建置必需,「Copy Whisper Runtime」build phase 會打包進 app。
#   - models/ = 僅供本機開發測試;發佈版不打包模型,改由 app 首次使用語音輸入時從 HF 下載
#               (見 Source/WhisperServerManager.swift)。本機開發若想免於 app 端下載,
#               可把這顆 cp 到 ~/Library/Application Support/McBopomofo/WhisperModel/model.bin。
#
# whisper.cpp 沒有官方 macOS 二進位 release,所以這裡從 git clone 固定 tag 後以 cmake
# 靜態編譯 whisper-server(單一執行檔,只動態連結系統框架 Metal/Accelerate,免 dylib 搬運)。
#
# 用法:  cd whisper-runtime && ./fetch-runtime.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HERE/bin"
MODELS="$HERE/models"

# === 1) clone whisper.cpp 固定 tag ===
WHISPER_TAG="v1.9.1"
echo "[1/3] clone whisper.cpp ${WHISPER_TAG} …"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone --depth 1 --branch "$WHISPER_TAG" https://github.com/ggml-org/whisper.cpp.git "$TMP/whisper.cpp"

# === 2) cmake 靜態編譯 whisper-server(附帶 whisper-cli 供本機 benchmark)===
echo "[2/3] cmake build whisper-server …"
cmake -S "$TMP/whisper.cpp" -B "$TMP/build" \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DWHISPER_BUILD_TESTS=OFF \
  -DWHISPER_BUILD_EXAMPLES=ON > /dev/null
cmake --build "$TMP/build" -j "$(sysctl -n hw.ncpu)" --target whisper-server whisper-cli > /dev/null

rm -rf "$BIN" && mkdir -p "$BIN"
cp "$TMP/build/bin/whisper-server" "$BIN/whisper-server"
cp "$TMP/build/bin/whisper-cli" "$BIN/whisper-cli"
xattr -dr com.apple.quarantine "$BIN" 2>/dev/null || true
codesign --force -s - "$BIN/whisper-server"
codesign --force -s - "$BIN/whisper-cli"

# === 3) 本機模型:與 app 首次下載同一顆(見 WhisperServerManager 的 URL/SHA256)===
# 僅供本機開發測試;發佈版不打包。
echo "[3/3] 下載 Whisper 模型(large-v3-turbo-q5_0,~574MB)…"
mkdir -p "$MODELS"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin"
curl -L --fail -C - -o "$MODELS/model.bin" "$MODEL_URL"

echo "完成。bin/ 與 models/model.bin 已就緒,可以 xcodebuild 了。"
