"""Render WeChat message envelopes without exposing their transport metadata.

Pure transformations only: no configuration, database, filesystem or network I/O.
Raw database values remain available to internal identity matching; presentation
code must use these helpers instead of falling back to a raw XML payload.
"""

from __future__ import annotations

import html
import re
from xml.etree import ElementTree as ET


HIDDEN = "[已隐藏]"
HIDDEN_ID = "[内部标识已隐藏]"
MAX_XML_CHARS = 1_000_000
MAX_FORWARD_DEPTH = 8
MAX_FORWARD_ITEMS = 50
# Base types rendered as a fixed label ([图片], [语音] ...); their bodies carry no readable text.
PLACEHOLDER_TYPES = frozenset({3, 34, 42, 43, 47, 48, 50})
IDENTIFIER_FIELDS = {
    "username", "sender_username", "chat_username", "owner_username",
    "account_username", "last_msg_sender", "wxid", "alias",
}
SECRET_NAMES = (
    r"(?:newformat)?aeskey|(?:newformat)?fileid|cdn(?:attach|thumb|video|midimg|bigimg|smallimg)?url|"
    r"(?:encrypt|decrypt|encryption|decryption|auth|access|api)[_-]?key|"
    r"(?:(?:access|refresh)[_-]?)?token|password|secret|salt"
)
SECRET_FIELD = re.compile(r"^(?:" + SECRET_NAMES + r"|key)$", re.I)
SECRET_VALUE = re.compile(
    r"(?i)(?<![\w-])(?P<label>(?:" + SECRET_NAMES + r"|key)[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;<>\"'&]+)"
)
INTERNAL_ID = re.compile(r"(?i)(?<![\w])wxid_[A-Za-z0-9_-]+")
ROOM_ID = re.compile(r"(?i)(?<![\w/\\.-])[A-Za-z0-9_.-]+@(?:chatroom|openim)\b")
ENVELOPE = re.compile(
    r"<\s*(?:[\w.-]+:)?(?:sysmsg|msg|appmsg|revokemsg|recordinfo|recorditem|voicemsg|videomsg|img|emoji)\b",
    re.I,
)
MARKUP = re.compile(r"<\s*(?:[!?/]|[A-Za-z_][\w:.-]*(?:\s|/?>))")
PREFIX = re.compile(r"\A\s*[A-Za-z0-9_.-]+(?:@(?:chatroom|openim))?:\r?\n")


def redact_text(text: str, *, include_identifiers: bool = False) -> str:
    """Redact explicit credential fields and internal IDs, not ordinary numbers."""
    text = SECRET_VALUE.sub(lambda m: m["label"] + HIDDEN, text)
    if not include_identifiers:
        text = INTERNAL_ID.sub(HIDDEN_ID, text)
        text = ROOM_ID.sub(HIDDEN_ID, text)
    return text


def public_value(value, *, include_identifiers: bool = False):
    """Copy data for display; never change the internal records used by callers."""
    if isinstance(value, dict):
        result = {}
        identifiers = {item for key, item in value.items()
                       if str(key).lower() in IDENTIFIER_FIELDS and isinstance(item, str) and item}
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized == "raw":
                continue
            if SECRET_FIELD.fullmatch(normalized):
                result[key] = HIDDEN if item else item
            elif normalized in IDENTIFIER_FIELDS and not include_identifiers:
                result[key] = HIDDEN_ID if item else item
            # Names fall back to the identifier when a contact has none (chat, sender,
            # from, owner, top-sender name ...); any such copy in the record is hidden too.
            elif not include_identifiers and isinstance(item, str) and item in identifiers:
                result[key] = HIDDEN_ID
            else:
                result[key] = public_value(item, include_identifiers=include_identifiers)
        return result
    if isinstance(value, (list, tuple)):
        return [public_value(item, include_identifiers=include_identifiers) for item in value]
    if isinstance(value, str):
        decoded = html.unescape(value)
        if ENVELOPE.search(decoded):
            return format_message_content(1, value)
        return redact_text(value, include_identifiers=include_identifiers)
    return value


