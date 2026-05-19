# NovelMaster WebUI Launcher (FastAPI)
$BIND_HOST = "0.0.0.0"
$PORT = 13567
$VENV = "venv"

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptPath

Write-Host ""
Write-Host "========================================"
Write-Host "   NovelMaster WebUI Launcher (FastAPI)"
Write-Host "========================================"
Write-Host ""

# Check and kill process using port
Write-Host "[*] Checking port $PORT..."
$connections = Get-NetTCPConnection -LocalPort $PORT -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
    if ($conn.State -eq "Listen") {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "[WARN] Found process $($proc.ProcessName) (PID: $($proc.Id)) using port, killing..."
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Host "[OK] Port released"

# Check Python
Write-Host "[*] Checking Python..."
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    $python = Get-Command python3 -ErrorAction SilentlyContinue
}
if (-not $python) {
    Write-Host "[ERROR] Python not found. Please install Python 3.8+"
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "[OK] Found Python"

# Check virtual environment
if (Test-Path "$VENV\Scripts\python.exe") {
    Write-Host "[*] Using virtual environment: $VENV"
    $PYTHON = "$VENV\Scripts\python.exe"
} else {
    Write-Host "[*] Using system Python"
    $PYTHON = $python.Source
}

# Install dependencies
Write-Host ""
Write-Host "[*] Checking dependencies..."
if (Test-Path "requirements.txt") {
    & pip install -r requirements.txt --quiet 2>$null
    Write-Host "[OK] Dependencies installed"
}

Write-Host ""
Write-Host "========================================"
Write-Host "   Starting FastAPI server..."
Write-Host "   Visit http://localhost:$PORT"
Write-Host "   API Docs: http://localhost:$PORT/docs"
Write-Host "========================================"
Write-Host ""

& $PYTHON app.py
