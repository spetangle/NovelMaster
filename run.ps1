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

# Check and create virtual environment
Write-Host "[*] Checking virtual environment..."
if (-not (Test-Path "$VENV\Scripts\python.exe")) {
    Write-Host "[*] Virtual environment not found, creating..."
    if (Test-Path $VENV) {
        Remove-Item -Recurse -Force $VENV
    }
    python -m venv $VENV
    if (-not (Test-Path "$VENV\Scripts\python.exe")) {
        Write-Host "[ERROR] Failed to create virtual environment"
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[OK] Virtual environment created"
}
Write-Host "[*] Using virtual environment: $VENV"
$PYTHON = "$VENV\Scripts\python.exe"
$PIP = "$VENV\Scripts\pip.exe"

# Install dependencies
Write-Host ""
Write-Host "[*] Checking dependencies..."
if (Test-Path "requirements.txt") {
    & $PIP install --upgrade pip --quiet 2>$null
    & $PIP install -r requirements.txt --quiet 2>$null
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