def _name(node: ET.Element) -> str:
    return str(node.tag).rsplit("}", 1)[-1].lower()


def _find(node: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in node.iter() if _name(item) == name), None)


def _child(node: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in node if _name(item) == name), None)


def _leaf(node: ET.Element | None) -> str:
    # Never flatten arbitrary descendants: a title can itself contain an XML
    # credential element. Only actual text in an allowlisted field is useful.
    if node is None:
        return ""
    text = (node.text or "").strip()
    decoded = html.unescape(text)
    if MARKUP.search(decoded) or re.search(r"&(?:amp;)*(?:lt|#0*60|#x0*3c);", decoded, re.I):
        return "[内嵌内容已隐藏]"
    return redact_text(text)


def _system(root: ET.Element, fallback: str) -> str:
    replacement = _leaf(_find(root, "replacemsg"))
    if replacement:
        return replacement
    plain = _leaf(_find(root, "plain"))
    if plain:
        return plain
    template = _leaf(_find(root, "template"))
    if not template:
        return fallback
    substitutions = {}
    for link in root.iter():
        if _name(link) != "link":
            continue
        key = link.attrib.get("name", "")
        if not re.fullmatch(r"[A-Za-z0-9_]+", key):
            continue
        if link.attrib.get("hidden") == "1":
            substitutions[key] = ""
            continue
        names = [_leaf(item) for item in link.iter() if _name(item) == "nickname"]
        names = [name for name in names if name]
        title = _leaf(_find(link, "title"))
        substitutions[key] = "、".join(names) or title or "[成员]"
    return re.sub(r"\$([A-Za-z0-9_]+)\$", lambda m: substitutions.get(m[1], "[内容]"), template).strip()


def _xml_body(content: str) -> str:
    original = content.lstrip("\ufeff").strip()
    text = PREFIX.sub("", original, count=1).strip()
    # Escaped envelopes occur in forwarded messages. Decode at most twice;
    # deeper/mixed malformed envelopes fail closed rather than returning XML.
    for _ in range(2):
        if MARKUP.search(text):
            break
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    # Do not strip an ordinary heading such as 'Introduction:\n...' or decode
    # ordinary prose containing '&amp;' merely because it resembles a prefix.
    return text if MARKUP.search(text) else original


def _parse(text: str) -> ET.Element | None:
    if len(text) > MAX_XML_CHARS or re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", text, re.I):
        return None
    try:
        return ET.fromstring(text)
    except (ET.ParseError, ValueError):
        return None


def _record_info(record: ET.Element) -> ET.Element | None:
    if _name(record) == "recordinfo":
        return record
    root = _child(record, "recordinfo")
    if root is None:
        root = _parse(_xml_body(record.text or ""))
    return root if root is not None and _name(root) == "recordinfo" else None


def _record_lines(record: ET.Element, depth: int, budget: list[int]) -> list[str]:
    if depth >= MAX_FORWARD_DEPTH:
        return ["[更深层转发内容已省略]"]
    root = _record_info(record)
    if root is None:
        return ["[转发内容无法解析]"]
    datalist = _child(root, "datalist")
    if datalist is None:
        return ["[无可读转发内容]"]
    lines = []
    for item in datalist:
        if _name(item) != "dataitem":
            continue
        if budget[0] <= 0:
            lines.append("[其余转发内容已省略]")
            break
        budget[0] -= 1
        source = _leaf(_child(item, "sourcename"))
        title = _leaf(_child(item, "datatitle"))
        description = _leaf(_child(item, "datadesc"))
        text = description or title or "[非文本转发消息]"
        lines.append((source + ": " if source else "") + text)
        nested = _child(item, "recorditem")
        if nested is None:
            nested = _child(item, "recordinfo")
        if nested is not None:
            lines.extend(_record_lines(nested, depth + 1, budget))
    return lines


