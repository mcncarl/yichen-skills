param(
    [string]$Python = "python",
    [string]$WorkBuddyHome = "",
    [string]$McpClient = "workbuddy",
    [switch]$SkipMcp,
    [switch]$SkipModelDownload
)

$ErrorActionPreference = "Stop"
$SkillRoot = Split-Path -Parent $PSScriptRoot
$AppDir = Join-Path $env:LOCALAPPDATA "wechat-windows-vault"
$VenvDir = Join-Path $AppDir "venv"
$Requirements = Join-Path $PSScriptRoot "requirements.txt"
$McpServer = Join-Path $PSScriptRoot "mcp_server.py"

if (-not $WorkBuddyHome) {
    $WorkBuddyHome = if ($env:WORKBUDDY_HOME) { $env:WORKBUDDY_HOME } else { Join-Path $HOME ".workbuddy" }
}

# ── venv ──
New-Item -ItemType Directory -Path $AppDir -Force | Out-Null
if (-not (Test-Path -LiteralPath (Join-Path $VenvDir "Scripts\python.exe"))) {
    & $Python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create Python virtual environment (exit code $LASTEXITCODE)"
    }
}
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$Uv = Get-Command uv -ErrorAction SilentlyContinue
if ($Uv) {
    & $Uv.Source pip install --python $VenvPython -r $Requirements
} else {
    & $VenvPython -m pip install --disable-pip-version-check --timeout 120 --retries 3 -r $Requirements
}
if ($LASTEXITCODE -ne 0) {
    throw "Python dependency installation failed (exit code $LASTEXITCODE)"
}

# ── node-runtime + silk-wasm ──
$NodeRuntime = Join-Path $AppDir "node-runtime"
$SilkModule = Join-Path $NodeRuntime "node_modules\silk-wasm"
if (-not (Test-Path -LiteralPath $SilkModule)) {
    $Npm = Get-Command npm -ErrorAction SilentlyContinue
    $Pnpm = Get-Command pnpm -ErrorAction SilentlyContinue
    if ($Npm) {
        & $Npm.Source install --prefix $NodeRuntime --no-audit --no-fund silk-wasm@3.7.1
    } elseif ($Pnpm) {
        & $Pnpm.Source add --dir $NodeRuntime --ignore-scripts silk-wasm@3.7.1
    } else {
        throw "npm or pnpm is required to install the SILK voice decoder"
    }
    if ($LASTEXITCODE -ne 0) {
        throw "SILK dependency installation failed (exit code $LASTEXITCODE)"
    }
}

# ── locate node.exe ──
$NodeCandidates = @(
    (Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
    (Join-Path $NodeRuntime "node.exe")
)
$NodeExecutable = $NodeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $NodeExecutable) {
    throw "Node.js runtime is required for SILK voice decoding"
}
if (-not (Test-Path -LiteralPath (Join-Path $NodeRuntime "node.exe"))) {
    Copy-Item -LiteralPath $NodeExecutable -Destination (Join-Path $NodeRuntime "node.exe")
}

# ── whisper model ──
if (-not $SkipModelDownload) {
    $VoiceModel = if ($env:WECHAT_VAULT_WHISPER_MODEL) { $env:WECHAT_VAULT_WHISPER_MODEL } else { "small" }
    & $VenvPython -c "import sys; from faster_whisper import WhisperModel; WhisperModel(sys.argv[1], device='cpu', compute_type='int8'); print('voice_model: ready')" $VoiceModel
    if ($LASTEXITCODE -ne 0) {
        throw "Voice model download failed (exit code $LASTEXITCODE)"
    }
}

# ── register MCP server ──
if (-not $SkipMcp) {
    $McpEntry = [ordered]@{
        command = $VenvPython
        args    = @($McpServer)
        env     = [ordered]@{
            PYTHONUTF8  = "1"
            PYTHONPATH  = $PSScriptRoot
        }
    }

    $McpConfigPath = switch ($McpClient.ToLower()) {
        "workbuddy" {
            New-Item -ItemType Directory -Path $WorkBuddyHome -Force | Out-Null
            Join-Path $WorkBuddyHome "mcp.json"
        }
        "claude" {
            $ClaudeDir = Join-Path $env:APPDATA "Claude"
            New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null
            Join-Path $ClaudeDir "claude_desktop_config.json"
        }
        default {
            Write-Output "mcp_client: $McpClient (no auto-registration)"
            $null
        }
    }

    if ($McpConfigPath) {
        if (Test-Path -LiteralPath $McpConfigPath) {
            $Existing = Get-Content -LiteralPath $McpConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
            if (-not $Existing.mcpServers) {
                $Existing | Add-Member -NotePropertyName mcpServers -NotePropertyValue @{} -Force
            }
            if ($Existing.mcpServers.PSObject.Properties["wechat-windows-vault"]) {
                $Existing.mcpServers."wechat-windows-vault" = $McpEntry
            } else {
                $Existing.mcpServers | Add-Member -NotePropertyName "wechat-windows-vault" -NotePropertyValue $McpEntry -Force
            }
            $JsonOutput = $Existing | ConvertTo-Json -Depth 10
        } else {
            $NewConfig = [ordered]@{ mcpServers = [ordered]@{ "wechat-windows-vault" = $McpEntry } }
            $JsonOutput = $NewConfig | ConvertTo-Json -Depth 10
        }

        if (Test-Path -LiteralPath $McpConfigPath) {
            Copy-Item -LiteralPath $McpConfigPath -Destination "$McpConfigPath.bak" -Force
        }
        [IO.File]::WriteAllText($McpConfigPath, $JsonOutput, [Text.UTF8Encoding]::new($false))
        Write-Output "mcp_registered: $McpConfigPath"
    }

    if ($McpClient.ToLower() -eq "workbuddy") {
        Write-Output "next: activate the wechat-windows-vault connector in WorkBuddy (top-right -> Trust)"
    } elseif ($McpClient.ToLower() -eq "claude") {
        Write-Output "next: restart Claude Desktop"
    }
}

# ── self test ──
& $VenvPython (Join-Path $PSScriptRoot "self_test.py")
if ($LASTEXITCODE -ne 0) {
    Write-Warning "self_test.py reported issues; run diagnose.py for details"
}

Write-Output "runtime_python: $VenvPython"
Write-Output "private_data: $AppDir"
