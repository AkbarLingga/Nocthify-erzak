# ============================================================================
#  Nocthify - erzak  |  Windows installer (Windows 7 SP1, 8, 8.1, 10, 11)
#
#  One-line install (paste in PowerShell or Win+R):
#    powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=3072; iex ((New-Object Net.WebClient).DownloadString('https://raw.githubusercontent.com/AkbarLingga/Nocthify-by-erzak/main/install.ps1'))"
#
#  Written for PowerShell 2.0+ (the version that ships with Windows 7).
# ============================================================================
$ErrorActionPreference = "Stop"

# >>> Change this to your GitHub "user/repo" after you create the repository <<<
$Repo   = "AkbarLingga/Nocthify-by-erzak"
$Branch = "main"

$Root    = Join-Path $env:LOCALAPPDATA "Nocthify"
$AppDir  = Join-Path $Root "app"
$VenvDir = Join-Path $Root "venv"
try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072 } catch {}

function Say($msg)  { Write-Host "  >  $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  OK $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  !  $msg" -ForegroundColor Yellow }

Write-Host ""
Write-Host "   Nocthify - erzak" -ForegroundColor White
Write-Host "   Dynamic Island + Control Center + Dock" -ForegroundColor DarkGray
Write-Host ""

$ver   = [Environment]::OSVersion.Version
$Win7  = ($ver.Major -eq 6 -and $ver.Minor -le 1)
$Win8  = ($ver.Major -eq 6 -and $ver.Minor -ge 2)
$Is64  = ([IntPtr]::Size -eq 8) -or ($env:PROCESSOR_ARCHITEW6432 -ne $null)

# ---------------------------------------------------------------- Python ---
function Test-Py($exe, $pre) {
    try {
        $out = & $exe $pre -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $p = "$out".Trim().Split(".")
        $maj = [int]$p[0]; $min = [int]$p[1]
        if ($maj -eq 3 -and $min -ge 8) { return "$out".Trim() }
    } catch {}
    return $null
}