def _forwarded(app: ET.Element) -> str:
    """Read bounded nested forwards, extracting only allowlisted human fields."""
    record = _child(app, "recorditem")
    if record is None:
        return ""
    return "\n".join(_record_lines(record, 0, [MAX_FORWARD_ITEMS]))


# paysubtype of a transfer message: 1 the payer sends it, 3 the receiver accepts it,
# 4 it goes back to the payer (returned or expired).
TRANSFER_STATES = {"1": "发出", "3": "已收款", "4": "已退还"}


def _transfer(app: ET.Element) -> str:
    pay = _find(app, "wcpayinfo")
    if pay is None:
        return "[转账]"
    amount = _leaf(_child(pay, "feedesc")) or "金额未知"
    memo = _leaf(_child(pay, "pay_memo"))
    state = TRANSFER_STATES.get(_leaf(_child(pay, "paysubtype")), "")
    return f"[转账] {amount}" + (f"（备注：{memo}）" if memo else "") + (f" · {state}" if state else "")


def format_message_content(local_type: int | None, content: str) -> str:
    """Return readable content, or a safe placeholder for an unknown envelope."""
    try:
        value = int(local_type or 0)
    except (TypeError, ValueError):
        value = 0
    base, subtype = value & 0xFFFFFFFF, value >> 32
    labels = {3: "图片", 34: "语音", 42: "名片", 43: "视频", 47: "表情",
              48: "位置", 49: "链接/文件", 50: "通话", 10000: "系统消息", 10002: "撤回消息"}
    fallback = "[" + labels.get(base, "消息") + "]"
    if base in PLACEHOLDER_TYPES:
        if base == 34:
            length = re.search(r'voicelength=[\"\'](\d+)[\"\']', content)
            if length:
                return f"[语音，约 {int(length[1]) / 1000:.1f} 秒]"
        return fallback

    text = _xml_body(content)
    looks_xml = bool(MARKUP.search(text))
    envelope = bool(ENVELOPE.search(text))
    if not looks_xml:
        if base != 1 and re.search(r"&(?:amp;)*(?:lt|#0*60|#x0*3c);", text, re.I):
            return fallback
        return redact_text(text) or ("" if base == 1 else fallback)
    # Ordinary text such as 'a < b', Markdown autolinks and code examples are
    # not WeChat envelopes. Explicit credential fields are still redacted.
    if base == 1 and not envelope and not text.startswith("<?xml"):
        if re.search(r"<\s*(?:" + SECRET_NAMES + r"|key)\b", text, re.I):
            return "[含敏感字段的内容已隐藏]"
        return redact_text(text)
    root = _parse(text)
    if root is None:
        return fallback
    system = _find(root, "sysmsg")
    if system is not None or base in {10000, 10002}:
        return _system(system if system is not None else root, fallback)
    app = _find(root, "appmsg")
    if app is None and base != 49:
        return fallback
    app = app if app is not None else root
    title = _leaf(_child(app, "title")) or _leaf(_child(app, "des")) or _leaf(_child(app, "filename"))
    kind = _leaf(_child(app, "type"))
    if kind == "2000" or subtype == 2000:
        return _transfer(app)
    if kind == "19":
        forwarded = _forwarded(app)
        return ("[聊天记录] " + title + ("\n" + forwarded if forwarded else "")).strip()
    label = "链接/文件"
    if kind == "5":
        label = "链接"
    elif kind in {"33", "36", "44"}:
        label = "小程序"
    elif kind == "6" or subtype == 6:
        label = "文件"
    return (f"[{label}] {title}").strip()


def file_attachment_size(content: str) -> int | None:
    """Byte size a file message declares in appmsg/appattach/totallen, if any."""
    root = _parse(_xml_body(content))
    app = _find(root, "appmsg") if root is not None else None
    attach = _child(app, "appattach") if app is not None else None
    total = _child(attach, "totallen") if attach is not None else None
    value = (total.text or "").strip() if total is not None else ""
    return int(value) if re.fullmatch(r"[0-9]{1,15}", value) else None
