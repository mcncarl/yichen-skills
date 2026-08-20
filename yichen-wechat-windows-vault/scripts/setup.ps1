[CmdletBinding()]
param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillRoot = Split-Path -Parent $ScriptRoot
$RuntimeRoot = Join-Path $env:LOCALAPPDATA "yichen-wechat-windows-vault"
$Venv = Join-Path $RuntimeRoot "venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Unable to create virtual environment." }
}

& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $SkillRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& $VenvPython (Join-Path $ScriptRoot "self_test.py")
if ($LASTEXITCODE -ne 0) { throw "Self-test failed." }

Write-Output "Runtime ready: $RuntimeRoot"
Write-Output "No Codex, Hermes, MCP, startup-task, or WeChat configuration was changed."
