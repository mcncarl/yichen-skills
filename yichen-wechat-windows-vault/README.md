# wechat-windows-vault

Windows 微信本地资料库 MCP 技能 — 安全查询本机微信聊天记录，解码语音/图片消息，支持批量处理。

## 功能

- **会话查询**：会话列表、未读、联系人、群成员、聊天记录、搜索、统计、收藏、朋友圈
- **语音解码**：SILK V3 → WAV + faster-whisper 本地中文转写（离线，不上传）
- **图片解码**：legacy XOR / V1 AES / V2 AES-XOR / WXGF-HEVC 全格式
- **批量处理**：resumable 分批处理媒体消息，每批最多 5 条
- **隐私保护**：所有数据本地处理，密钥不外泄，原始数据库只读

## 系统要求

| 组件 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 x64 |
| Python | 3.10+（推荐 3.12/3.13） |
| Node.js | 18+（用于 SILK 语音解码） |
| 微信 | Windows 桌面版 4.1.10.53 或 4.1.12.26 |

## 快速安装

### 一键安装（推荐）

```powershell
# 1. 将本目录放到技能目录
#    WorkBuddy: ~/.workbuddy/skills/wechat-windows-vault/
#    通用:      任意目录

# 2. 运行安装脚本
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1

# 3. 激活 MCP 连接器
#    WorkBuddy: 打开连接器管理页 → 找到 wechat-windows-vault → 点击「信任」
```

### 手动安装

如果不使用 WorkBuddy，手动配置 MCP server：

#### 1. 创建 Python venv 并安装依赖

```powershell
python -m venv "%LOCALAPPDATA%\wechat-windows-vault\venv"
"%LOCALAPPDATA%\wechat-windows-vault\venv\Scripts\pip.exe" install -r scripts\requirements.txt
```

#### 2. 安装 Node.js SILK 解码器

```powershell
mkdir "%LOCALAPPDATA%\wechat-windows-vault\node-runtime"
npm install --prefix "%LOCALAPPDATA%\wechat-windows-vault\node-runtime" silk-wasm@3.7.1
copy node.exe "%LOCALAPPDATA%\wechat-windows-vault\node-runtime\node.exe"
```

#### 3. 注册 MCP Server

根据你的 MCP 客户端，将以下配置写入对应的配置文件：

**WorkBuddy** (`~/.workbuddy/mcp.json`):

```json
{
  "mcpServers": {
    "wechat-windows-vault": {
      "command": "C:\\Users\\YOUR_NAME\\AppData\\Local\\wechat-windows-vault\\venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\wechat-windows-vault\\scripts\\mcp_server.py"],
      "env": {
        "PYTHONUTF8": "1",
        "PYTHONPATH": "C:\\path\\to\\wechat-windows-vault\\scripts"
      }
    }
  }
}
```

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "wechat-windows-vault": {
      "command": "C:\\Users\\YOUR_NAME\\AppData\\Local\\wechat-windows-vault\\venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\wechat-windows-vault\\scripts\\mcp_server.py"],
      "env": {
        "PYTHONUTF8": "1",
        "PYTHONPATH": "C:\\path\\to\\wechat-windows-vault\\scripts"
      }
    }
  }
}
```

> 将 `YOUR_NAME` 和路径替换为你的实际路径。

## 首次使用

### 1. 密钥抓取

微信数据库使用 SQLCipher 加密，需要通过 frida hook 抓取密钥：

```powershell
$VaultPython = Join-Path $env:LOCALAPPDATA "wechat-windows-vault\venv\Scripts\python.exe"
& $VaultPython scripts\capture_keys.py --duration 120
```

抓取期间保持微信登录状态，打开需要查询的聊天、收藏、朋友圈和图片消息。

### 2. 刷新资料库

```powershell
& $VaultPython scripts\refresh_vault.py
```

确认所有数据库报告 `ok`。

### 3. 验证安装

```powershell
& $VaultPython scripts\self_test.py
& $VaultPython scripts\diagnose.py
```

## MCP 工具

| 工具 | 功能 |
|------|------|
| `wechat_vault_query` | 查询会话/联系人/历史/搜索/统计/收藏/朋友圈 |
| `wechat_vault_media` | 解码单条语音或图片消息（含语音转写） |
| `wechat_vault_media_batch` | 批量处理媒体消息（每批最多 5 条） |
| `wechat_vault_image` | 加载解码后的图片到视觉上下文 |

## 隐私规则

- 密钥、数据库、解码媒体仅存储在 `%LOCALAPPDATA%\wechat-windows-vault`
- 原始微信数据库目录（`xwechat_files`）保持只读
- 不向任何外部服务上传数据
- 语音转写使用本地 faster-whisper 模型，离线运行

## 卸载

```powershell
powershell -ExecutionPolicy Bypass -File scripts\uninstall.ps1 -RemovePrivateData
```

## 支持的微信版本

| 微信版本 | Weixin.dll SHA-256 | 状态 |
|----------|-------------------|------|
| 4.1.10.53 | `AB35CFBD...` | 已验证 |
| 4.1.12.26 | `4914A621...` | 已验证（20/20 数据库通过 HMAC 校验） |
| 4.1.12.25 | `2E5348D7...` | 不支持（profile 未验证） |

其他版本需要手动添加 profile，详见 [references/compatibility.md](references/compatibility.md)。

## 许可

仅供个人使用，查询本人微信账号的本地数据。请遵守相关法律法规。
