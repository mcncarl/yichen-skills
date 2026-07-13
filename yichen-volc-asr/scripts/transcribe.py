#!/usr/bin/env python3
"""
火山引擎录音文件识别 - 自动化脚本
用法: python transcribe.py <本地文件路径> [--dry-run] [--no-cache] [--no-execute] [--request-id <id>]

需要设置环境变量:
export TOS_ACCESS_KEY=你的AccessKeyId
export TOS_SECRET_KEY=你的SecretAccessKey
export TOS_BUCKET=你的TOSBucket
export VOLC_ASR_TRIAL_APP_ID=你的试用或时长包AppID
export VOLC_ASR_TRIAL_TOKEN=你的试用或时长包AccessToken
"""

import os
import sys
import requests
import uuid
import time
import re
import json
import argparse
import subprocess
from difflib import SequenceMatcher

# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────

TRIAL_APP_ID = os.getenv("VOLC_ASR_TRIAL_APP_ID", "")
PAID_APP_ID = os.getenv("VOLC_ASR_PAID_APP_ID", "")


def resolve_app_id():
    """Use trial quota first; only switch to paid after trial is marked exhausted."""
    explicit_app_id = os.getenv("VOLC_ASR_APP_ID")
    if explicit_app_id:
        return explicit_app_id

    if os.getenv("VOLC_ASR_TRIAL_EXHAUSTED") == "1":
        return PAID_APP_ID

    return TRIAL_APP_ID


def resolve_access_token(app_id):
    """Keep trial and paid ASR credentials separate so a stale paid token cannot mask the trial path."""
    if app_id == TRIAL_APP_ID:
        token = os.getenv("VOLC_ASR_TRIAL_TOKEN", "")
        if token:
            return token
        if os.getenv("VOLC_ASR_ALLOW_LEGACY_TOKEN") == "1":
            return os.getenv("VOLC_ASR_TOKEN", "")
        return ""

    if app_id == PAID_APP_ID:
        return os.getenv("VOLC_ASR_PAID_TOKEN") or os.getenv("VOLC_ASR_TOKEN", "")

    return os.getenv("VOLC_ASR_TOKEN", "")


APP_ID = resolve_app_id()
ACCESS_TOKEN = resolve_access_token(APP_ID)
TOS_BUCKET = os.getenv("TOS_BUCKET", "")
TOS_REGION = os.getenv("TOS_REGION", "cn-beijing")

# ─────────────────────────────────────────────
# 剪辑规则常量
# ─────────────────────────────────────────────

# 规则2：纯语气词（严格匹配，去标点后整段只有这些词才删）
PURE_FILLERS = {
    "嗯", "啊", "呃", "哦", "额", "哈", "唔",
    "嗯嗯", "啊啊", "呃呃", "哦哦",
    "emmm", "em", "ah",
}

# 规则5：TRIM前缀词（连续出现时保留第一个，后续删开头词）
TRIM_PREFIXES = ["然后", "所以", "其实", "就是说", "那个", "反正"]

# 静音缺口阈值（毫秒）
SILENCE_THRESHOLD_MS = 1000

# 智能margin参数
MARGIN_MAX_MS = 150       # 最长片段的最大margin
MARGIN_MIN_MS = 50        # 最短片段的最小margin
MARGIN_RATIO = 0.1        # margin = max(MARGIN_MIN, min(MARGIN_MAX, duration * ratio))

# Smoothing：最短保留片段时长（毫秒）
MIN_KEEP_DURATION_MS = 500

# 规则7：difflib自动重复检测阈值
SIMILARITY_AUTO_CUT = 0.8     # >=0.8 自动删前保后
SIMILARITY_AUTO_KEEP = 0.5    # <0.5 自动保留
# 0.5~0.8 交给LLM判断

# ─────────────────────────────────────────────
# TOS 上传
# ─────────────────────────────────────────────

def get_tos_credentials():
    """获取TOS凭证"""
    access_key = os.getenv("TOS_ACCESS_KEY")
    secret_key = os.getenv("TOS_SECRET_KEY")

    if not access_key or not secret_key or not TOS_BUCKET:
        print("错误: 请设置TOS Access Key、Secret Key和Bucket")
        print("export TOS_ACCESS_KEY=你的AccessKeyId")
        print("export TOS_SECRET_KEY=你的SecretAccessKey")
        print("export TOS_BUCKET=你的TOSBucket")
        return None, None

    return access_key, secret_key


