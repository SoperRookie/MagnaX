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
echo -e "${GREEN}[1/4] Cleaning previous builds...${NC}"
rm -rf build/ dist/ *.egg-info magnax.egg-info
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
echo "Done."
echo ""

# Step 2: Install/upgrade build tools
echo -e "${GREEN}[2/4] Checking build tools...${NC}"
python3 -m pip install --upgrade pip setuptools wheel build twine -q
echo "Done."
echo ""

# Step 3: Build the package
echo -e "${GREEN}[3/4] Building package...${NC}"
python3 -m build
echo "Done."
echo ""

# List built files
echo -e "${GREEN}Built files:${NC}"
ls -la dist/
echo ""

# Step 4: Upload (if requested)
if [ "$1" == "test" ]; then
    echo -e "${GREEN}[4/4] Uploading to TestPyPI...${NC}"
    python3 -m twine upload --repository testpypi dist/*
    echo ""
    echo -e "${GREEN}Package uploaded to TestPyPI!${NC}"
    echo -e "Install with: ${YELLOW}pip install -i https://test.pypi.org/simple/ magnax==${VERSION}${NC}"
elif [ "$1" == "release" ]; then
    echo -e "${YELLOW}[4/4] Uploading to PyPI...${NC}"
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
    echo -e "${GREEN}[4/4] Build complete (no upload).${NC}"
    echo ""
    echo -e "To install locally: ${YELLOW}pip install dist/magnax-${VERSION}-py3-none-any.whl${NC}"
    echo -e "To upload to TestPyPI: ${YELLOW}./build.sh test${NC}"
    echo -e "To upload to PyPI: ${YELLOW}./build.sh release${NC}"
fi

echo ""
echo -e "${GREEN}=== Build Complete ===${NC}"