function Find-Python {
    $cands = @()
    if (Get-Command py -ErrorAction SilentlyContinue) { $cands += ,@("py", "-3") }
    if (Get-Command python -ErrorAction SilentlyContinue) { $cands += ,@("python", "") }
    foreach ($d in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles", "${env:ProgramFiles(x86)}")) {
        if (Test-Path $d) {
            Get-ChildItem $d -Filter "Python3*" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | ForEach-Object {
                $exe = Join-Path $_.FullName "python.exe"
                if (Test-Path $exe) { $cands += ,@($exe, "") }
            }
        }
    }
    foreach ($c in $cands) {
        $v = if ($c[1]) { Test-Py $c[0] $c[1] } else { Test-Py $c[0] "-I" }
        if ($v) {
            if ($c[1]) { $exe = (& $c[0] $c[1] -c "import sys; print(sys.executable)").Trim() } else { $exe = $c[0] }
            if ($Win7 -or $Win8) {
                $mm = [int]($v.Split(".")[1]); if ($mm -gt 8) { continue }  # 3.9+ does not run on Win 7/8
            }
            return $exe
        }
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    if ($Win7 -or $Win8) { $PyVer = "3.8.10" } else { $PyVer = "3.12.10" }
    $arch = if ($Is64) { "-amd64" } else { "" }
    $url = "https://www.python.org/ftp/python/$PyVer/python-$PyVer$arch.exe"
    $tmp = Join-Path $env:TEMP "python-$PyVer-installer.exe"
    Say "Python not found - downloading Python $PyVer (one time only)..."
    (New-Object Net.WebClient).DownloadFile($url, $tmp)
    Say "Installing Python $PyVer for this user (silent)..."
    $p = Start-Process $tmp -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_test=0 Include_doc=0 Include_tcltk=0" -Wait -PassThru
    Remove-Item $tmp -ErrorAction SilentlyContinue
    $short = $PyVer.Split(".")[0] + $PyVer.Split(".")[1]
    $Python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$short$(if (-not $Is64) {'-32'})\python.exe"
    if (-not (Test-Path $Python)) { $Python = Find-Python }
    if (-not $Python) { throw "Python install failed. Install Python $PyVer from python.org and run this again." }
}
Ok "Python: $Python"

# ------------------------------------------------------------- app files ---
if (-not (Test-Path $Root)) { New-Item -ItemType Directory $Root | Out-Null }

# Stop a running copy first (it restores the taskbar on exit)
$oldPyw = Join-Path $VenvDir "Scripts\pythonw.exe"
if ((Test-Path $oldPyw) -and (Test-Path (Join-Path $AppDir "run.pyw"))) {
    Start-Process $oldPyw -ArgumentList "`"$AppDir\run.pyw`" --quit" -Wait -ErrorAction SilentlyContinue
}

$LocalSrc = $null
if ($MyInvocation.MyCommand.Path) {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    if (Test-Path (Join-Path $here "nocthify\app.py")) { $LocalSrc = $here }
}

if ($LocalSrc) {
    Say "Installing from local folder $LocalSrc"
    if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
    New-Item -ItemType Directory $AppDir | Out-Null
    foreach ($item in @("nocthify", "run.pyw", "requirements.txt", "README.md", "LICENSE", "restore-taskbar.bat", "uninstall.ps1")) {
        $src = Join-Path $LocalSrc $item
        if (Test-Path $src) { Copy-Item $src $AppDir -Recurse -Force }
    }
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
    if (Test-Path (Join-Path $AppDir ".git")) {
        Say "Updating Nocthify (git pull)..."
        & git -C $AppDir pull --ff-only | Out-Null
    } else {
        if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
        Say "Downloading Nocthify (git clone)..."
        & git clone --depth 1 -b $Branch "https://github.com/$Repo.git" $AppDir | Out-Null
    }
} else {
    $zip = Join-Path $env:TEMP "nocthify.zip"
    $ex  = Join-Path $env:TEMP "nocthify_extract"
    Say "Downloading Nocthify..."
    (New-Object Net.WebClient).DownloadFile("https://github.com/$Repo/archive/refs/heads/$Branch.zip", $zip)
    if (Test-Path $ex) { Remove-Item $ex -Recurse -Force }
    New-Item -ItemType Directory $ex | Out-Null
    $shell = New-Object -ComObject Shell.Application          # works on PowerShell 2.0
    $shell.Namespace($ex).CopyHere($shell.Namespace($zip).Items(), 0x14)
    $inner = Get-ChildItem $ex | Where-Object { $_.PSIsContainer } | Select-Object -First 1
    if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
    Move-Item $inner.FullName $AppDir
    Remove-Item $zip, $ex -Recurse -Force -ErrorAction SilentlyContinue
}
Ok "Files: $AppDir"

# --------------------------------------------------------- environment ---
if (-not (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
    Say "Creating a private Python environment..."
    & $Python -m venv $VenvDir
}
$VPy  = Join-Path $VenvDir "Scripts\python.exe"
$VPyw = Join-Path $VenvDir "Scripts\pythonw.exe"
Say "Installing PyQt5 + psutil (first time takes a minute)..."
& $VPy -m pip install --upgrade --disable-pip-version-check -q pip 2>$null | Out-Null
if ($Win7 -or $Win8) {
    & $VPy -m pip install --disable-pip-version-check -q "PyQt5>=5.15,<5.16" "psutil<6"
} else {
    & $VPy -m pip install --disable-pip-version-check -q -r (Join-Path $AppDir "requirements.txt")
}
if ($LASTEXITCODE -ne 0) { throw "pip install failed - check your internet connection and run again." }
Ok "Dependencies installed"

# ------------------------------------------------------------ shortcuts ---
$wsh = New-Object -ComObject WScript.Shell
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
foreach ($def in @(@("Nocthify", ""), @("Nocthify Settings", "--settings"), @("Restore Windows Taskbar", "--restore-taskbar"))) {
    $lnk = $wsh.CreateShortcut((Join-Path $startMenu "$($def[0]).lnk"))
    $lnk.TargetPath = $VPyw
    $lnk.Arguments = "`"$AppDir\run.pyw`" $($def[1])".Trim()
    $lnk.WorkingDirectory = $AppDir
    $lnk.Description = "Nocthify - erzak"
    $lnk.Save()
}
Ok "Start Menu shortcuts created"

Say "Starting Nocthify..."
Start-Process $VPyw -ArgumentList "`"$AppDir\run.pyw`"" -WorkingDirectory $AppDir
Write-Host ""
Write-Host "   Done!  Hover the island at the top of the screen, right-click the Dock for options." -ForegroundColor Green
Write-Host "   Shortcuts:  Alt+Shift+Space = Apps,  Alt+Shift+C = Control Center" -ForegroundColor DarkGray
Write-Host "   Emergency:  Start Menu > 'Restore Windows Taskbar'" -ForegroundColor DarkGray
Write-Host ""
