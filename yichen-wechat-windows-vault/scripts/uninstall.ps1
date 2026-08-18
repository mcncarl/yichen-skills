param(
    [string]$WorkBuddyHome = "",
    [string]$McpClient = "workbuddy",
    [switch]$RemovePrivateData
)

$ErrorActionPreference = "Stop"
if (-not $WorkBuddyHome) {
    $WorkBuddyHome = if ($env:WORKBUDDY_HOME) { $env:WORKBUDDY_HOME } else { Join-Path $HOME ".workbuddy" }
}

# ── determine MCP config path ──
$McpConfigPath = switch ($McpClient.ToLower()) {
    "workbuddy" { Join-Path $WorkBuddyHome "mcp.json" }
    "claude"    { Join-Path $env:APPDATA "Claude\claude_desktop_config.json" }
    default     { $null }
}

# ── remove MCP entry ──
if ($McpConfigPath -and (Test-Path -LiteralPath $McpConfigPath)) {
    $Config = Get-Content -LiteralPath $McpConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($Config.mcpServers -and $Config.mcpServers.PSObject.Properties["wechat-windows-vault"]) {
        $Config.mcpServers.PSObject.Properties.Remove("wechat-windows-vault")
        $JsonOutput = $Config | ConvertTo-Json -Depth 10
        Copy-Item -LiteralPath $McpConfigPath -Destination "$McpConfigPath.bak" -Force
        [IO.File]::WriteAllText($McpConfigPath, $JsonOutput, [Text.UTF8Encoding]::new($false))
        Write-Output "mcp_removed: $McpConfigPath"
    }
}

# ── optionally remove private data ──
if ($RemovePrivateData) {
    $AppDir = Join-Path $env:LOCALAPPDATA "wechat-windows-vault"
    if (Test-Path -LiteralPath $AppDir) {
        Remove-Item -LiteralPath $AppDir -Recurse -Force
        Write-Output "private_data: removed"
    }
}

Write-Output "uninstalled: restart your MCP client"
