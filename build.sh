#!/bin/bash
#
# MagnaX Build Script
# Usage:
#   ./build.sh          - Build only
#   ./build.sh test     - Build and upload to TestPyPI
#   ./build.sh release  - Build and upload to PyPI
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Project directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo -e "${GREEN}=== MagnaX Build Script ===${NC}"
echo ""

# Get current version
VERSION=$(python3 -c "from magnax import __version__; print(__version__)")
echo -e "Current version: ${YELLOW}${VERSION}${NC}"
echo ""

# Step 1: Clean previous builds
echo -e "${GREEN}[1/5] Cleaning previous builds...${NC}"
rm -rf build/ dist/ *.egg-info magnax.egg-info
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
echo "Done."
echo ""

# Step 2: Verify bundled adb binaries are present and non-empty
# (曾出现过 adb 二进制被提交成 0 字节空文件，导致 Windows/Linux 用户安装后无法运行)
echo -e "${GREEN}[2/5] Verifying bundled adb binaries...${NC}"
REQUIRED_ADB=(
    "magnax/public/adb/windows/adb.exe"
    "magnax/public/adb/windows/AdbWinApi.dll"
    "magnax/public/adb/windows/AdbWinUsbApi.dll"
    "magnax/public/adb/mac/adb"
    "magnax/public/adb/linux/adb"
)
ADB_OK=1
for f in "${REQUIRED_ADB[@]}"; do
    if [ ! -s "$f" ]; then
        echo -e "  ${RED}✗ 缺失或为空: $f${NC}"
        ADB_OK=0
    else
        size=$(wc -c < "$f" | tr -d ' ')
        echo -e "  ${GREEN}✓${NC} $f (${size} bytes)"
    fi
done
# linux_arm 无官方二进制，仅提醒不阻断
if [ ! -s "magnax/public/adb/linux_arm/adb" ]; then
    echo -e "  ${YELLOW}! magnax/public/adb/linux_arm/adb 为空(无官方 ARM 版,ARM Linux 依赖系统 adb)${NC}"
fi
if [ "$ADB_OK" -ne 1 ]; then
    echo -e "${RED}校验失败:存在空的 adb 二进制,已中止打包。请补全后再发布。${NC}"
    exit 1
fi
echo "Done."
echo ""

# Step 3: Install/upgrade build tools
echo -e "${GREEN}[3/5] Checking build tools...${NC}"
python3 -m pip install --upgrade pip setuptools wheel build twine -q
echo "Done."
echo ""

# Step 4: Build the package
echo -e "${GREEN}[4/5] Building package...${NC}"
python3 -m build
echo "Done."
echo ""

# Verify the built wheel actually contains non-empty adb binaries
# (防止 MANIFEST.in/package_data 配置遗漏,把 adb 漏在包外)
echo -e "${GREEN}Verifying adb binaries inside built wheel...${NC}"
WHEEL=$(ls dist/*.whl 2>/dev/null | head -n 1)
if [ -z "$WHEEL" ]; then
    echo -e "${RED}未找到 wheel 文件,打包可能失败。${NC}"
    exit 1
fi
# unzip -l 输出:  size  date  time  name —— 取 adb 相关条目检查 size>0
WHEEL_ADB_BAD=$(unzip -l "$WHEEL" | awk '/adb\/(windows|mac|linux)\/.*(adb|adb\.exe|\.dll)$/ {if ($1+0==0) print $4}')
if [ -n "$WHEEL_ADB_BAD" ]; then
    echo -e "${RED}✗ wheel 内以下 adb 文件为 0 字节:${NC}"
    echo "$WHEEL_ADB_BAD"
    echo -e "${RED}已中止。请检查 MANIFEST.in / package_data 配置。${NC}"
    exit 1
fi
echo -e "${GREEN}✓ wheel 内 adb 二进制均非空。${NC}"
echo ""

# List built files
echo -e "${GREEN}Built files:${NC}"
ls -la dist/
echo ""

# Step 5: Upload (if requested)
if [ "$1" == "test" ]; then
    echo -e "${GREEN}[5/5] Uploading to TestPyPI...${NC}"
    python3 -m twine upload --repository testpypi dist/*
    echo ""
    echo -e "${GREEN}Package uploaded to TestPyPI!${NC}"
    echo -e "Install with: ${YELLOW}pip install -i https://test.pypi.org/simple/ magnax==${VERSION}${NC}"
elif [ "$1" == "release" ]; then
    echo -e "${YELLOW}[5/5] Uploading to PyPI...${NC}"
    read -p "Are you sure you want to upload to PyPI? (y/N) " confirm
    if [ "$confirm" == "y" ] || [ "$confirm" == "Y" ]; then
        python3 -m twine upload dist/*
        echo ""
        echo -e "${GREEN}Package uploaded to PyPI!${NC}"
        echo -e "Install with: ${YELLOW}pip install magnax==${VERSION}${NC}"
    else
        echo "Upload cancelled."
    fi
else
    echo -e "${GREEN}[5/5] Build complete (no upload).${NC}"
    echo ""
    echo -e "To install locally: ${YELLOW}pip install dist/magnax-${VERSION}-py3-none-any.whl${NC}"
    echo -e "To upload to TestPyPI: ${YELLOW}./build.sh test${NC}"
    echo -e "To upload to PyPI: ${YELLOW}./build.sh release${NC}"
fi

echo ""
echo -e "${GREEN}=== Build Complete ===${NC}"
