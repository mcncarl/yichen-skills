[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$DbRoot,
    [int]$Duration = 20,
    [int]$Pid = 0,
    [string]$VaultHome = ""
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $env:LOCALAPPDATA "yichen-wechat-windows-vault\venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Runtime not found. Run setup.ps1 first."
}

$captureArgs = @((Join-Path $ScriptRoot "capture_keys.py"), "--db-root", $DbRoot, "--duration", $Duration)
$refreshArgs = @((Join-Path $ScriptRoot "refresh_vault.py"), "--db-root", $DbRoot)
if ($Pid -eq 0) {
    $candidates = @(Get-Process -Name Weixin -ErrorAction Stop | Where-Object {
        try { @($_.Modules | Where-Object { $_.ModuleName -ieq "Weixin.dll" }).Count -eq 1 }
        catch { $false }
    })
    if ($candidates.Count -ne 1) {
        throw "Expected exactly one Weixin.exe process with Weixin.dll loaded; pass -Pid explicitly."
    }
    $Pid = $candidates[0].Id
}
$captureArgs += @("--pid", $Pid)
if ($VaultHome) {
    $captureArgs += @("--vault-home", $VaultHome)
    $refreshArgs += @("--vault-home", $VaultHome)
}

& $Python @captureArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python @refreshArgs
exit $LASTEXITCODE
