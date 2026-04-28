#!/usr/bin/env python3
"""
Parse Markdown for X Articles publishing.

Attribution:
- Adapted with references to wshuyi/x-article-publisher-skill and JimLiu/baoyu-skills.
- See repository THIRD_PARTY_NOTICES.md for details.

Extracts:
- Title (from filename or first H1/H2)
- Cover image (first image)
- Content images with block index for precise positioning
- Dividers (---) with block index for menu insertion
- HTML content (images and dividers stripped)

Usage:
    python parse_markdown.py <markdown_file> [--output json|html] [--html-only]

Output (JSON):
{
    "title": "Article Title",
    "cover_image": "/path/to/cover.jpg",
    "content_images": [
        {"path": "/path/to/img.jpg", "block_index": 3, "after_text": "context..."},
        ...
    ],
    "dividers": [
        {"block_index": 7, "after_text": "context..."},
        ...
    ],
    "html": "<p>Content...</p><h2>Section</h2>...",
    "total_blocks": 25
}

The block_index indicates which block element (0-indexed) the image/divider should follow.
This allows precise positioning without relying on text matching.

Note: Dividers must be inserted via X Articles' Insert > Divider menu, not HTML <hr> tags.
"""

import argparse
import io
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

# Windows 控制台 UTF-8 编码修复
# 解决中文路径和内容在 Windows 命令行输出乱码的问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# Common search directories for missing images
SEARCH_DIRS = [
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home() / "Pictures",
]


def find_image_in_assets(md_dir: Path, img_filename: str) -> str | None:
    """Search for image in assets directory structure.

    Handles Obsidian-style assets where images are in:
    - assets/<article_name>/<image_file>
    - assets/<image_file>

    Args:
        md_dir: Directory containing the markdown file
        img_filename: Image filename to search for

    Returns:
        Full path to image if found, None otherwise
    """
    # Decode URL-encoded filename
    img_filename = urllib.parse.unquote(img_filename)

    # Search in assets subdirectories
    assets_dir = md_dir / "assets"
    if assets_dir.exists():
        for subdir in assets_dir.iterdir():
            if subdir.is_dir():
                candidate = subdir / img_filename
                if candidate.exists():
                    return str(candidate)
            elif subdir.name == img_filename:
                return str(subdir)

    # Search directly in md_dir
    candidate = md_dir / img_filename
    if candidate.exists():
        return str(candidate)

    return None


def find_image_file(original_path: str, filename: str, md_dir: Path) -> tuple[str, bool]:
    """Find an image file, searching common directories if not found at original path.

    Args:
        original_path: The resolved absolute path from markdown
        filename: Just the filename to search for
        md_dir: Directory containing the markdown file

    Returns:
        (found_path, exists): The path to use and whether file exists
    """
    # Decode URL-encoded paths (handle double encoding)
    decoded_path = urllib.parse.unquote(urllib.parse.unquote(original_path))
    decoded_filename = urllib.parse.unquote(urllib.parse.unquote(filename))

    # Normalize spaces: replace %20 with actual space
    decoded_path = decoded_path.replace('%20', ' ')
    decoded_filename = decoded_filename.replace('%20', ' ')

    # 1. Check original path (decoded)
    if os.path.isfile(decoded_path):
        return decoded_path, True

    # 2. Search in assets directory
    found_in_assets = find_image_in_assets(md_dir, decoded_filename)
    if found_in_assets:
        print(f"[parse_markdown] Found image in assets: {found_in_assets}", file=sys.stderr)
        return found_in_assets, True

    # 3. Search common directories
    for search_dir in SEARCH_DIRS:
        candidate = search_dir / decoded_filename
        if candidate.is_file():
            print(f"[parse_markdown] Found image in {search_dir}: {decoded_filename}", file=sys.stderr)
            return str(candidate), True

    print(f"[parse_markdown] WARNING: Image not found: '{decoded_path}'", file=sys.stderr)
    return original_path, False


