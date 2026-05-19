#!/bin/bash
# NovelMaster WebUI Launcher (FastAPI)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

HOST="0.0.0.0"
PORT=5000
VENV="venv"

echo ""
echo "========================================"
echo "   NovelMaster WebUI Launcher (FastAPI)"
echo "========================================"
echo ""

# 检查Python
echo "[*] 检查 Python..."
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        echo "[ERROR] 未找到 Python，请先安装 Python 3.8+"
        exit 1
    fi
    PYTHON="python"
else
    PYTHON="python3"
fi
echo "[OK] $($PYTHON --version)"

# 检查虚拟环境
if [ -d "$VENV/bin/python" ]; then
    echo "[*] 使用虚拟环境: $VENV"
    PYTHON="$VENV/bin/python"
elif [ -d "$VENV/Scripts/python" ]; then
    echo "[*] 使用虚拟环境: $VENV"
    PYTHON="$VENV/Scripts/python"
else
    echo "[*] 使用系统 Python"
fi

# 安装依赖
echo ""
echo "[*] 检查依赖..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet
    echo "[OK] 依赖已安装"
fi

# 启动服务
echo ""
echo "========================================"
echo "   Starting FastAPI server..."
echo "   Visit http://localhost:$PORT"
echo "   API Docs: http://localhost:$PORT/docs"
echo "========================================"
echo ""

$PYTHON app.py
