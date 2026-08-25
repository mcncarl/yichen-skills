#!/usr/bin/env python3
"""Inspect portable web-research backends without reading private content."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = Path(
    os.environ.get("YICHEN_SKILLS_ROOT", str(REPOSITORY_ROOT))
).expanduser()
OPENCLI_HOME = Path(
    os.environ.get("OPENCLI_HOME", str(Path.home() / ".opencli"))
).expanduser()
STEP_ASR = Path(
    os.environ.get(
        "YICHEN_STEP_ASR_SCRIPT",
        str(SKILLS_ROOT / "step-asr/scripts/step_asr_transcribe.py"),
    )
).expanduser()
UNIFIED_ASR_DOCTOR = (
    SKILLS_ROOT / "yichen-asr/scripts/asr_doctor.py"
)
ARCHIVE_SCRIPTS = (
    SKILLS_ROOT / "yichen-content-archive/scripts"
)
FXTWITTER_SEARCH = (
    SKILLS_ROOT / "yichen-unified-search/scripts/fxtwitter_search.py"
)
X_KNOWN_URL = ARCHIVE_SCRIPTS / "x_known_url.py"
XIAOYUZHOU = ARCHIVE_SCRIPTS / "xiaoyuzhou_stepfun.py"
XIAOYUZHOU_OPENCLI = ARCHIVE_SCRIPTS / "xiaoyuzhou_opencli.py"
XIAOYUZHOU_OPENCLI_CREDENTIALS = Path(
    os.environ.get(
        "YICHEN_XIAOYUZHOU_CREDENTIAL_FILE",
        str(OPENCLI_HOME / "xiaoyuzhou.json"),
    )
).expanduser()
WECHAT_MP_LOCAL = ARCHIVE_SCRIPTS / "wechat_mp_local.py"
TOUTIAO_SEARCH_ADAPTER = OPENCLI_HOME / "clis/toutiao/search.js"
TOUTIAO_HEADLESS_ADAPTER = OPENCLI_HOME / "clis/toutiao/headless.js"
TOUTIAO_ANONYMOUS_PROFILE = OPENCLI_HOME / "toutiao-anonymous-profile"
SYSTEM_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
GROK_CLI_VALUE = (
    os.environ.get("GROK_CLI")
    or shutil.which("grok")
    or str(Path.home() / ".grok/bin/grok")
)
GROK_CLI = Path(GROK_CLI_VALUE).expanduser()
GROK_AUTH = Path(
    os.environ.get("GROK_AUTH_FILE", str(Path.home() / ".grok/auth.json"))
).expanduser()
GROK_CONSULT_ROOT_VALUE = os.environ.get("YICHEN_GROK_CONSULT_ROOT")
GROK_CONSULT_ROOT = (
    Path(GROK_CONSULT_ROOT_VALUE).expanduser()
    if GROK_CONSULT_ROOT_VALUE
    else None
)
CODEX_CONFIG = Path(
    os.environ.get("CODEX_CONFIG", str(Path.home() / ".codex/config.toml"))
).expanduser()
FIRECRAWL_UNIFIED_ADAPTER = (
    SKILLS_ROOT / "yichen-unified-search/scripts/firecrawl_adapter.py"
)
FIRECRAWL_KEY_FILE = Path(
    os.environ.get(
        "FIRECRAWL_KEY_FILE",
        str(Path.home() / ".config/agent-secrets/firecrawl-api-key"),
    )
).expanduser()
ZHIHU_ADAPTER = SKILLS_ROOT / "yichen-unified-search/scripts/zhihu_adapter.py"
ZHIHU_CLI_VALUE = (
    os.environ.get("ZHIHU_CLI")
    or shutil.which("zhihu-cli")
    or str(
        Path.home()
        / "Library/Application Support/zhihu-cli/current/zhihu-cli"
    )
)
ZHIHU_CLI = Path(ZHIHU_CLI_VALUE).expanduser()
ZHIHU_PUBLIC_CAPABILITIES = frozenset({"search zhihu", "hot"})
ZHIHU_PUBLIC_ADAPTER_COMMANDS = frozenset({"search", "hot"})
SAFE_METADATA_ENV_NAMES = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TZ",
        "TMPDIR",
        "TEMP",
        "TMP",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
    }
)


def safe_metadata_environment(
    environ: dict[str, str] | None = None,
) -> dict[str, str]:
    """Keep only runtime settings for offline third-party metadata checks."""

    source = os.environ if environ is None else environ
    return {
        name: value
        for name, value in source.items()
        if name.upper() in SAFE_METADATA_ENV_NAMES
    }


def firecrawl_key_source() -> str | None:
    """Report Firecrawl key availability without reading the secret."""
    if os.environ.get("FIRECRAWL_API_KEY"):
        return "environment"
    try:
        metadata = FIRECRAWL_KEY_FILE.lstat()
    except OSError:
        return None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
        or metadata.st_size <= 3
    ):
        return None
    return "private_file"


def zhihu_metadata(command: tuple[str, ...]) -> dict[str, object] | None:
    """Run one documented offline CLI metadata command without leaking output."""
    environment = safe_metadata_environment()
    try:
        result = subprocess.run(
            [str(ZHIHU_CLI), *command],
            check=False,
            text=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=10,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def zhihu_adapter_commands() -> set[str]:
    """Read only the adapter's argparse command surface; never execute it."""
    try:
        tree = ast.parse(ZHIHU_ADAPTER.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()

    commands: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (
            node.func.attr == "add_parser"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            commands.add(node.args[0].value.strip().lower())
            continue
        if node.func.attr != "add_argument" or not node.args:
            continue
        first = node.args[0]
        if not (
            isinstance(first, ast.Constant)
            and first.value in {"command", "mode"}
        ):
            continue
        choices = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "choices"),
            None,
        )
        if not isinstance(choices, (ast.List, ast.Tuple, ast.Set)):
            continue
        commands.update(
            item.value.strip().lower()
            for item in choices.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
    return commands


def zhihu_channel_status() -> dict[str, object]:
    """Inspect the explicit Zhihu backend using offline metadata only."""
    adapter_present = ZHIHU_ADAPTER.is_file()
    adapter_commands = zhihu_adapter_commands() if adapter_present else set()
    public_commands_only = adapter_commands == ZHIHU_PUBLIC_ADAPTER_COMMANDS
    personal_commands_exposed = any(
        command == "me" or command.startswith("me ")
        for command in adapter_commands
    )
    adapter_ready = bool(
        adapter_present and public_commands_only and not personal_commands_exposed
    )
    cli_executable = ZHIHU_CLI.is_file() and os.access(ZHIHU_CLI, os.X_OK)

    version: dict[str, object] | None = None
    capabilities: dict[str, object] | None = None
    auth: dict[str, object] | None = None
    if cli_executable:
        version = zhihu_metadata(("version",))
        capabilities = zhihu_metadata(("capabilities",))
        auth = zhihu_metadata(("auth", "status"))

    version_ready = bool(
        version
        and all(
            isinstance(version.get(field), str) and bool(version.get(field))
            for field in ("name", "version", "os", "arch")
        )
    )
    capability_items = (capabilities or {}).get("commands", [])
    if not isinstance(capability_items, list):
        capability_items = []
    capability_names = {
        str(item.get("name", "")).strip().lower()
        for item in capability_items
        if isinstance(item, dict)
    }
    capabilities_ready = ZHIHU_PUBLIC_CAPABILITIES.issubset(capability_names)
    auth_status_ready = bool(
        auth
        and isinstance(auth.get("ok"), bool)
        and isinstance(auth.get("environment_set"), bool)
        and isinstance(auth.get("keychain"), str)
        and isinstance(auth.get("verification"), str)
        and isinstance(auth.get("environment_shadows_keychain"), bool)
    )

    keychain_configured = bool(
        auth_status_ready
        and (
            auth.get("keychain") == "found"
            or (
                auth.get("keychain") == "available"
                and auth.get("source") == "keychain"
            )
        )
    )
    auth_configured = bool(
        auth_status_ready
        and auth.get("ok") is True
        and auth.get("environment_set") is False
        and keychain_configured
        and auth.get("verification") == "not_performed"
        and auth.get("environment_shadows_keychain") is False
    )
    cli_ready = bool(cli_executable and version_ready and capabilities_ready)
    ready = adapter_ready and cli_ready and auth_configured
    missing = [
        label
        for label, present in (
            ("unified zhihu_adapter", adapter_ready),
            ("configured CLI/offline metadata", cli_ready),
            ("Keychain authentication", auth_configured),
        )
        if not present
    ]

    return {
        "status": "ok" if ready else "warn",
        "name": "知乎 Open Platform CLI 站内搜索与热榜",
        "message": (
            "显式知乎公开候选后端就绪；未执行网络探针"
            if ready
            else "显式知乎后端尚未就绪：" + ", ".join(missing)
        ),
        "tier": 1,
        "backends": ["configured zhihu-cli via unified-search adapter"],
        "active_backend": "zhihu-open-platform-cli" if ready else None,
        "adapter_ready": adapter_ready,
        "cli_ready": cli_ready,
        "auth_configured": auth_configured,
        "credential_source": "keychain" if auth_configured else None,
        "network_probe_performed": False,
        "default_backend": False,
        "public_commands_only": public_commands_only,
        "personal_commands_exposed": personal_commands_exposed,
        "metadata_checks": {
            "version": version_ready,
            "capabilities": capabilities_ready,
            "auth_status": auth_status_ready,
        },
    }


def stepfun_key_available() -> bool:
    """Report only explicitly exported Step credentials.

    The public doctor deliberately does not import or execute the configured
    Step ASR script: ``YICHEN_STEP_ASR_SCRIPT`` may point to user-controlled
    code, while a read-only readiness check must not execute arbitrary modules.
    """
    return bool(os.environ.get("STEPFUN_API_KEY") or os.environ.get("STEP_API_KEY"))


def unified_asr_status() -> dict[str, object] | None:
    if not UNIFIED_ASR_DOCTOR.is_file():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(UNIFIED_ASR_DOCTOR)],
            check=False,
            text=True,
            capture_output=True,
            timeout=20,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def fieldtheory_graphql_only_status() -> tuple[bool, str]:
    executable = shutil.which("ft")
    if not executable:
        return False, "Field Theory 命令缺失"
    try:
        version = subprocess.run(
            [executable, "--version"],
            check=True,
            text=True,
            capture_output=True,
            timeout=10,
        ).stdout.strip()
        root_help = subprocess.run(
            [executable, "--help"],
            check=True,
            text=True,
            capture_output=True,
            timeout=10,
        ).stdout
        sync_help = subprocess.run(
            [executable, "sync", "--help"],
            check=True,
            text=True,
            capture_output=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Field Theory 帮助检查失败：{exc}"

    package_root = Path(executable).resolve().parent.parent
    graphql_runtime = package_root / "dist" / "graphql-bookmarks.js"
    removed_runtime_files = [
        package_root / "dist" / "xauth.js",
        package_root / "dist" / "bookmarks.js",
    ]
    has_removed_command = any(line.strip().startswith("auth ") for line in root_help.splitlines())
    has_removed_flag = "--api" in sync_help
    ready = (
        "graphql-only" in version
        and graphql_runtime.exists()
        and not any(path.exists() for path in removed_runtime_files)
        and not has_removed_command
        and not has_removed_flag
    )
    if ready:
        return True, f"Field Theory {version} GraphQL-only 路线就绪；doctor 不读取私人书签"
    return False, "Field Theory 不是预期的 GraphQL-only 本地覆盖层"


def wechat_mp_local_status() -> tuple[bool, str, bool]:
    if not WECHAT_MP_LOCAL.exists():
        return False, "公众号本地客户端缺失", False
    try:
        result = subprocess.run(
            [sys.executable, str(WECHAT_MP_LOCAL), "status"],
            check=False,
            text=True,
            capture_output=True,
            timeout=15,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return False, f"公众号本地服务检查失败：{exc}", False
    service_ready = bool(payload.get("service_reachable")) and bool(payload.get("localhost_only"))
    login_ready = payload.get("login_status") == "ready"
    if service_ready and login_ready:
        return True, "本机私有服务可用；公众号搜索登录态就绪", True
    if service_ready:
        return (
            True,
            "本机私有服务可用；已知链接可抓取，公众号搜索登录态未读取",
            False,
        )
    return False, "本机私有服务不可用", False


def opencli_search_metadata(site: str) -> dict | None:
    """Read effective OpenCLI search metadata without opening a page or reading login state."""
    executable = shutil.which("opencli")
    if not executable:
        return None
    try:
        result = subprocess.run(
            [executable, site, "search", "--help", "-f", "json"],
            check=False,
            text=True,
            capture_output=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def search_metadata_has_args(metadata: dict | None, required_flags: tuple[str, ...]) -> bool:
    if not metadata:
        return False
    items = metadata.get("positionals", []) + metadata.get("command_options", [])
    names = {
        str(item.get("name", ""))
        for item in items
        if isinstance(item, dict)
    }
    return all(flag.lstrip("-") in names for flag in required_flags)


def opencli_search_available(site: str, required_flags: tuple[str, ...]) -> bool:
    return search_metadata_has_args(opencli_search_metadata(site), required_flags)


def toutiao_search_contract_ready() -> bool:
    metadata = opencli_search_metadata("toutiao")
    if not search_metadata_has_args(metadata, ("query", "--days", "--limit")):
        return False
    effective_contract = (
        metadata.get("access") == "read"
        and metadata.get("browser") is False
        and metadata.get("domain") == "so.toutiao.com"
    )
    if (
        not effective_contract
        or not TOUTIAO_SEARCH_ADAPTER.is_file()
        or not TOUTIAO_HEADLESS_ADAPTER.is_file()
        or not SYSTEM_CHROME.is_file()
    ):
        return False
    try:
        source = TOUTIAO_SEARCH_ADAPTER.read_text(encoding="utf-8")
        headless_source = TOUTIAO_HEADLESS_ADAPTER.read_text(encoding="utf-8")
    except OSError:
        return False
    return (
        "strategy: Strategy.PUBLIC" in source
        and "browser: false" in source
        and "isVideoCard" in source
        and "filter_period" in headless_source
        and "toutiao-anonymous-profile" in headless_source
        and "--user-data-dir=" in headless_source
    )


def xiaoyuzhou_opencli_available() -> bool:
    executable = shutil.which("opencli")
    if not executable or not XIAOYUZHOU_OPENCLI.exists():
        return False
    try:
        result = subprocess.run(
            [executable, "xiaoyuzhou", "--help"],
            check=False,
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    required_commands = {"podcast", "podcast-episodes", "episode", "download", "transcript"}
    return result.returncode == 0 and all(command in result.stdout for command in required_commands)


def grok_consult_source_ready() -> bool:
    if GROK_CONSULT_ROOT is None:
        return False
    server_path = GROK_CONSULT_ROOT / "mcp" / "server.mjs"
    skill_paths = (
        GROK_CONSULT_ROOT / "skills" / "yichen-grok-consult" / "SKILL.md",
        GROK_CONSULT_ROOT / "skills" / "grok-consult" / "SKILL.md",
    )
    skill_path = next((path for path in skill_paths if path.is_file()), None)
    if not server_path.is_file() or skill_path is None:
        return False
    try:
        server = server_path.read_text(encoding="utf-8")
        skill = skill_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return all(
        marker in server
        for marker in (
            '"official_cli_account_quota"',
            "callFxTwitterSearch",
            "callOpenCliSearch",
            "callXreachSearch",
            "explicit quota-exhaustion evidence",
            "allow_authenticated_fallback",
            "authenticated_fallback_requires_current_task_authorization",
        )
    ) and "search_x_with_grok" in skill


def grok_consult_enabled() -> bool:
    override = os.environ.get("YICHEN_GROK_CONSULT_ENABLED")
    if override is not None:
        return override == "1"
    if not CODEX_CONFIG.is_file():
        return False
    try:
        source = CODEX_CONFIG.read_text(encoding="utf-8")
    except OSError:
        return False
    match = re.search(
        r'(?ms)^\[plugins\."(?:grok-consult|yichen-grok-consult)@[^"\]]+"\]\s*$'
        r'(?P<body>.*?)(?=^\[|\Z)',
        source,
    )
    return bool(
        match
        and re.search(r"(?m)^\s*enabled\s*=\s*true\s*$", match.group("body"))
    )


def grok_cli_authenticated() -> bool:
    if not GROK_CLI.is_file() or not GROK_AUTH.is_file():
        return False
    try:
        result = subprocess.run(
            [str(GROK_CLI), "models"],
            check=False,
            text=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    output = f"{result.stdout}\n{result.stderr}".lower()
    return "you are logged in with grok.com." in output


def local_public_channels() -> dict[str, dict[str, object]]:
    """Build the public base-channel inventory from direct local checks."""
    gh_ready = shutil.which("gh") is not None
    ytdlp_ready = shutil.which("yt-dlp") is not None
    bili_ready = shutil.which("bili") is not None
    curl_ready = shutil.which("curl") is not None
    firecrawl_adapter_ready = FIRECRAWL_UNIFIED_ADAPTER.is_file()
    firecrawl_credential_source = firecrawl_key_source()
    firecrawl_ready = bool(
        firecrawl_adapter_ready and firecrawl_credential_source
    )
    return {
        "github": {
            "status": "ok" if gh_ready else "warn",
            "name": "GitHub 仓库和代码",
            "message": (
                "gh CLI 只读路由可用（仓库、代码、Issue、PR、Release）"
                if gh_ready
                else "gh CLI 缺失"
            ),
            "tier": 0,
            "backends": ["gh CLI"],
            "active_backend": "gh CLI" if gh_ready else None,
        },
        "youtube": {
            "status": "ok" if ytdlp_ready else "warn",
            "name": "YouTube 视频和字幕",
            "message": (
                "yt-dlp 可读取公开视频信息并按明确请求下载"
                if ytdlp_ready
                else "yt-dlp 缺失"
            ),
            "tier": 0,
            "backends": ["yt-dlp"],
            "active_backend": "yt-dlp" if ytdlp_ready else None,
        },
        "bilibili": {
            "status": "ok" if bili_ready and ytdlp_ready else "warn",
            "name": "B站视频、字幕和搜索",
            "message": (
                "bili-cli 搜索/详情与 yt-dlp 明确链接下载均可用"
                if bili_ready and ytdlp_ready
                else "缺少：" + ", ".join(
                    name
                    for name, ready in (
                        ("bili-cli", bili_ready),
                        ("yt-dlp", ytdlp_ready),
                    )
                    if not ready
                )
            ),
            "tier": 1,
            "backends": ["bili-cli", "yt-dlp", "OpenCLI"],
            "active_backend": (
                "bili-cli + yt-dlp" if bili_ready and ytdlp_ready else None
            ),
        },
        "web": {
            "status": "ok" if curl_ready else "warn",
            "name": "公共网页",
            "message": (
                "AnySearch/Web Reader 由运行时路由；本地 curl 可用；"
                + (
                    "Firecrawl 显式 Map/Scrape 路线已配置"
                    if firecrawl_ready
                    else "Firecrawl 为可选显式路线，当前适配器或凭证未齐"
                )
                if curl_ready
                else "本地 curl 缺失；运行时仍需检查搜索/网页读取工具"
            ),
            "tier": 0,
            "backends": [
                "AnySearch",
                "Web Reader",
                "Jina Reader",
                "Firecrawl explicit Map/Scrape routes",
            ],
            "active_backend": "runtime router" if curl_ready else None,
            "firecrawl": {
                "configured": firecrawl_ready,
                "adapter_ready": firecrawl_adapter_ready,
                "credential_source": firecrawl_credential_source,
                "default_backend": False,
                "network_probe_performed": False,
            },
        },
    }


def main() -> None:
    channels = local_public_channels()
    channels["zhihu"] = zhihu_channel_status()

    asr = unified_asr_status()
    asr_ready = bool(asr and asr.get("ok"))
    channels["asr"] = {
        "status": "ok" if asr_ready else "warn",
        "name": "统一音视频 ASR",
        "message": (
            "统一 Step/豆包路由就绪；豆包余额仍需登录费用中心核验"
            if asr_ready
            else "统一 ASR 路由或其底层凭证未就绪"
        ),
        "tier": 1,
        "backends": ["Step ASR", "Doubao/Volcengine ASR"],
        "active_backend": "yichen-asr" if asr_ready else None,
        "billing_status": (
            asr.get("doubao", {}).get("billing_status")
            if isinstance(asr, dict)
            and isinstance(asr.get("doubao"), dict)
            else "unknown"
        ),
    }

    grok_source_ready = grok_consult_source_ready()
    grok_plugin_enabled = grok_consult_enabled()
    grok_authenticated = grok_cli_authenticated()
    fxtwitter_adapter_ready = FXTWITTER_SEARCH.is_file()
    x_known_url_adapter_ready = X_KNOWN_URL.is_file()
    opencli_twitter_ready = opencli_search_available("twitter", ("query", "--limit"))
    xreach_ready = shutil.which("xreach") is not None
    old_twitter_backend_absent = shutil.which("twitter") is None
    grok_primary_ready = all(
        (
            grok_source_ready,
            grok_plugin_enabled,
            grok_authenticated,
        )
    )
    twitter_fallback_ready = all(
        (
            fxtwitter_adapter_ready,
            opencli_twitter_ready,
            xreach_ready,
            old_twitter_backend_absent,
        )
    )
    twitter_ready = all(
        (
            grok_primary_ready,
            fxtwitter_adapter_ready,
            x_known_url_adapter_ready,
        )
    )
    twitter_missing = [
        name
        for name, ready in (
            ("grok_consult_source", grok_source_ready),
            ("grok_consult_enabled", grok_plugin_enabled),
            ("grok_cli_authenticated", grok_authenticated),
            ("fxtwitter_adapter", fxtwitter_adapter_ready),
            ("x_known_url_adapter", x_known_url_adapter_ready),
            ("opencli_twitter_adapter", opencli_twitter_ready),
            ("xreach", xreach_ready),
            ("old_backend_removed", old_twitter_backend_absent),
        )
        if not ready
    ]
    channels["twitter"] = {
        "status": "ok" if twitter_ready else "warn",
        "name": "Twitter/X Grok 优先搜索与匿名链接解析",
        "message": (
            "Grok CLI 原生 X 搜索、仅额度耗尽触发的 FxTwitter 回退、X 已知链接解析与当前任务授权闸门后的 OpenCLI → xreach 末级链均就绪"
            if twitter_ready and twitter_fallback_ready
            else "X Grok 优先搜索、匿名适配器或末级回退当前缺少："
            + ", ".join(twitter_missing)
        ),
        "tier": 1,
        "backends": [
            "official Grok CLI account quota + native x_search",
            "FxTwitter public API only after explicit quota exhaustion",
            "known X URL: FxTwitter -> Jina, no login state",
            "OpenCLI Chrome session read-only adapter, current-task authorization required",
            "xreach read-only GraphQL client, current-task authorization required",
        ],
        "active_backend": "official_cli_account_quota" if grok_primary_ready else None,
        "search_route": [
            "official_cli_account_quota",
            "fxtwitter-public",
            "opencli",
            "xreach",
        ],
        "fxtwitter_fallback_condition": "explicit_account_quota_exhausted_only",
        "fxtwitter_adapter_ready": fxtwitter_adapter_ready,
        "known_url_adapter_ready": x_known_url_adapter_ready,
        "primary_login_required": True,
        "primary_account_oauth_used": True,
        "grok_primary_ready": grok_primary_ready,
        "fallback_chain_ready": twitter_fallback_ready,
        "authenticated_fallback_authorization_required": True,
        "authenticated_fallback_default_allowed": False,
        "grok_consult_source_ready": grok_source_ready,
        "grok_consult_enabled": grok_plugin_enabled,
        "grok_cli_authenticated": grok_authenticated,
        "grok_oauth_auto_refresh": True,
        "manual_login_required_each_run": False,
        "opencli_twitter_adapter_ready": opencli_twitter_ready,
        "xreach_ready": xreach_ready,
        "old_twitter_backend_absent": old_twitter_backend_absent,
    }

    xiaohongshu_search_ready = opencli_search_available(
        "xiaohongshu", ("query", "--days", "--content", "--limit", "--enrich")
    )
    channels["xiaohongshu"] = {
        "status": "ok" if xiaohongshu_search_ready else "warn",
        "name": "小红书公开笔记与站内搜索",
        "message": (
            "匿名已知链接路线可用；OpenCLI 有界公开只读站内搜索可自动复用 Chrome 登录态，无需逐次授权，并受单关键词、20 条上限和串行限速约束"
            if xiaohongshu_search_ready
            else "匿名已知链接路线可用；OpenCLI 站内搜索适配器不可用"
        ),
        "tier": 1,
        "backends": ["anonymous known-link fetch", "OpenCLI Chrome session search"],
        "active_backend": "anonymous known-link fetch + bounded read-only OpenCLI search",
        "search_adapter_ready": xiaohongshu_search_ready,
        "time_filter_options": [0, 1, 7, 180],
        "content_filter_options": ["all", "video", "image"],
        "detail_enrichment_available": xiaohongshu_search_ready,
        "enriched_fields": ["likes", "comments", "collects", "shares", "engagement_total", "published_at", "author_followers", "url"],
        "login_required_for_search": True,
        "current_turn_authorization_required": False,
        "write_or_private_scope_authorization_required": True,
        "rate_limit_policy": {
            "max_results": 20,
            "serial": True,
            "minimum_gap_seconds": 5,
        },
    }

    douyin_search_ready = opencli_search_available(
        "douyin", ("query", "--days", "--content", "--limit", "--enrich")
    )
    channels["douyin"] = {
        "status": "ok" if douyin_search_ready else "warn",
        "name": "抖音公开视频站内搜索",
        "message": (
            "OpenCLI 有界公开只读综合搜索可自动复用 Chrome 登录态，无需逐次授权，并受单关键词、30 条上限和串行限速约束"
            if douyin_search_ready
            else "OpenCLI 抖音搜索适配器不可用"
        ),
        "tier": 1,
        "backends": ["OpenCLI Chrome session search"],
        "active_backend": (
            "bounded read-only OpenCLI search" if douyin_search_ready else None
        ),
        "search_adapter_ready": douyin_search_ready,
        "time_filter_options": [0, 1, 7, 180],
        "content_filter_options": ["all", "video", "image"],
        "detail_enrichment_available": douyin_search_ready,
        "enriched_fields": ["likes", "comments", "collects", "shares", "engagement_total", "published_at", "author_followers", "url"],
        "login_required_for_search": True,
        "current_turn_authorization_required": False,
        "write_or_private_scope_authorization_required": True,
        "rate_limit_policy": {
            "max_results": 30,
            "serial": True,
            "minimum_gap_seconds": 5,
        },
    }

    toutiao_search_ready = toutiao_search_contract_ready()
    channels["toutiao"] = {
        "status": "ok" if toutiao_search_ready else "warn",
        "name": "今日头条综合全网非视频搜索",
        "message": (
            "综合全网非视频搜索就绪；专用匿名 Chrome 使用服务器时间筛选，不读取用户 Chrome 或账号登录态"
            if toutiao_search_ready
            else "OpenCLI 今日头条匿名公开搜索适配器不可用"
        ),
        "tier": 1,
        "backends": ["OpenCLI + dedicated anonymous headless Chrome"],
        "active_backend": "anonymous synthesis/all-content non-video search" if toutiao_search_ready else None,
        "search_adapter_ready": toutiao_search_ready,
        "login_required_for_search": False,
        "opencli_browser_bridge_required": False,
        "dedicated_headless_chrome_required": True,
        "user_chrome_state_used": False,
        "anonymous_profile": str(TOUTIAO_ANONYMOUS_PROFILE),
        "time_filter": "server filter_period/min_time/max_time + local publish_time verification",
        "video_results_included": False,
        "batch_search_allowed": False,
    }

    fieldtheory_ready, fieldtheory_message = fieldtheory_graphql_only_status()
    channels["x_bookmarks"] = {
        "status": "ok" if fieldtheory_ready else "warn",
        "name": "X 书签本地同步与检索",
        "message": fieldtheory_message,
        "tier": 1,
        "backends": ["Field Theory Chrome session -> X internal GraphQL"],
        "active_backend": "Field Theory GraphQL-only" if fieldtheory_ready else None,
    }

    prerequisites = {
        "wrapper": XIAOYUZHOU.exists(),
        "step_asr": STEP_ASR.exists(),
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "stepfun_key": stepfun_key_available(),
    }
    ready = all(prerequisites.values())
    opencli_ready = xiaoyuzhou_opencli_available()
    opencli_credentials_present = XIAOYUZHOU_OPENCLI_CREDENTIALS.is_file()
    missing = [name for name, ok in prerequisites.items() if not ok]
    channels["xiaoyuzhou"] = {
        "status": "ok" if ready else "warn",
        "name": "小宇宙播客下载、列表与转文字",
        "message": (
            "匿名下载/StepFun 路线就绪；OpenCLI 命令、包装层和本地凭证均就绪，实际调用仍需当轮授权"
            if ready and opencli_ready and opencli_credentials_present
            else "匿名下载/StepFun 路线就绪；OpenCLI 命令与包装层可用，但本地小宇宙凭证缺失，使用前需提醒配置"
            if ready and opencli_ready
            else "自用 StepFun 路线配置就绪；OpenCLI 补充层不可用"
            if ready
            else "StepFun 路线缺少：" + ", ".join(missing)
        ),
        "tier": 1,
        "backends": [
            "anonymous episode page/audio",
            "StepFun stepaudio-2.5-asr",
            "OpenCLI Xiaoyuzhou account token (explicit authorization required)",
        ],
        "active_backend": "anonymous page/audio + StepFun" if ready else None,
        "opencli_available": opencli_ready,
        "opencli_login_required": True,
        "opencli_credentials_present": opencli_credentials_present,
    }

    wechat_ready, wechat_message, wechat_login_ready = wechat_mp_local_status()
    sogou_search_ready = opencli_search_available("weixin", ("query", "--page", "--limit"))
    wechat_backends = ["localhost wechat-article-exporter"]
    if sogou_search_ready:
        wechat_backends.insert(0, "Sogou Weixin public search via OpenCLI")
    channels["wechat_mp"] = {
        "status": "ok" if wechat_ready and sogou_search_ready else "warn",
        "name": "微信公众号公开搜索与文章",
        "message": (
            f"{wechat_message}；搜狗跨公众号关键词搜索可用"
            if sogou_search_ready
            else f"{wechat_message}；搜狗跨公众号关键词搜索适配器不可用"
        ),
        "tier": 1,
        "backends": wechat_backends,
        "active_backend": (
            "Sogou Weixin public search + 127.0.0.1:18901"
            if wechat_ready and sogou_search_ready
            else "127.0.0.1:18901"
            if wechat_ready
            else "Sogou Weixin public search"
            if sogou_search_ready
            else None
        ),
        "global_search_ready": sogou_search_ready,
        "login_ready": wechat_login_ready,
    }
    print(json.dumps(channels, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