def clean_markdown_errors(markdown: str) -> tuple[str, list[str]]:
    """Clean common markdown formatting errors.

    Returns:
        (cleaned_markdown, list_of_errors_fixed)
    """
    errors_fixed = []

    # Extract inline images to standalone lines
    # Find all images and check if they're on a line with other content
    count_extracted = 0
    lines = markdown.split('\n')
    new_lines = []

    img_pattern_inline = re.compile(r'!\[[^\]]*\]\(.+\)')

    for line in lines:
        # Find all images in this line
        img_matches = list(img_pattern_inline.finditer(line))

        if not img_matches:
            # No images, keep line as is
            new_lines.append(line)
        elif len(img_matches) == 1 and line.strip() == img_matches[0].group(0):
            # Single image that is the entire line (already standalone)
            new_lines.append(line)
        else:
            # Image(s) with other content on the same line - extract them
            # Split the line by images and reassemble
            pos = 0
            for match in img_matches:
                # Add text before image (if any)
                before = line[pos:match.start()].strip()
                if before:
                    new_lines.append(before)
                # Add image on its own line
                new_lines.append(match.group(0))
                pos = match.end()
                count_extracted += 1

            # Add remaining text after last image (if any)
            after = line[pos:].strip()
            if after:
                new_lines.append(after)

    markdown = '\n'.join(new_lines)

    if count_extracted > 0:
        errors_fixed.append(f"Extracted {count_extracted} inline image(s) to standalone lines")
        print(f"[parse_markdown] Extracted {count_extracted} inline images to standalone lines", file=sys.stderr)

    # Fix malformed image references like: ![](path (1).jpeg).jpeg)
    # This handles cases where extension is repeated, even with parentheses in path
    # Use .+ for greedy matching to handle paths with parentheses like "image (1).jpeg"
    pattern1 = r'(!\[[^\]]*\]\((.+?)\.(\w+)\))\.\3\)'
    matches1 = re.findall(pattern1, markdown)
    if matches1:
        markdown = re.sub(pattern1, r'\1', markdown)
        errors_fixed.append(f"Fixed {len(matches1)} .ext).ext) format error(s)")
        print(f"[parse_markdown] Fixed .ext).ext) format errors: {len(matches1)}", file=sys.stderr)

    # Fix extra closing parenthesis: ![](path))
    # Use .+ for greedy matching to handle parentheses in path
    pattern2 = r'(!\[[^\]]*\]\((.+)\))\)'
    matches2 = re.findall(pattern2, markdown)
    if matches2:
        markdown = re.sub(pattern2, r'\1', markdown)
        errors_fixed.append(f"Fixed {len(matches2)} extra parenthesis error(s)")
        print(f"[parse_markdown] Fixed extra closing parenthesis: {len(matches2)}", file=sys.stderr)

    # Fix double extensions like: .jpeg.jpeg
    double_ext = re.findall(r'\.(jpe?g|png|gif|webp)\.\1', markdown, re.IGNORECASE)
    if double_ext:
        markdown = re.sub(r'\.(jpe?g|png|gif|webp)\.\1', r'.\1', markdown, flags=re.IGNORECASE)
        errors_fixed.append(f"Fixed {len(double_ext)} double extension(s)")

    # Fix unclosed image syntax
    unclosed = re.findall(r'!\[[^\]]*\]\([^)]*$', markdown, re.MULTILINE)
    if unclosed:
        errors_fixed.append(f"WARNING: {len(unclosed)} unclosed image reference(s)")

    return markdown, errors_fixed


def extract_title_from_filename(filepath: str) -> str:
    """Extract article title from filename.

    Priority: Use filename (without extension) as title.
    This avoids confusion with H1 chapter titles in the content.

    Args:
        filepath: Path to markdown file

    Returns:
        Title extracted from filename
    """
    filename = os.path.basename(filepath)
    # Remove extension
    title = os.path.splitext(filename)[0]
    # Clean up common prefixes/suffixes
    title = re.sub(r'^\d{4}-?\d{2}-?\d{2}[-_]?', '', title)  # Remove date prefix
    title = title.strip('_- ')
    return title if title else "Untitled"