def upload_to_tos(file_path, access_key, secret_key):
    """上传文件到TOS"""
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    print(f"正在上传: {filename} ({file_size} bytes)")

    url = f"https://{TOS_BUCKET}.tos-{TOS_REGION}.volces.com/{filename}"

    with open(file_path, 'rb') as f:
        file_data = f.read()

    headers = {
        'Content-Type': 'application/octet-stream',
        'Content-Length': str(file_size),
    }

    try:
        resp = requests.put(url, data=file_data, headers=headers)
        print(f"上传响应: {resp.status_code}")

        if resp.status_code in [200, 201]:
            print("上传成功!")
            set_public_access(filename, access_key, secret_key)
            return f"https://{TOS_BUCKET}.tos-{TOS_REGION}.volces.com/{filename}"
        else:
            print(f"上传失败: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"上传出错: {e}")
        return None


def set_public_access(filename, access_key, secret_key):
    """设置文件为公开访问"""
    print("设置公开访问权限...")

    url = f"https://{TOS_BUCKET}.tos-{TOS_REGION}.volces.com/{filename}?acl"

    acl_xml = '''<?xml version="1.0" encoding="UTF-8"?>
<AccessControlPolicy>
    <Owner>
        <ID>owner123</ID>
    </Owner>
    <AccessControlList>
        <Grant>
            <Grantee xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="Group">
                <URI>http://acs.amazonaws.com/groups/global/AllUsers</URI>
            </Grantee>
            <Permission>READ</Permission>
        </Grant>
    </AccessControlList>
</AccessControlPolicy>'''

    headers = {
        'Content-Type': 'application/xml',
        'Content-Length': str(len(acl_xml)),
    }

    try:
        resp = requests.put(url, data=acl_xml, headers=headers)
        if resp.status_code in [200, 201, 204]:
            print("公开访问权限设置成功!")
        else:
            print(f"设置公开访问失败: {resp.status_code} (可能bucket已公开)")
    except Exception as e:
        print(f"设置公开访问出错: {e}")


# ─────────────────────────────────────────────
# ASR 识别
# ─────────────────────────────────────────────

def submit_asr(audio_url, file_path=None):
    """提交ASR任务"""
    ensure_trial_or_paid_after_exhausted()
    request_id = str(uuid.uuid4())

    url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"

    headers = {
        "X-Api-Access-Key": ACCESS_TOKEN,
        "X-Api-App-Key": APP_ID,
        "X-Api-Resource-Id": "volc.seedasr.auc",
        "X-Api-Request-Id": request_id,
        "X-Api-Sequence": "-1",
        "Content-Type": "application/json"
    }

    data = {
        "audio": {
            "url": audio_url,
            "format": "mp3",
            "rate": 16000
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True
        }
    }

    print(f"提交识别任务: {request_id}")

    resp = requests.post(url, headers=headers, json=data)
    result = resp.json()

    if resp.status_code == 200 and (result == {} or result.get("header", {}).get("code") == 20000000):
        print("任务提交成功！")
        if file_path:
            save_pending_request(file_path, request_id, audio_url)
        return request_id
    else:
        print(f"提交失败: {result}")
        return None


def query_asr(request_id):
    """查询ASR结果"""
    url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

    headers = {
        "X-Api-Access-Key": ACCESS_TOKEN,
        "X-Api-App-Key": APP_ID,
        "X-Api-Resource-Id": "volc.seedasr.auc",
        "X-Api-Request-Id": request_id,
        "Content-Type": "application/json"
    }

    data = {"request_id": request_id}

    max_attempts = int(os.getenv("VOLC_ASR_QUERY_ATTEMPTS", "360"))
    interval_seconds = int(os.getenv("VOLC_ASR_QUERY_INTERVAL_SECONDS", "5"))

    print("等待处理...")

    for i in range(max_attempts):
        time.sleep(interval_seconds)
        resp = requests.post(url, headers=headers, json=data)

        try:
            result = resp.json()
        except Exception:
            result = {}

        if result.get("result", {}).get("text"):
            return result

        additions = result.get("result", {}).get("additions", {})
        status = additions.get("status", "processing")
        print(f"  状态: {status} ({i+1}/{max_attempts})")

        if status == "success":
            return result

    return result


def transcribe(audio_url, file_path=None, request_id=None):
    """转写音频"""
    if request_id:
        ensure_trial_or_paid_after_exhausted()
        print(f"恢复查询已提交任务: {request_id}")
        return query_asr(request_id)

    request_id = submit_asr(audio_url, file_path=file_path)
    if not request_id:
        return None

    result = query_asr(request_id)
    return result


def ensure_trial_or_paid_after_exhausted():
    """Avoid paid Volcengine ASR before the trial/time package is exhausted."""
    if not APP_ID:
        if os.getenv("VOLC_ASR_TRIAL_EXHAUSTED") == "1":
            print("错误: 已标记试用/时长包用完，但未设置 VOLC_ASR_PAID_APP_ID。")
        else:
            print("错误: 未设置 VOLC_ASR_TRIAL_APP_ID。公开版本不内置任何 AppID。")
        sys.exit(1)

    if APP_ID == TRIAL_APP_ID:
        if not ACCESS_TOKEN:
            print(f"错误: 当前默认使用试用/时长包应用 {TRIAL_APP_ID}，但未设置 VOLC_ASR_TRIAL_TOKEN。")
            print("为避免误用付费 token，本次已停止。")
            print("请从火山控制台复制试用应用的 Access Token 后设置 VOLC_ASR_TRIAL_TOKEN。")
            print("只有确认 VOLC_ASR_TOKEN 本身就是试用 token 时，才可临时设置 VOLC_ASR_ALLOW_LEGACY_TOKEN=1 兼容旧配置。")
            sys.exit(1)
        print(f"使用试用/时长包 ASR 应用: {APP_ID}")
        return

    if APP_ID == PAID_APP_ID and os.getenv("VOLC_ASR_TRIAL_EXHAUSTED") == "1":
        print(f"试用/时长包已标记用完，使用付费 ASR 应用: {APP_ID}")
        return

    if os.getenv("VOLC_ASR_ALLOW_NON_TRIAL_APP") == "1":
        print(f"警告: 当前 VOLC_ASR_APP_ID={APP_ID}，不是试用包应用 {TRIAL_APP_ID}，将按该应用配置继续调用。")
        return

    print("错误: 当前火山 ASR AppID 不是试用包所在应用。")
    print(f"当前 AppID: {APP_ID}")
    print(f"试用包 AppID: {TRIAL_APP_ID}")
    print(f"付费 AppID: {PAID_APP_ID}")
    print("为避免误扣余额，本次已停止。")
    print("规则: 先用完试用/时长包；确认用完后设置 VOLC_ASR_TRIAL_EXHAUSTED=1 才会走付费应用。")
    print("如果确实要临时使用其他应用，需显式设置 VOLC_ASR_ALLOW_NON_TRIAL_APP=1。")
    sys.exit(1)


# ─────────────────────────────────────────────
# 格式化工具
# ─────────────────────────────────────────────

def format_timestamp(ms):
    """将毫秒转换为 分:秒 格式"""
    seconds = ms // 1000
    minutes = seconds // 60
    seconds = seconds % 60
    return f"{minutes}:{seconds:02d}"


def format_timestamp_ffmpeg(ms):
    """将毫秒转换为 ffmpeg 格式 HH:MM:SS.ms"""
    seconds = ms / 1000.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"
    else:
        return f"{minutes:02d}:{secs:05.2f}"


def format_srt_timestamp(ms):
    """将毫秒转换为 SRT 格式 HH:MM:SS,mmm"""
    seconds = ms / 1000.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


# ─────────────────────────────────────────────
# 剪辑规则实现
# ─────────────────────────────────────────────

# 规则1：静音缺口检测

def find_silence_gaps(utterances):
    """
    检测相邻片段之间 ≥1秒的静音缺口。
    返回：[{"after_index": i, "gap_ms": ..., "from_ms": ..., "to_ms": ...}, ...]
    """
    gaps = []
    for i in range(len(utterances) - 1):
        end_ms = utterances[i].get("end_time", 0)
        start_ms = utterances[i + 1].get("start_time", 0)
        gap_ms = start_ms - end_ms
        if gap_ms >= SILENCE_THRESHOLD_MS:
            gaps.append({
                "after_index": i,
                "gap_ms": gap_ms,
                "from_ms": end_ms,
                "to_ms": start_ms,
            })
    return gaps


# 规则2+4：纯语气词片段检测

def is_pure_filler_segment(text):
    """
    规则2：整段去标点后是否仅为纯语气词。
    规则4：如果语气词在句子中间（text还有其他实质内容），返回False保留整段。
    """
    cleaned = re.sub(r'[。，！？、,.!?…\s]', '', text)
    return cleaned in PURE_FILLERS


def find_filler_segments(utterances):
    """
    找出纯语气词片段，并合并相邻语气词为单个CUT。
    返回：[{"start_index": i, "end_index": j, "start": ms, "end": ms, "texts": [...], "reason": "纯语气词"}, ...]
    """
    raw_indices = []
    for i, utt in enumerate(utterances):
        text = utt.get("text", "").strip()
        if not text:
            continue
        if is_pure_filler_segment(text):
            raw_indices.append(i)

    if not raw_indices:
        return []

    # 合并相邻语气词片段
    merged = []
    group_start = raw_indices[0]
    group_end = raw_indices[0]

    for idx in raw_indices[1:]:
        if idx == group_end + 1:
            group_end = idx
        else:
            merged.append((group_start, group_end))
            group_start = idx
            group_end = idx
    merged.append((group_start, group_end))

    results = []
    for start_i, end_i in merged:
        start_ms = utterances[start_i].get("start_time", 0)
        end_ms = utterances[end_i].get("end_time", 0)
        texts = [utterances[i].get("text", "").strip() for i in range(start_i, end_i + 1)]
        results.append({
            "start_index": start_i,
            "end_index": end_i,
            "indices": set(range(start_i, end_i + 1)),
            "start": start_ms,
            "end": end_ms,
            "texts": texts,
            "reason": "纯语气词" + ("(合并)" if start_i != end_i else ""),
        })

    return results


# 规则3：相邻重复片段（difflib自动判断 + LLM兜底）

def compute_similarity(text1, text2):
    """计算两段文本的相似度"""
    # 去标点后比较
    clean = lambda t: re.sub(r'[。，！？、,.!?…\s]', '', t)
    return SequenceMatcher(None, clean(text1), clean(text2)).ratio()


def analyze_adjacent_pairs(utterances, filler_indices):
    """
    规则3：分析相邻片段对的相似度。
    - >=0.8：自动删前保后
    - <0.5：自动保留
    - 0.5~0.8：交给LLM判断
    返回：(auto_cuts, llm_candidates)
      auto_cuts: [{"index": i, "reason": "重复(相似度XX%)", "kept_index": j}, ...]
      llm_candidates: [{"i": i, "j": j, "similarity": float, "earlier": utt, "later": utt}, ...]
    """
    auto_cuts = []
    llm_candidates = []
    i = 0

    while i < len(utterances) - 1:
        if i in filler_indices:
            i += 1
            continue
        j = i + 1
        while j < len(utterances) and j in filler_indices:
            j += 1
        if j >= len(utterances):
            break

        t1 = utterances[i].get("text", "").strip()
        t2 = utterances[j].get("text", "").strip()

        if t1 and t2:
            sim = compute_similarity(t1, t2)
            if sim >= SIMILARITY_AUTO_CUT:
                auto_cuts.append({
                    "index": i,
                    "kept_index": j,
                    "similarity": sim,
                    "reason": f"重复(相似度{sim:.0%})",
                })
            elif sim >= SIMILARITY_AUTO_KEEP:
                llm_candidates.append({
                    "i": i,
                    "j": j,
                    "similarity": sim,
                    "earlier": utterances[i],
                    "later": utterances[j],
                })

        i = j

    return auto_cuts, llm_candidates


# 规则5：连续TRIM前缀词处理

def find_consecutive_trim_prefixes(utterances, filler_indices):
    """
    连续多段以TRIM前缀词开头时，保留第一个的前缀词，
    后续段的开头前缀词删掉（TRIM，只删词不删整段）。
    """
    filler_set = set(filler_indices)
    trims = []
    # 每个前缀词独立追踪连续序列
    run_tracker = {}  # {prefix: run_start_index}

    for i, utt in enumerate(utterances):
        if i in filler_set:
            run_tracker = {}
            continue

        text = utt.get("text", "").strip()
        matched_prefix = None
        for prefix in TRIM_PREFIXES:
            if text.startswith(prefix):
                matched_prefix = prefix
                break

        if matched_prefix:
            if matched_prefix not in run_tracker:
                run_tracker[matched_prefix] = i  # 第一个，保留
            else:
                # 非第一个，标记TRIM
                trimmed = re.sub(r'^' + re.escape(matched_prefix) + r'\s*', '', text)
                if trimmed:  # TRIM后还有内容才标记
                    trims.append({
                        "index": i,
                        "start": utt.get("start_time", 0),
                        "end": utt.get("end_time", 0),
                        "prefix": matched_prefix,
                        "original": text,
                        "trimmed": trimmed,
                    })
        else:
            # 不以任何前缀开头，重置所有tracker
            run_tracker = {}

    return trims


# ─────────────────────────────────────────────
# Margin 计算
# ─────────────────────────────────────────────

def compute_margin(duration_ms):
    """
    智能margin：长片段给大margin，短片段给小margin。
    duration_ms: 片段时长（毫秒）
    """
    return int(max(MARGIN_MIN_MS, min(MARGIN_MAX_MS, duration_ms * MARGIN_RATIO)))


# ─────────────────────────────────────────────
# 主分析函数
# ─────────────────────────────────────────────

def analyze_and_generate_cuts(result, input_file, dry_run=False):
    """
    应用全部剪辑规则，生成剪好的视频。
    """
    utterances = result.get("result", {}).get("utterances", [])

    if not utterances:
        print("没有找到时间戳片段")
        return

    print("\n" + "=" * 60)
    print("剪辑分析")
    print("=" * 60)

    # 规则1：静音缺口
    silence_gaps = find_silence_gaps(utterances)
    silence_after = {g["after_index"] for g in silence_gaps}

    # 规则2+4：纯语气词片段（已合并相邻）
    filler_cuts = find_filler_segments(utterances)
    filler_indices = set()
    for fc in filler_cuts:
        filler_indices.update(fc["indices"])

    # 规则3：相邻重复（difflib自动 + LLM候选）
    auto_repeat_cuts, llm_candidates = analyze_adjacent_pairs(utterances, filler_indices)
    repeat_cut_indices = {c["index"] for c in auto_repeat_cuts}

    # 规则5：连续TRIM前缀词
    trim_results = find_consecutive_trim_prefixes(utterances, filler_indices)
    trim_indices = {t["index"] for t in trim_results}

    # 合并所有要删除的索引
    all_cut_indices = filler_indices | repeat_cut_indices

    # ── 输出逐段标注 ──
    print("\n【逐段标注】")

    for i, utt in enumerate(utterances):
        start = format_timestamp(utt.get("start_time", 0))
        end = format_timestamp(utt.get("end_time", 0))
        text = utt.get("text", "").strip()

        if i in filler_indices:
            fc = next((f for f in filler_cuts if i in f["indices"]), None)
            label = "纯语气词" + ("(合并)" if fc and len(fc["indices"]) > 1 else "")
            print(f"❌ CUT     [{start} - {end}]  \"{text}\"  → {label}")
        elif i in repeat_cut_indices:
            rc = next(c for c in auto_repeat_cuts if c["index"] == i)
            print(f"❌ CUT     [{start} - {end}]  \"{text}\"  → {rc['reason']}")
        elif i in trim_indices:
            t = next(x for x in trim_results if x["index"] == i)
            print(f"✂️  TRIM    [{start} - {end}]  删除开头\"{t['prefix']}\" → \"{t['trimmed']}\"")
        else:
            print(f"✅ KEEP    [{start} - {end}]  \"{text}\"")

        if i in silence_after:
            gap = next(g for g in silence_gaps if g["after_index"] == i)
            gap_sec = gap["gap_ms"] / 1000
            ts_from = format_timestamp(gap["from_ms"])
            ts_to = format_timestamp(gap["to_ms"])
            print(f"🔇 SILENCE [{ts_from} → {ts_to}]  ({gap_sec:.1f}秒静音)")

    # ── 待LLM确认的模糊对 ──
    if llm_candidates:
        print("\n" + "=" * 60)
        print("【待LLM确认：模糊重复对（相似度50%~80%）】")
        print("=" * 60)
        for idx, pair in enumerate(llm_candidates, 1):
            earlier = pair["earlier"]
            later = pair["later"]
            t1 = format_timestamp(earlier.get("start_time", 0))
            t2 = format_timestamp(earlier.get("end_time", 0))
            t3 = format_timestamp(later.get("start_time", 0))
            t4 = format_timestamp(later.get("end_time", 0))
            print(f"\n对{idx}: (相似度 {pair['similarity']:.0%})")
            print(f"  前: [{t1} - {t2}] \"{earlier.get('text', '').strip()}\"")
            print(f"  后: [{t3} - {t4}] \"{later.get('text', '').strip()}\"")
            print(f"  → 请判断相似度是否≥80%？若是，删前保后。")

    # ── 统计 ──
    original_duration = utterances[-1].get("end_time", 0) - utterances[0].get("start_time", 0)
    cut_duration = sum(
        utterances[i].get("end_time", 0) - utterances[i].get("start_time", 0)
        for i in all_cut_indices
    )
    silence_duration = sum(g["gap_ms"] for g in silence_gaps)
    estimated_cut_duration = original_duration - cut_duration - silence_duration

    print("\n" + "=" * 60)
    print("【统计】")
    print(f"  总片段数:       {len(utterances)}")
    print(f"  原始时长:       {original_duration/1000:.1f}秒")
    print(f"  静音缺口(≥1s):  {len(silence_gaps)} 处 ({silence_duration/1000:.1f}秒)")
    print(f"  语气词删除:     {len(filler_cuts)} 段 ({cut_duration/1000:.1f}秒)")
    print(f"  重复自动删除:   {len(auto_repeat_cuts)} 段")
    print(f"  TRIM片段:       {len(trim_results)} 段")
    print(f"  待LLM确认:      {len(llm_candidates)} 对")
    print(f"  预估剪后时长:   {estimated_cut_duration/1000:.1f}秒")
    print(f"  预估缩减:       {(1 - estimated_cut_duration/original_duration)*100:.1f}%" if original_duration > 0 else "")
    print("=" * 60)

    # ── 构建保留片段列表（含smoothing） ──
    segments_to_keep = []
    for i, utt in enumerate(utterances):
        if i not in all_cut_indices:
            segments_to_keep.append(utt)

    # Smoothing：合并过短的保留片段到相邻片段
    segments_to_keep = apply_smoothing(segments_to_keep, utterances, all_cut_indices, silence_gaps)

    # ── 生成ffmpeg剪辑 ──
    base_name = os.path.splitext(input_file)[0]
    output_file = base_name + "_cut.mp4"

    generate_and_execute_ffmpeg(
        segments_to_keep, silence_gaps, input_file, output_file, dry_run
    )

    # ── 生成SRT字幕 ──
    srt_file = base_name + "_cut.srt"
    generate_srt(segments_to_keep, srt_file)

    return output_file, srt_file


# ─────────────────────────────────────────────
# Smoothing
# ─────────────────────────────────────────────

def apply_smoothing(segments, all_utterances, cut_indices, silence_gaps):
    """
    过短的保留片段（<0.5s）合并到相邻片段，避免闪帧。
    """
    if not segments:
        return segments

    smoothed = []
    i = 0
    while i < len(segments):
        seg = segments[i]
        duration = seg.get("end_time", 0) - seg.get("start_time", 0)

        if duration < MIN_KEEP_DURATION_MS and len(smoothed) > 0:
            # 太短，合并到前一个保留片段
            prev = smoothed[-1]
            prev["end_time"] = seg.get("end_time", 0)
            if not prev.get("merged_texts"):
                prev["merged_texts"] = [prev.get("text", "")]
            prev["merged_texts"].append(seg.get("text", ""))
            prev["text"] = prev.get("text", "") + seg.get("text", "")
        else:
            smoothed.append(dict(seg))  # 浅拷贝避免修改原始数据

        i += 1

    return smoothed


# ─────────────────────────────────────────────
# FFmpeg 执行
# ─────────────────────────────────────────────

def generate_and_execute_ffmpeg(segments_to_keep, silence_gaps, input_file, output_file, dry_run=False):
    """生成并执行ffmpeg命令，剪切视频"""
    if not segments_to_keep:
        print("没有需要保留的片段")
        return

    print("\n" + "=" * 60)
    print(f"{'[DRY-RUN] ' if dry_run else ''}FFmpeg 剪辑")
    print("=" * 60)
    print(f"输入: {input_file}")
    print(f"输出: {output_file}")

    # 构建保留片段列表（带margin，跳过静音缺口）
    keep_ranges = []
    for seg in segments_to_keep:
        start_ms = seg.get("start_time", 0)
        end_ms = seg.get("end_time", 0)
        duration_ms = end_ms - start_ms

        # 智能margin
        margin = compute_margin(duration_ms)
        margin_start = max(0, start_ms - margin)
        margin_end = end_ms + margin

        # 不超过下一个保留片段的起点
        keep_ranges.append((margin_start, margin_end))

    # 去重合并重叠区间
    keep_ranges.sort()
    merged_ranges = [keep_ranges[0]]
    for start, end in keep_ranges[1:]:
        if start <= merged_ranges[-1][1]:
            merged_ranges[-1] = (merged_ranges[-1][0], max(merged_ranges[-1][1], end))
        else:
            merged_ranges.append((start, end))

    # 生成filter_complex
    filter_parts = []
    for i, (start, end) in enumerate(merged_ranges):
        start_fmt = format_timestamp_ffmpeg(start)
        end_fmt = format_timestamp_ffmpeg(end)
        # ffmpeg trim filter需要秒数,不是时间码
        start_sec = start / 1000.0
        end_sec = end / 1000.0
        text = segments_to_keep[min(i, len(segments_to_keep)-1)].get("text", "")[:30] if i < len(segments_to_keep) else ""
        print(f"  片段{i+1}: [{start_fmt} - {end_fmt}] {text}...")

        filter_parts.append(
            f"[0:v]trim=start={start_sec:.2f}:end={end_sec:.2f},setpts=PTS-STARTPTS[v{i}];"
        )
        filter_parts.append(
            f"[0:a]atrim=start={start_sec:.2f}:end={end_sec:.2f},asetpts=PTS-STARTPTS[a{i}];"
        )

    # concat
    inputs_str = "".join(f"[v{i}][a{i}]" for i in range(len(merged_ranges)))
    filter_parts.append(f"{inputs_str}concat=n={len(merged_ranges)}:v=1:a=1[outv][outa]")

    filter_complex = " ".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        "-i", input_file,
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-preset", "fast",
        "-c:a", "aac",
        output_file
    ]

    if dry_run:
        print(f"\n[DRY-RUN] 命令:")
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
    else:
        print(f"\n正在执行ffmpeg剪辑...")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                print(f"✅ 剪辑完成: {output_file}")
                file_size = os.path.getsize(output_file)
                print(f"   文件大小: {file_size / 1024 / 1024:.1f} MB")
            else:
                print(f"❌ ffmpeg执行失败 (退出码 {result.returncode})")
                if result.stderr:
                    # 只打印最后几行错误
                    err_lines = result.stderr.strip().split('\n')
                    for line in err_lines[-5:]:
                        print(f"   {line}")
        except subprocess.TimeoutExpired:
            print("❌ ffmpeg超时（超过5分钟）")
        except FileNotFoundError:
            print("❌ ffmpeg未安装。请运行: brew install ffmpeg")


