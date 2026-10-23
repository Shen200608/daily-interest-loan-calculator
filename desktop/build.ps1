<#
.SYNOPSIS
    利息计算器 · 桌面版打包脚本（PyInstaller 单文件 exe）。

.DESCRIPTION
    把 desktop/app.py 打包成 Windows 上双击即可运行的单个 exe。
    PyInstaller 是「可选增强」：未安装时本脚本只打印中文提示并正常退出（exit 0），
    不影响源码直接运行（python app.py 本身零第三方依赖）。

    刻意不自动 pip install —— 安装第三方包属于用户环境决策，请按提示手动执行。

    注意：本文件必须保存为「UTF-8 带 BOM」。Windows PowerShell 5.1 会把无 BOM 的
    .ps1 当成 ANSI(GBK) 读取，中文全部乱码并导致语法错误。

.PARAMETER Python
    指定 Python 解释器路径。默认自动探测 py -3 / python / python3。

.PARAMETER Name
    产物名，默认 LixiCalculator → 产物 desktop/dist/LixiCalculator.exe。

.PARAMETER OneDir
    生成目录版（启动更快）而非单文件版。

.PARAMETER SkipSelftest
    跳过打包前的 --selftest 校验。

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File desktop\build.ps1

.EXAMPLE
    .\desktop\build.ps1 -OneDir -Name LixiCalc
#>
[CmdletBinding()]
param(
    [string]$Python,
    [string]$Name = 'LixiCalculator',
    [switch]$OneDir,
    [switch]$SkipSelftest
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# ---------------------------------------------------------------- 0. UTF-8 输出
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
    # 某些受限宿主不允许改编码，忽略即可
}

function Write-Step([string]$Text) { Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok([string]$Text) { Write-Host "[OK] $Text" -ForegroundColor Green }
function Write-Warn([string]$Text) { Write-Host "[提示] $Text" -ForegroundColor Yellow }
function Write-Err([string]$Text) { Write-Host "[错误] $Text" -ForegroundColor Red }

# ---------------------------------------------------------------- 1. 定位路径
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir
$AppPy = Join-Path $ScriptDir 'app.py'
$RatesJson = Join-Path $RootDir 'data\rates.json'

Write-Host ''
Write-Host '  利息计算器 · 桌面版打包' -ForegroundColor White
Write-Host '  ----------------------------------------' -ForegroundColor DarkGray

if (-not (Test-Path -LiteralPath $AppPy)) {
    Write-Err "找不到 desktop/app.py：$AppPy"
    exit 1
}

# ---------------------------------------------------------------- 2. 找 Python
function Resolve-Python([string]$Explicit) {
    if ($Explicit) {
        if (Test-Path -LiteralPath $Explicit) { return $Explicit }
        Write-Err "指定的 Python 不存在：$Explicit"
        return $null
    }
    foreach ($candidate in @('py -3', 'python', 'python3')) {
        $parts = $candidate.Split(' ')
        $exe = $parts[0]
        $found = Get-Command $exe -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        try {
            # 注意：不能用 $args（PowerShell 自动变量），这里用 $pyArgs
            $pyArgs = @()
            if ($parts.Length -gt 1) { $pyArgs += $parts[1..($parts.Length - 1)] }
            $pyArgs += @('-c', 'import sys; print(sys.executable)')
            $out = & $exe @pyArgs 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -Last 1).ToString().Trim() }
        } catch { continue }
    }
    return $null
}

# 优先用环境变量里指定的解释器（便于 CI / 无 PATH 的环境）
if (-not $Python -and $env:LIXI_PYTHON) { $Python = $env:LIXI_PYTHON }

$PyExe = Resolve-Python $Python
if (-not $PyExe) {
    Write-Err '未找到可用的 Python。请先安装 Python 3.9+ 并勾选「Add Python to PATH」。'
    Write-Host '  下载地址：https://www.python.org/downloads/windows/' -ForegroundColor DarkGray
    Write-Host '  也可以显式指定解释器：' -ForegroundColor DarkGray
    Write-Host '    .\desktop\build.ps1 -Python "C:\Python312\python.exe"' -ForegroundColor Yellow
    exit 1
}
Write-Ok "Python：$PyExe"
$PyVersion = (& $PyExe -c "import sys; print('.'.join(str(x) for x in sys.version_info[:3]))") -join ''
Write-Ok "版本：$PyVersion"

# tkinter 必须可用，否则打出来的 exe 打不开窗口
& $PyExe -c "import tkinter" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Err '该 Python 缺少 tkinter，无法打包图形界面。请安装带 Tcl/Tk 的官方发行版。'
    exit 1
}
Write-Ok 'tkinter 可用'

# ---------------------------------------------------------------- 3. 打包前自检
if (-not $SkipSelftest) {
    Write-Step '打包前运行无头自检（--selftest）'
    & $PyExe $AppPy --selftest 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Err '自检未通过，已中止打包。请先运行 python desktop\app.py --selftest 排查。'
        exit 1
    }
    Write-Ok '自检通过'
}

