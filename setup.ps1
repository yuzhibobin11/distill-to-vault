# distill-to-vault 依赖安装（Windows / PowerShell）
# 用法：pwsh -File setup.ps1            默认阿里云镜像（国内快）
#      pwsh -File setup.ps1 -Mirror no  用官方源

param(
    [string]$Mirror = "aliyun"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "== 检查 Python ==" -ForegroundColor Cyan
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Host "找不到 python，请先安装 Python 3.10+ 并加入 PATH" -ForegroundColor Red; exit 1 }

$ver = (python -c "import sys;print('%d.%d'%sys.version_info[:2])")
$ok = python -c "import sys;print(1 if sys.version_info[:2] >= (3,10) else 0)"
if ($ok.Trim() -ne "1") { Write-Host "Python $ver 太旧，需要 3.10+" -ForegroundColor Red; exit 1 }
Write-Host "Python $ver OK" -ForegroundColor Green

$indexArgs = @()
if ($Mirror -eq "aliyun") {
    $indexArgs = @("-i", "https://mirrors.aliyun.com/pypi/simple/")
    Write-Host "使用阿里云镜像" -ForegroundColor Yellow
}

Write-Host "`n== 安装依赖（av 固定 16.1.0，PyAV 19 会弄坏 faster-whisper） ==" -ForegroundColor Cyan
python -m pip install --upgrade pip @indexArgs
python -m pip install @indexArgs requests yt-dlp faster-whisper "av==16.1.0"
if ($LASTEXITCODE -ne 0) { Write-Host "依赖安装失败" -ForegroundColor Red; exit $LASTEXITCODE }

Write-Host "`n== 自检 ==" -ForegroundColor Cyan
$env:HF_ENDPOINT = "https://hf-mirror.com"
python scripts/fetch_text.py doctor

Write-Host @"

下一步：
  1. 设 vault 路径（不设则默认 E:/football/足球）
       setx DISTILL_VAULT "你的Obsidian库路径"
  2. 取一篇试试
       python scripts/fetch_text.py fetch <url> --out-dir C:\Temp\distill\job1
  3. 跑用例确认校验器正常
       python scripts/audit.py eval eval/cases

"@ -ForegroundColor Green