# ─────────────────────────────────────────────
# SRT 生成
# ─────────────────────────────────────────────

def generate_srt(segments_to_keep, srt_file):
    """生成SRT字幕文件，供剪映导入"""
    print("\n" + "=" * 60)
    print("生成SRT字幕")
    print("=" * 60)

    lines = []
    for idx, seg in enumerate(segments_to_keep, 1):
        start_ms = seg.get("start_time", 0)
        end_ms = seg.get("end_time", 0)
        text = seg.get("text", "").strip()

        if not text:
            continue

        start_srt = format_srt_timestamp(start_ms)
        end_srt = format_srt_timestamp(end_ms)

        lines.append(str(idx))
        lines.append(f"{start_srt} --> {end_srt}")
        lines.append(text)
        lines.append("")

    if lines:
        with open(srt_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print(f"✅ SRT已生成: {srt_file} ({len(lines)//4} 条字幕)")
    else:
        print("没有字幕内容可生成")


# ─────────────────────────────────────────────
# 缓存
# ─────────────────────────────────────────────

def get_cache_path(file_path):
    """获取ASR缓存文件路径"""
    return file_path + ".asr_cache.json"


def get_pending_path(file_path):
    """获取ASR未完成任务记录路径"""
    return file_path + ".asr_pending.json"


def result_has_text(result):
    """判断ASR结果是否已包含可用转写文本"""
    return bool(result and result.get("result", {}).get("text"))


def load_cache(file_path):
    """加载ASR缓存"""
    cache_file = get_cache_path(file_path)
    if os.path.exists(cache_file):
        cache_mtime = os.path.getmtime(cache_file)
        file_mtime = os.path.getmtime(file_path)
        if cache_mtime > file_mtime:
            print(f"发现ASR缓存: {cache_file}")
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    return None


def load_pending_request(file_path):
    """加载未完成ASR任务记录，避免重复提交同一音频"""
    pending_file = get_pending_path(file_path)
    if not os.path.exists(pending_file):
        return None

    try:
        with open(pending_file, 'r', encoding='utf-8') as f:
            pending = json.load(f)
    except Exception as e:
        print(f"读取未完成任务记录失败: {e}")
        return None

    request_id = pending.get("request_id")
    app_id = pending.get("app_id")
    status = pending.get("status")

    if not request_id or status == "completed":
        return None

    if app_id and app_id != APP_ID:
        print(f"发现未完成任务记录，但 AppID 不一致: {app_id} != {APP_ID}")
        print("如需恢复，请设置提交任务时使用的 VOLC_ASR_APP_ID 后重试。")
        return None

    print(f"发现未完成ASR任务记录: {pending_file}")
    return pending


def save_pending_request(file_path, request_id, audio_url):
    """保存未完成ASR任务记录；不包含token/密钥"""
    pending_file = get_pending_path(file_path)
    pending = {
        "request_id": request_id,
        "app_id": APP_ID,
        "audio_url": audio_url,
        "status": "submitted",
        "submitted_at": int(time.time()),
    }
    with open(pending_file, 'w', encoding='utf-8') as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)
    print(f"已保存未完成任务记录: {pending_file}")