# ---------------------------------------------------------------- 4. 检查 PyInstaller
Write-Step '检查 PyInstaller'
$HasPyInstaller = $false
try {
    & $PyExe -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -eq 0) { $HasPyInstaller = $true }
} catch { $HasPyInstaller = $false }

if (-not $HasPyInstaller) {
    Write-Warn '未安装 PyInstaller，无法生成 exe。'
    Write-Host ''
    Write-Host '  这一步是「可选增强」，不影响交付：' -ForegroundColor White
    Write-Host '    - 用户装好 Python 3.9+ 后，双击或执行 python desktop\app.py 即可运行；'
    Write-Host '    - 桌面版零第三方依赖，不需要 pip install 任何东西。'
    Write-Host ''
    Write-Host '  如果确实想生成免安装 exe，请手动执行（本脚本不会自动安装）：' -ForegroundColor White
    Write-Host "    `"$PyExe`" -m pip install pyinstaller" -ForegroundColor Yellow
    Write-Host '  然后重新运行本脚本：' -ForegroundColor White
    Write-Host '    powershell -ExecutionPolicy Bypass -File desktop\build.ps1' -ForegroundColor Yellow
    Write-Host ''
    exit 0
}

$PiVersion = (& $PyExe -c "import PyInstaller; print(PyInstaller.__version__)") -join ''
Write-Ok "PyInstaller：$PiVersion"

# ---------------------------------------------------------------- 5. 组装参数
# 产物统一到 desktop/dist/；所有中间产物（workpath / spec）丢到系统临时目录，
# 绝不污染仓库（配合 .gitignore 的 desktop/dist/）。
$DistDir = Join-Path $ScriptDir 'dist'
$StagingDir = Join-Path ([System.IO.Path]::GetTempPath()) ('lixi-pyinstaller-' + [System.Guid]::NewGuid().ToString('N').Substring(0, 8))
$WorkDir = Join-Path $StagingDir 'work'
New-Item -ItemType Directory -Path $WorkDir -Force | Out-Null
Write-Ok "中间产物目录（临时）：$StagingDir"

$BuildArgs = @(
    '-m', 'PyInstaller',
    '--noconfirm',
    '--clean',
    '--name', $Name,
    '--distpath', $DistDir,
    '--workpath', $WorkDir,
    '--specpath', $WorkDir
)
if ($OneDir) { $BuildArgs += '--onedir' } else { $BuildArgs += '--onefile' }
# --windowed：双击不弹黑色控制台窗口
$BuildArgs += '--windowed'

# 把利率数据一起打进去（app.py 会优先读 sys._MEIPASS/data/rates.json）
if (Test-Path -LiteralPath $RatesJson) {
    $BuildArgs += @('--add-data', ($RatesJson + ';data'))
    Write-Ok '已加入 data/rates.json（打包后仍使用真实利率数据）'
} else {
    Write-Warn '找不到 data\rates.json，将使用程序内置的最小数据集。'
}

# 体积优化：排除用不到的重型模块（app.py 只用标准库）
foreach ($module in @('numpy', 'pandas', 'matplotlib', 'scipy', 'PIL', 'PyQt5', 'PySide2', 'pytest')) {
    $BuildArgs += @('--exclude-module', $module)
}

$BuildArgs += $AppPy

# ---------------------------------------------------------------- 6. 执行打包
Write-Step '开始打包（首次约 1-3 分钟）'
Write-Host "  $PyExe $($BuildArgs -join ' ')" -ForegroundColor DarkGray
$buildOk = $false
try {
    & $PyExe @BuildArgs
    if ($LASTEXITCODE -eq 0) { $buildOk = $true }
    else { Write-Err "打包失败（退出码 $LASTEXITCODE）。可尝试 -OneDir 参数，或检查杀毒软件是否拦截。" }
} finally {
    # 无论成败都清掉临时中间产物（spec / work 目录都在这里）
    if (Test-Path -LiteralPath $StagingDir) {
        Remove-Item -LiteralPath $StagingDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}
if (-not $buildOk) { exit 1 }

# ---------------------------------------------------------------- 7. 结果
$ExePath = Join-Path $DistDir ($Name + '.exe')
if ($OneDir) { $ExePath = Join-Path (Join-Path $DistDir $Name) ($Name + '.exe') }

Write-Host ''
if (Test-Path -LiteralPath $ExePath) {
    $sizeMB = [math]::Round((Get-Item -LiteralPath $ExePath).Length / 1MB, 1)
    Write-Ok "打包完成：$ExePath（约 $sizeMB MB）"
    Write-Host '  双击即可运行，无需安装 Python。' -ForegroundColor White
    Write-Host '  首次启动会稍慢（单文件版需解压到临时目录）。' -ForegroundColor DarkGray
} else {
    Write-Warn "打包命令已结束，但未找到预期产物：$ExePath"
    Write-Host "  请查看 $DistDir 目录。" -ForegroundColor DarkGray
    exit 0
}

Write-Host ''
Write-Ok '中间产物已自动清理，仓库内只保留 desktop/dist/ 下的 exe。'
exit 0