def split_into_blocks(markdown: str) -> list[str]:
    """Split markdown into logical blocks (paragraphs, headers, quotes, code blocks, etc.)."""
    blocks = []
    current_block = []
    in_code_block = False
    code_block_lines = []

    lines = markdown.split('\n')

    for line in lines:
        stripped = line.strip()

        # Handle code block boundaries
        if stripped.startswith('```'):
            if in_code_block:
                # End of code block
                in_code_block = False
                if code_block_lines:
                    blocks.append('___CODE_BLOCK_START___' + '\n'.join(code_block_lines) + '___CODE_BLOCK_END___')
                code_block_lines = []
            else:
                # Start of code block
                if current_block:
                    blocks.append('\n'.join(current_block))
                    current_block = []
                in_code_block = True
            continue

        # If inside code block, collect ALL lines
        if in_code_block:
            code_block_lines.append(line)
            continue

        # Empty line signals end of block
        if not stripped:
            if current_block:
                blocks.append('\n'.join(current_block))
                current_block = []
            continue

        # Horizontal rule (divider) is its own block
        if re.match(r'^---+$', stripped):
            if current_block:
                blocks.append('\n'.join(current_block))
                current_block = []
            blocks.append('___DIVIDER___')
            continue

        # Headers, blockquotes are their own blocks
        if stripped.startswith(('#', '>')):
            if current_block:
                blocks.append('\n'.join(current_block))
                current_block = []
            blocks.append(stripped)
            continue

        # Image on its own line is its own block
        if re.match(r'^!\[.*\]\(.*\)$', stripped):
            if current_block:
                blocks.append('\n'.join(current_block))
                current_block = []
            blocks.append(stripped)
            continue

        current_block.append(line)

    if current_block:
        blocks.append('\n'.join(current_block))

    # Handle unclosed code block
    if code_block_lines:
        blocks.append('___CODE_BLOCK_START___' + '\n'.join(code_block_lines) + '___CODE_BLOCK_END___')

    return blocks


def extract_images_and_dividers(markdown: str, base_path: Path) -> tuple[list[dict], list[dict], str, int]:
    """Extract images and dividers with their block index positions.

    Returns:
        (image_list, divider_list, markdown_without_images_and_dividers, total_blocks)
    """
    blocks = split_into_blocks(markdown)
    images = []
    dividers = []
    clean_blocks = []

    # Use greedy matching .+ to handle paths with parentheses like "image (1).jpeg"
    img_pattern = re.compile(r'^!\[([^\]]*)\]\((.+)\)$')

    for i, block in enumerate(blocks):
        block_stripped = block.strip()

        # Check for divider
        if block_stripped == '___DIVIDER___':
            block_index = len(clean_blocks)
            after_text = ""
            if clean_blocks:
                prev_block = clean_blocks[-1].strip()
                lines = [l for l in prev_block.split('\n') if l.strip()]
                after_text = lines[-1][:80] if lines else ""
            dividers.append({
                "block_index": block_index,
                "after_text": after_text
            })
            continue

        match = img_pattern.match(block_stripped)
        if match:
            alt_text = match.group(1)
            img_path = match.group(2)

            # Decode URL-encoded path
            img_path_decoded = urllib.parse.unquote(img_path)

            if not os.path.isabs(img_path_decoded):
                resolved_path = str(base_path / img_path_decoded)
            else:
                resolved_path = img_path_decoded

            filename = os.path.basename(img_path_decoded)
            full_path, exists = find_image_file(resolved_path, filename, base_path)

            block_index = len(clean_blocks)

            after_text = ""
            text_before = ""
            block_type = "paragraph"  # default

            if clean_blocks:
                prev_block = clean_blocks[-1].strip()
                lines = [l for l in prev_block.split('\n') if l.strip()]
                after_text = lines[-1][:80] if lines else ""

                # Extract text_before (first 50 chars of the block content)
                text_before = prev_block[:50]

                # Determine block type
                if prev_block.startswith('#'):
                    if prev_block.startswith('# '):
                        block_type = "heading"
                    elif prev_block.startswith('## '):
                        block_type = "heading"
                elif prev_block.startswith('>'):
                    block_type = "blockquote"
                elif prev_block.startswith('- ') or prev_block.startswith('* '):
                    block_type = "list-item"
                else:
                    block_type = "paragraph"

            images.append({
                "path": full_path,
                "original_path": resolved_path,
                "exists": exists,
                "alt": alt_text,
                "block_index": block_index,
                "after_text": after_text,
                "text_before": text_before,
                "text_after": "",  # Will be filled after loop
                "block_type": block_type
            })
        else:
            clean_blocks.append(block)

    # Fill text_after for each image (next block after insertion point)
    for img in images:
        next_block_index = img["block_index"] + 1
        if next_block_index < len(clean_blocks):
            next_block = clean_blocks[next_block_index].strip()
            img["text_after"] = next_block[:30]  # First 30 chars of next block
        else:
            img["text_after"] = ""  # No next block

    clean_markdown = '\n\n'.join(clean_blocks)
    return images, dividers, clean_markdown, len(clean_blocks)


