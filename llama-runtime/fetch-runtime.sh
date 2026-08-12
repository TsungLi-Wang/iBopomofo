#!/bin/bash
# 重建本機推理 runtime(bin/ + models/)。這些是大型二進位產物,不入一般 git(見 .gitignore)。
# clone 後跑這支腳本:
#   - bin/    = 建置必需,「Copy Llama Runtime」build phase 會打包進 app。
#   - models/ = 僅供本機開發測試;發佈版不打包模型,改由 app 首次使用時從 HF 下載
#               (見 Source/LlamaServerManager.swift)。本機開發若想免於 app 端下載,
#               可把這顆 cp 到 ~/Library/Application Support/iBopomofo/AIModel/model.gguf。
#
# 用法:  cd llama-runtime && ./fetch-runtime.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HERE/bin"
MODELS="$HERE/models"

# === 1) llama.cpp 官方 release(macos-arm64,自含 @loader_path dylib) ===
LLAMA_TAG="b9692"
TARBALL="llama-${LLAMA_TAG}-bin-macos-arm64.tar.gz"
URL="https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_TAG}/${TARBALL}"

# llama-server 實際依賴的 10 個 dylib(以 @rpath/libX.0.dylib 請求);把版本實體檔直接
# 命名成請求的名稱,扁平、無 symlink、好簽章。
echo "[1/3] 下載 llama.cpp ${LLAMA_TAG} …"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -L --fail -o "$TMP/$TARBALL" "$URL"
mkdir -p "$TMP/x" && tar -xzf "$TMP/$TARBALL" -C "$TMP/x"
SRC="$TMP/x/llama-${LLAMA_TAG}"

echo "[2/3] 組裝精簡 bin/ …"
rm -rf "$BIN" && mkdir -p "$BIN"
cp "$SRC/llama-server" "$BIN/llama-server"
cp "$SRC/libggml-base.0.15.1.dylib"      "$BIN/libggml-base.0.dylib"
cp "$SRC/libggml-blas.0.15.1.dylib"      "$BIN/libggml-blas.0.dylib"
cp "$SRC/libggml-cpu.0.15.1.dylib"       "$BIN/libggml-cpu.0.dylib"
cp "$SRC/libggml-metal.0.15.1.dylib"     "$BIN/libggml-metal.0.dylib"
cp "$SRC/libggml-rpc.0.15.1.dylib"       "$BIN/libggml-rpc.0.dylib"
cp "$SRC/libggml.0.15.1.dylib"           "$BIN/libggml.0.dylib"
cp "$SRC/libllama.0.0.${LLAMA_TAG#b}.dylib"        "$BIN/libllama.0.dylib"
cp "$SRC/libllama-common.0.0.${LLAMA_TAG#b}.dylib" "$BIN/libllama-common.0.dylib"
cp "$SRC/libmtmd.0.0.${LLAMA_TAG#b}.dylib"         "$BIN/libmtmd.0.dylib"
cp "$SRC/libllama-server-impl.dylib"     "$BIN/libllama-server-impl.dylib"
xattr -dr com.apple.quarantine "$BIN" 2>/dev/null || true
for f in "$BIN"/*.dylib "$BIN/llama-server"; do codesign --force -s - "$f"; done

# === 3) 本機模型:Qwen3-4B-Instruct-2507 Q5_K_M(apache-2.0) ===
# 僅供本機開發測試;發佈版不打包,改由 app 首次使用時從同一條 HF URL 下載(見 LlamaServerManager)。
# Phase 0 對比實測勝出;授權乾淨可發佈。bartowski repo 有 Qwen_ 前綴。
# 2026-06-18 由 Q4_K_M 升 Q5_K_M(~2.89GB):同模型純降量化誤差、零相容性風險。
echo "[3/3] 下載模型 Qwen3-4B-Instruct-2507-Q5_K_M(~2.89GB) …"
mkdir -p "$MODELS"
MODEL_URL="https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF/resolve/main/Qwen_Qwen3-4B-Instruct-2507-Q5_K_M.gguf"
curl -L --fail -C - -o "$MODELS/model.gguf" "$MODEL_URL"

echo "✅ 完成。bin/ 與 models/model.gguf 已就緒,可以 xcodebuild 了。"
