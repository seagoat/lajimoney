#!/bin/bash
# 打包脚本 - 将可转债套利系统打包为 zip 压缩包
# 用法: ./package.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 获取 Windows 原生 temp 目录（bash 和 Python 共用）
WINTMP=$(python -c 'import tempfile; print(tempfile.gettempdir())')

# 读取最新 git tag 或 commit hash
VERSION=$(cd "$SCRIPT_DIR" && git describe --tags --always 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || echo "latest")
DATE=$(date +%Y%m%d)

# 输出文件名
PKG_NAME="cb_arbitrage_${DATE}_${VERSION}"
TMP_PKG="$WINTMP/$PKG_NAME"
DEST_ZIP="$SCRIPT_DIR/${PKG_NAME}.zip"

echo "[1/3] 清理旧文件..."
rm -rf "$TMP_PKG"
rm -f "$DEST_ZIP"
mkdir -p "$TMP_PKG"

echo "[2/3] 复制文件..."
cp -r "$SCRIPT_DIR/app" "$TMP_PKG/"
cp -r "$SCRIPT_DIR/tests" "$TMP_PKG/"
cp "$SCRIPT_DIR/run.py" "$SCRIPT_DIR/run.bat" "$SCRIPT_DIR/run.sh" "$TMP_PKG/"
cp "$SCRIPT_DIR/requirements.txt" "$SCRIPT_DIR/README.md" "$TMP_PKG/"
cp "$SCRIPT_DIR/.gitignore" "$TMP_PKG/" 2>/dev/null || true
cp -r "$SCRIPT_DIR/docs/superpowers/plans" "$TMP_PKG/plans" 2>/dev/null || true

# 清理 __pycache__
find "$TMP_PKG" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$TMP_PKG" -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

echo "[3/3] 打包..."
# 用 Python zipfile 模块（跨平台，无依赖）
python - "$TMP_PKG" "$DEST_ZIP" "$PKG_NAME" << 'PYEOF'
import sys, zipfile, pathlib
src_dir = sys.argv[1]
dst_zip = sys.argv[2]
pkg_name = sys.argv[3]
with zipfile.ZipFile(dst_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
    src = pathlib.Path(src_dir)
    for fp in src.rglob('*'):
        if fp.is_file():
            arcname = fp.relative_to(src)
            zf.write(fp, arcname)
PYEOF

echo "打包完成: $DEST_ZIP"

# 清理临时目录
rm -rf "$TMP_PKG"
