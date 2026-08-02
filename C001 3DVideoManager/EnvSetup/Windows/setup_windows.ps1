$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Resolve-Path -LiteralPath (Join-Path $ScriptDir "..\..")
$EnvRoot = Join-Path $ProjectDir "EnvSetup"
$VenvDir = Join-Path $EnvRoot "venv-windows"
$Requirements = Join-Path $EnvRoot "requirements.txt"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.10+ and enable Add python.exe to PATH."
}

if (-not (Test-Path -LiteralPath $VenvDir)) {
    python -m venv $VenvDir
}

$PythonExe = Join-Path $VenvDir "Scripts\python.exe"
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r $Requirements

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Write-Warning "ffmpeg/ffprobe were not found in PATH. Install FFmpeg and add its bin folder to PATH."
}

Write-Host "Windows environment is ready: $VenvDir"
Write-Host "Run the tool with: $ProjectDir\run_av1_tool.bat"