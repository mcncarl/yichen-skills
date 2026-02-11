#!/usr/bin/env python3
"""
推文 Markdown 处理器
1. 将 **粗体** 转为 Unicode 数学粗体字符
2. 将 *斜体* 转为 Unicode 数学斜体字符
3. 保留段落换行
4. 提取媒体文件路径
"""
import sys
import re
import json

# Unicode 字符映射表
BOLD_MAP = {
    'a': '𝗮', 'b': '𝗯', 'c': '𝗰', 'd': '𝗱', 'e': '𝗲', 'f': '𝗳', 'g': '𝗴', 'h': '𝗵',
    'i': '𝗶', 'j': '𝗷', 'k': '𝗸', 'l': '𝗹', 'm': '𝗺', 'n': '𝗻', 'o': '𝗼', 'p': '𝗽',
    'q': '𝗾', 'r': '𝗿', 's': '𝘀', 't': '𝘁', 'u': '𝘂', 'v': '𝘃', 'w': '𝘄', 'x': '𝘅',
    'y': '𝘆', 'z': '𝘇',
    'A': '𝗔', 'B': '𝗕', 'C': '𝗖', 'D': '𝗗', 'E': '𝗘', 'F': '𝗙', 'G': '𝗚', 'H': '𝗛',
    'I': '𝗜', 'J': '𝗝', 'K': '𝗞', 'L': '𝗟', 'M': '𝗠', 'N': '𝗡', 'O': '𝗢', 'P': '𝗣',
    'Q': '𝗤', 'R': '𝗥', 'S': '𝗦', 'T': '𝗧', 'U': '𝗨', 'V': '𝗩', 'W': '𝗪', 'X': '𝗫',
    'Y': '𝗬', 'Z': '𝗭',
    '0': '𝟬', '1': '𝟭', '2': '𝟮', '3': '𝟯', '4': '𝟰', '5': '𝟱', '6': '𝟲', '7': '𝟳',
    '8': '𝟴', '9': '𝟵'
}

ITALIC_MAP = {
    'a': '𝘢', 'b': '𝘣', 'c': '𝘤', 'd': '𝘥', 'e': '𝘦', 'f': '𝘧', 'g': '𝘨', 'h': '𝘩',
    'i': '𝘪', 'j': '𝘫', 'k': '𝘬', 'l': '𝘭', 'm': '𝘮', 'n': '𝘯', 'o': '𝘰', 'p': '𝘱',
    'q': '𝘲', 'r': '𝘳', 's': '𝘴', 't': '𝘵', 'u': '𝘶', 'v': '𝘷', 'w': '𝘸', 'x': '𝘹',
    'y': '𝘺', 'z': '𝘻',
    'A': '𝘈', 'B': '𝘉', 'C': '𝘊', 'D': '𝘋', 'E': '𝘌', 'F': '𝘍', 'G': '𝘎', 'H': '𝘏',
    'I': '𝘐', 'J': '𝘑', 'K': '𝘒', 'L': '𝘓', 'M': '𝘔', 'N': '𝘕', 'O': '𝘖', 'P': '𝘗',
    'Q': '𝘘', 'R': '𝘙', 'S': '𝘚', 'T': '𝘛', 'U': '𝘜', 'V': '𝘝', 'W': '𝘞', 'X': '𝘟',
    'Y': '𝘠', 'Z': '𝘡'
}

def convert_to_unicode_bold(text):
    """转换为 Unicode 粗体"""
    return ''.join(BOLD_MAP.get(c, c) for c in text)

def convert_to_unicode_italic(text):
    """转换为 Unicode 斜体"""
    return ''.join(ITALIC_MAP.get(c, c) for c in text)

def process_markdown(text):
    """处理 Markdown 格式并提取媒体"""

    # 1. 提取媒体文件
    media_files = []
    media_pattern = r'!\[([^\]]*)\]\(([^)]+)\)'

    for match in re.finditer(media_pattern, text):
        media_path = match.group(2)
        media_files.append(media_path)

    # 移除媒体语法（避免显示为文本）
    text = re.sub(media_pattern, '', text)

    # 2. 转换粗体 **text** → Unicode 粗体
    def replace_bold(match):
        return convert_to_unicode_bold(match.group(1))
    text = re.sub(r'\*\*(.+?)\*\*', replace_bold, text)

    # 3. 转换斜体 *text* → Unicode 斜体（避免匹配粗体）
    def replace_italic(match):
        return convert_to_unicode_italic(match.group(1))
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', replace_italic, text)

    # 4. 处理链接 [text](url) → text (url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)

    # 5. 清理多余空行（超过2个连续换行压缩为2个）
    text = re.sub(r'\n{3,}', '\n\n', text)

    # 6. 移除媒体标记留下的多余空行
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = text.strip()

    return {
        'text': text,
        'media_files': media_files
    }

if __name__ == '__main__':
    import io

    # 设置stdout为UTF-8编码（Windows兼容）
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    if len(sys.argv) > 1:
        input_text = ' '.join(sys.argv[1:])
    else:
        input_text = sys.stdin.read()

    result = process_markdown(input_text)
    print(json.dumps(result, ensure_ascii=False))