def extract_title(markdown: str, use_h1: bool = False) -> tuple[str, str]:
    """Extract title from first H1, H2, or first non-empty line.

    Args:
        markdown: Markdown content
        use_h1: If True, use H1 as title (default False - prefer filename)

    Returns:
        (title, markdown_without_title): Title string and markdown with H1 title removed.
    """
    lines = markdown.strip().split('\n')
    title = "Untitled"
    title_line_idx = None

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # H1 - use as title and mark for removal
        if stripped.startswith('# '):
            title = stripped[2:].strip()
            title_line_idx = idx
            break
        # H2 - use as title but don't remove (it's a section header)
        if stripped.startswith('## '):
            title = stripped[3:].strip()
            break
        # First non-empty, non-image line
        if not stripped.startswith('!['):
            title = stripped[:100]
            break

    # Remove H1 title line from markdown to avoid duplication
    if title_line_idx is not None:
        lines.pop(title_line_idx)
        markdown = '\n'.join(lines)

    return title, markdown


def markdown_to_html(markdown: str) -> str:
    """Convert markdown to HTML for X Articles rich text paste."""
    html = markdown

    # Process code blocks first
    def convert_code_block(match):
        code_content = match.group(1)
        lines = code_content.strip().split('\n')
        formatted = '<br>'.join(line for line in lines if line.strip())
        return f'<blockquote>{formatted}</blockquote>'

    html = re.sub(r'___CODE_BLOCK_START___(.*?)___CODE_BLOCK_END___', convert_code_block, html, flags=re.DOTALL)

    # H1 -> H2 (X Articles uses H2 for section headers)
    html = re.sub(r'^# (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)

    # Headers
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)

    # Bold
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)

    # Italic
    html = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', html)

    # Links
    html = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', html)

    # Blockquotes
    html = re.sub(r'^> (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)

    # Unordered lists
    html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)

    # Ordered lists
    html = re.sub(r'^\d+\. (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)

    # Wrap consecutive <li> in <ul>
    html = re.sub(r'((?:<li>.*?</li>\n?)+)', r'<ul>\1</ul>', html)

    # Paragraphs
    parts = html.split('\n\n')
    processed_parts = []

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith(('<h2>', '<h3>', '<blockquote>', '<ul>', '<ol>')):
            processed_parts.append(part)
        else:
            part = part.replace('\n', '<br>')
            processed_parts.append(f'<p>{part}</p>')

    # Add UTF-8 encoding marker as defense layer
    # Note: X Articles editor may strip <meta> tags, but we add this as standard practice
    utf8_marker = '<!-- UTF-8 Encoding Marker -->\n'
    return utf8_marker + ''.join(processed_parts)


def parse_markdown_file(filepath: str) -> dict:
    """Parse a markdown file and return structured data."""
    print(f"[parse_markdown] === Starting to parse: {filepath} ===", file=sys.stderr)

    path = Path(filepath)
    base_path = path.parent

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Clean markdown errors first
    content, errors_fixed = clean_markdown_errors(content)
    if errors_fixed:
        for err in errors_fixed:
            print(f"[parse_markdown] {err}", file=sys.stderr)

    # Skip YAML frontmatter if present
    if content.startswith('---'):
        end_marker = content.find('---', 3)
        if end_marker != -1:
            content = content[end_marker + 3:].strip()

    # Extract title from filename (preferred) and content H1
    filename_title = extract_title_from_filename(filepath)
    content_title, content = extract_title(content)

    # Use filename title if it looks meaningful, otherwise use content title
    if filename_title and filename_title != "Untitled" and len(filename_title) > 3:
        title = filename_title
    else:
        title = content_title

    # Extract images and dividers with block indices
    images, dividers, clean_markdown, total_blocks = extract_images_and_dividers(content, base_path)

    # Convert to HTML
    html = markdown_to_html(clean_markdown)

    cover_image = images[0]["path"] if images else None
    cover_exists = images[0]["exists"] if images else True
    content_images = images[1:] if len(images) > 1 else []

    missing = [img for img in images if not img["exists"]]
    if missing:
        print(f"[parse_markdown] WARNING: {len(missing)} image(s) not found", file=sys.stderr)

    # Print detailed statistics
    print(f"[parse_markdown] === Image Statistics ===", file=sys.stderr)
    print(f"[parse_markdown] Total images found: {len(images)}", file=sys.stderr)
    print(f"[parse_markdown] - Cover image: {1 if cover_image else 0}", file=sys.stderr)
    print(f"[parse_markdown] - Content images: {len(content_images)}", file=sys.stderr)
    print(f"[parse_markdown] - Missing images: {len(missing)}", file=sys.stderr)

    # List each content image with status
    for i, img in enumerate(content_images):
        status = "✓" if img['exists'] else "✗"
        img_name = Path(img['path']).name
        print(f"[parse_markdown] [{status}] Image {i+1}: {img_name}", file=sys.stderr)

    # Verify image count matches expected
    expected_count = len(re.findall(r'!\[[^\]]*\]\([^\)]+\)', content))
    actual_count = len(images)

    if expected_count != actual_count:
        print(f"[parse_markdown] WARNING: Image count mismatch!", file=sys.stderr)
        print(f"[parse_markdown]   Expected (from Markdown): {expected_count}", file=sys.stderr)
        print(f"[parse_markdown]   Actual (resolved): {actual_count}", file=sys.stderr)
        print(f"[parse_markdown]   Missing: {expected_count - actual_count}", file=sys.stderr)
    else:
        print(f"[parse_markdown] ✓ All {actual_count} images resolved successfully", file=sys.stderr)

    return {
        "title": title,
        "filename_title": filename_title,
        "content_title": content_title,
        "cover_image": cover_image,
        "cover_exists": cover_exists,
        "content_images": content_images,
        "dividers": dividers,
        "html": html,
        "total_blocks": total_blocks,
        "source_file": str(path.absolute()),
        "missing_images": len(missing),
        "errors_fixed": errors_fixed,
        "expected_image_count": len(content_images)
    }


def find_markdown_file(input_path: str) -> str:
    """
    智能查找 Markdown 文件。

    支持三种模式：
    1. 文件路径：直接返回
    2. 目录路径：列出所有 .md 文件，如果只有一个则返回，多个则报错提示
    3. 关键词：在当前目录搜索包含关键词的 .md 文件

    Args:
        input_path: 文件路径、目录路径或关键词

    Returns:
        找到的 Markdown 文件的完整路径

    Raises:
        SystemExit: 找不到文件或有多个匹配时
    """
    import glob

    # 情况1：直接是文件且存在
    if os.path.isfile(input_path):
        print(f"[parse_markdown] Found file directly: {input_path}", file=sys.stderr)
        return os.path.abspath(input_path)

    # 情况2：是目录
    if os.path.isdir(input_path):
        search_dir = input_path
        pattern = os.path.join(search_dir, "*.md")
        md_files = glob.glob(pattern)

        if len(md_files) == 0:
            print(f"Error: No .md files found in directory: {search_dir}", file=sys.stderr)
            sys.exit(1)
        elif len(md_files) == 1:
            print(f"[parse_markdown] Found single .md file in directory: {md_files[0]}", file=sys.stderr)
            return os.path.abspath(md_files[0])
        else:
            print(f"Error: Multiple .md files found in directory: {search_dir}", file=sys.stderr)
            print("Please specify which file to parse:", file=sys.stderr)
            for i, f in enumerate(md_files, 1):
                print(f"  {i}. {os.path.basename(f)}", file=sys.stderr)
            sys.exit(1)

    # 情况3：可能是关键词或不存在的路径
    # 尝试在当前目录搜索包含关键词的 .md 文件
    cwd = os.getcwd()
    all_md_files = glob.glob(os.path.join(cwd, "*.md"))

    # 关键词匹配（不区分大小写）
    keyword = input_path.lower()
    matched_files = [f for f in all_md_files if keyword in os.path.basename(f).lower()]

    if len(matched_files) == 0:
        # 尝试空格分割的多关键词匹配
        keywords = keyword.split()
        matched_files = [
            f for f in all_md_files
            if all(kw in os.path.basename(f).lower() for kw in keywords)
        ]

    if len(matched_files) == 0:
        print(f"Error: Cannot find file matching: {input_path}", file=sys.stderr)
        print(f"Searched in: {cwd}", file=sys.stderr)
        if all_md_files:
            print(f"Available .md files:", file=sys.stderr)
            for f in all_md_files[:5]:  # 只显示前5个
                print(f"  - {os.path.basename(f)}", file=sys.stderr)
        sys.exit(1)
    elif len(matched_files) == 1:
        print(f"[parse_markdown] Found file by keyword '{input_path}': {matched_files[0]}", file=sys.stderr)
        return os.path.abspath(matched_files[0])
    else:
        print(f"Error: Multiple files match keyword '{input_path}':", file=sys.stderr)
        for i, f in enumerate(matched_files, 1):
            print(f"  {i}. {os.path.basename(f)}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='Parse Markdown for X Articles')
    parser.add_argument('file', nargs='?', help='Markdown file path, directory, or keyword (or set MARKDOWN_FILE env variable)')
    parser.add_argument('--output', choices=['json', 'html'], default='json',
                       help='Output format (default: json)')
    parser.add_argument('--html-only', action='store_true',
                       help='Output only HTML content')

    args = parser.parse_args()

    # 优先级：环境变量 > 命令行参数
    input_path = None
    if 'MARKDOWN_FILE' in os.environ:
        input_path = os.environ['MARKDOWN_FILE']
        print(f"[parse_markdown] Using input from MARKDOWN_FILE env: {input_path}", file=sys.stderr)
    elif args.file:
        input_path = args.file
    else:
        parser.error("Please provide markdown file via MARKDOWN_FILE environment variable or command line argument")

    # 智能查找文件
    markdown_file = find_markdown_file(input_path)

    result = parse_markdown_file(markdown_file)

    if args.html_only:
        print(result['html'])
    elif args.output == 'json':
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result['html'])


if __name__ == '__main__':
    main()
