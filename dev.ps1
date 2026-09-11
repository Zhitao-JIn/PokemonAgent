# dev.ps1 —— 一键启动观测台（PowerShell 版，Windows PowerShell 5.1 兼容）
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File dev.ps1
#   （或终端允许脚本时直接 .\dev.ps1）
#
# 端口：后端 127.0.0.1:8000（POKEMON_API_PORT 可改），前端 5173（vite 默认）。
$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8
Set-Location $PSScriptRoot

if (-not (Test-Path "assets/rom")) { Write-Host "找不到 ROM: assets/rom"; exit 1 }
if (-not (Test-Path "web/node_modules")) {
    Write-Host "web/node_modules 不存在，先跑: cd web; npm install"
    exit 1
}

# 选 Python：优先 py -3.12（装齐了 fastapi/uvicorn 等依赖），退回 PATH 里的 python。
$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    $py = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
    if (-not $py) { $py = & py -c "import sys; print(sys.executable)" }
}
if (-not $py) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source }
}
if (-not $py) { Write-Host "找不到 Python 3.12（py launcher 或 PATH 里的 python）"; exit 1 }
Write-Host "使用 Python: $py"

if (-not $env:DASHSCOPE_API_KEY -and -not $env:ANTHROPIC_AUTH_TOKEN) {
    Write-Host "警告: 未设置 DASHSCOPE_API_KEY/ANTHROPIC_AUTH_TOKEN——后端能起，但 LLM 调用会失败"
}

$env:POKEMON_ROM = Join-Path $PSScriptRoot "assets\rom"
$apiLog = Join-Path $PSScriptRoot "dev-api.log"
$apiErr = Join-Path $PSScriptRoot "dev-api.err.log"
$webLog = Join-Path $PSScriptRoot "dev-web.log"
$webErr = Join-Path $PSScriptRoot "dev-web.err.log"

$api = Start-Process -FilePath $py -ArgumentList "-m", "pokemon_agent.api" `
    -WorkingDirectory $PSScriptRoot `
    -RedirectStandardOutput $apiLog -RedirectStandardError $apiErr `
    -NoNewWindow -PassThru
$web = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm run dev" `
    -WorkingDirectory (Join-Path $PSScriptRoot "web") `
    -RedirectStandardOutput $webLog -RedirectStandardError $webErr `
    -NoNewWindow -PassThru

Write-Host ""
Write-Host "后端  : http://127.0.0.1:8000/health"
Write-Host "前端  : http://localhost:5173"
Write-Host "日志  : $apiLog / $webLog"
Write-Host "退出  : Ctrl+C（同时关掉两个进程）"
Write-Host ""

# 前端就绪后自动打开默认浏览器——人不用再手动敲地址。
# 轮询而非固定 sleep：vite 冷启动秒级波动大，固定等待要么白等要么 404。
$frontUp = $false
foreach ($i in 1..30) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:5173" -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) { $frontUp = $true; break }
    } catch { Start-Sleep -Milliseconds 500 }
}
if ($frontUp) {
    Start-Process "http://localhost:5173"
    Write-Host "浏览器已打开 http://localhost:5173"
} else {
    Write-Host "前端 30 秒内未就绪，没开浏览器——手动访问 http://localhost:5173"
}

try {
    Wait-Process -Id $api.Id, $web.Id
} finally {
    Stop-Process -Id $api.Id, $web.Id -ErrorAction SilentlyContinue
}