def mark_pending_completed(file_path):
    """将未完成ASR任务记录标记为已完成，不删除文件。"""
    pending_file = get_pending_path(file_path)
    if not os.path.exists(pending_file):
        return

    try:
        with open(pending_file, 'r', encoding='utf-8') as f:
            pending = json.load(f)
    except Exception:
        pending = {}

    pending["status"] = "completed"
    pending["completed_at"] = int(time.time())
    with open(pending_file, 'w', encoding='utf-8') as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)
    print(f"未完成任务记录已标记完成: {pending_file}")


def save_cache(file_path, result):
    """保存ASR缓存"""
    cache_file = get_cache_path(file_path)
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"ASR结果已缓存: {cache_file}")


# ─────────────────────────────────────────────
# 输出格式化
# ─────────────────────────────────────────────

def format_output(result):
    """格式化输出，带时间戳"""
    text_parts = []
    timestamp_parts = []

    if result and result.get("result", {}).get("text"):
        full_text = result["result"]["text"]
        text_parts.append("【完整文字】")
        text_parts.append(full_text)

        utterances = result.get("result", {}).get("utterances", [])
        if utterances:
            timestamp_parts.append("\n【分段时间戳】")
            for utt in utterances:
                start = format_timestamp(utt.get("start_time", 0))
                end = format_timestamp(utt.get("end_time", 0))
                text = utt.get("text", "")
                timestamp_parts.append(f"[{start} - {end}] {text}")

    return "\n".join(text_parts) + ("\n".join(timestamp_parts) if timestamp_parts else "")


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='火山引擎录音文件识别 + 自动剪辑')
    parser.add_argument('file', help='本地音视频文件路径')
    parser.add_argument('--dry-run', action='store_true', help='只打印ffmpeg命令，不执行')
    parser.add_argument('--no-cache', action='store_true', help='忽略缓存，重新调ASR')
    parser.add_argument('--no-execute', action='store_true', help='不执行ffmpeg剪辑（仍生成SRT和标注）')
    parser.add_argument('--transcribe-only', action='store_true', help='只保存ASR转写结果，不做剪辑分析或生成SRT')
    parser.add_argument('--request-id', help='只恢复查询已提交的火山ASR任务，不重新上传/提交')
    parser.add_argument('--force-new', action='store_true', help='即使有未完成任务记录，也强制重新上传并提交新任务')
    args = parser.parse_args()

    file_path = args.file

    if not os.path.exists(file_path):
        print(f"错误: 文件不存在: {file_path}")
        sys.exit(1)

    # 尝试加载缓存
    result = None
    if not args.no_cache:
        result = load_cache(file_path)

    if not result:
        pending = None
        if not args.request_id and not args.force_new:
            pending = load_pending_request(file_path)

        if args.request_id or pending:
            request_id = args.request_id or pending["request_id"]
            result = transcribe(None, file_path=file_path, request_id=request_id)
        else:
            access_key, secret_key = get_tos_credentials()
            if not access_key or not secret_key:
                sys.exit(1)

            audio_url = upload_to_tos(file_path, access_key, secret_key)
            if not audio_url:
                print("上传失败，退出")
                sys.exit(1)

            print("\n开始识别...")
            result = transcribe(audio_url, file_path=file_path)

        if result_has_text(result):
            save_cache(file_path, result)
            mark_pending_completed(file_path)

    if result_has_text(result):
        output = format_output(result)
        print("\n" + "=" * 60)
        print("识别结果:")
        print("=" * 60)
        print(output)

        output_file = file_path + ".txt"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"\n结果已保存到: {output_file}")

        # 剪辑分析 + 生成视频
        if args.transcribe_only:
            print("仅转写模式：跳过剪辑分析和SRT生成。")
        else:
            dry_run = args.dry_run or args.no_execute
            analyze_and_generate_cuts(result, file_path, dry_run)
    else:
        print("\n识别失败")


if __name__ == "__main__":
    main()
