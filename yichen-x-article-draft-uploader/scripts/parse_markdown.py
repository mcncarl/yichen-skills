#!/usr/bin/env python3
from __future__ import annotations
"""
Parse Markdown for X Articles publishing.

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
import base64
import html as htmlmod
import io
import json
import os
import re
import string
import sys
import urllib.parse
from collections import Counter
from html.parser import HTMLParser
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

TABLE_MARKER_PREFIX = "X_TABLE_MARKER"
CODE_BLOCK_TOKEN_RE = re.compile(r'\ue000XCODEBLOCKB64([A-Za-z0-9_=-]*)\ue001')
MARKDOWN_ESCAPABLE_ASCII_CLASS = re.escape(string.punctuation)


def _encode_code_block(content: str) -> str:
    payload = base64.urlsafe_b64encode((content or '').encode('utf-8')).decode('ascii')
    return f'\ue000XCODEBLOCKB64{payload}\ue001'


def _decode_code_block(payload: str) -> str:
    return base64.urlsafe_b64decode(payload.encode('ascii')).decode('utf-8')


def strip_yaml_frontmatter(content: str) -> str:
    """Strip only a leading, independently delimited YAML frontmatter block."""
    content = (content or "").removeprefix("\ufeff")
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return content
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            return "".join(lines[index + 1 :]).lstrip("\r\n")
    return content


def _parse_fence_line(line: str) -> tuple[str, int, str] | None:
    match = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
    if not match:
        return None
    delimiter = match.group(1)
    return delimiter[0], len(delimiter), match.group(2)


def _is_valid_fence_opening(parsed: tuple[str, int, str] | None) -> bool:
    return bool(parsed and not (parsed[0] == '`' and '`' in parsed[2]))


def _is_valid_fence_closing(parsed: tuple[str, int, str] | None, character: str, length: int) -> bool:
    return bool(parsed and parsed[0] == character and parsed[1] >= length and not parsed[2].strip())


def _protect_fenced_markdown(markdown: str) -> tuple[str, dict[str, str]]:
    """Hide complete or unclosed fenced blocks from Markdown cleanup regexes."""
    protected = {}
    output = []
    code_lines = []
    fence_character = None
    fence_length = 0

    def store_code_block() -> None:
        token_index = len(protected)
        token = f'\ue000XFENCEDMARKDOWN{token_index:06d}\ue001'
        while token in markdown or token in protected:
            token_index += 1
            token = f'\ue000XFENCEDMARKDOWN{token_index:06d}\ue001'
        protected[token] = '\n'.join(code_lines)
        output.append(token)

    for line in markdown.split('\n'):
        parsed = _parse_fence_line(line)
        if fence_character is None:
            if _is_valid_fence_opening(parsed):
                fence_character = parsed[0]
                fence_length = parsed[1]
                code_lines = [line]
            else:
                output.append(line)
            continue

        code_lines.append(line)
        if _is_valid_fence_closing(parsed, fence_character, fence_length):
            store_code_block()
            code_lines = []
            fence_character = None
            fence_length = 0

    if fence_character is not None:
        store_code_block()
    return '\n'.join(output), protected


def split_table_row(row: str) -> list[str]:
    row = row.strip()
    if row.startswith('|'):
        row = row[1:]
    if row.endswith('|'):
        row = row[:-1]

    cells = []
    current = []
    escaped = False
    for char in row:
        if char == '\\' and not escaped:
            escaped = True
            continue
        if char == '|' and not escaped:
            cells.append(''.join(current).strip())
            current = []
            continue
        current.append(char)
        escaped = False
    cells.append(''.join(current).strip())
    return cells


def is_table_separator(row: str) -> bool:
    cells = split_table_row(row)
    if len(cells) < 2:
        return False
    return all(re.match(r'^:?-{3,}:?$', cell.strip()) for cell in cells)


def parse_table_block(block: str) -> list[list[str]] | None:
    lines = [line.strip() for line in block.split('\n') if line.strip()]
    if len(lines) < 2 or not is_table_separator(lines[1]):
        return None

    header = split_table_row(lines[0])
    separators = split_table_row(lines[1])
    if len(header) < 2 or len(separators) != len(header):
        return None

    rows = [header]
    for line in lines[2:]:
        # A line without any pipe is not a Markdown table row; stop the table
        # there so a caption directly after the table stays a separate paragraph.
        if '|' not in line:
            break
        row = split_table_row(line)
        if len(row) < len(header):
            row = row + [''] * (len(header) - len(row))
        rows.append(row[:len(header)])
    return rows


def extract_tables_and_placeholders(markdown: str) -> tuple[str, list[dict]]:
    blocks = split_into_blocks(markdown)
    clean_blocks = []
    tables = []

    for block in blocks:
        rows = parse_table_block(block)
        if not rows:
            clean_blocks.append(block)
            continue

        marker = f"{TABLE_MARKER_PREFIX}_{len(tables) + 1:03d}_DO_NOT_EDIT"
        after_text = ""
        if clean_blocks:
            prev_block = clean_blocks[-1].strip()
            lines = [line for line in prev_block.split('\n') if line.strip()]
            after_text = lines[-1][:80] if lines else ""
        # A table block may be followed on the same block by a non-table caption
        # line (e.g. "局域网补充解释…" after the IP table). Keep only the pipe
        # rows as the table's Markdown; emit the caption as a separate paragraph
        # so images anchored to it stay outside the native table.
        block_lines = [line for line in block.split('\n') if line.strip()]
        table_markdown = '\n'.join(block_lines[:len(rows) + 1])
        trailing_lines = block_lines[len(rows) + 1:]
        tables.append(
            {
                "index": len(tables) + 1,
                "marker": marker,
                "markdown": table_markdown,
                "rows": rows,
                "row_count": len(rows),
                "column_count": len(rows[0]) if rows else 0,
                "after_text": after_text,
            }
        )
        clean_blocks.append(marker)
        if trailing_lines:
            clean_blocks.append('\n'.join(trailing_lines))

    return '\n\n'.join(clean_blocks), tables


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
    markdown, protected_fences = _protect_fenced_markdown(markdown)
    errors_fixed = []

    # Extract inline images to standalone lines
    # Find all images and check if they're on a line with other content
    count_extracted = 0
    lines = markdown.split('\n')
    new_lines = []

    for line in lines:
        # Find all images in this line
        img_matches = scan_inline_markdown_images(line)

        if not img_matches:
            # No images, keep line as is
            new_lines.append(line)
        elif len(img_matches) == 1 and line.strip() == img_matches[0]["markdown"]:
            # Single image that is the entire line (already standalone)
            new_lines.append(line)
        else:
            # Image(s) with other content on the same line - extract them
            # Split the line by images and reassemble
            pos = 0
            for match in img_matches:
                # Add text before image (if any)
                before = line[pos:match["start"]].strip()
                if before:
                    new_lines.append(before)
                # Add image on its own line
                new_lines.append(match["markdown"])
                pos = match["end"]
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

    for token, fenced_markdown in protected_fences.items():
        markdown = markdown.replace(token, fenced_markdown)

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
    fence_character = None
    fence_length = 0
    code_block_lines = []

    lines = markdown.split('\n')

    for line in lines:
        stripped = line.strip()

        # Handle backtick and tilde fences, including longer opening fences.
        fence_match = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
        if fence_match:
            delimiter = fence_match.group(1)
            trailing = fence_match.group(2)
            character = delimiter[0]
            if fence_character is None:
                if character == '`' and '`' in trailing:
                    current_block.append(line)
                    continue
                # Start of code block
                if current_block:
                    blocks.append('\n'.join(current_block))
                    current_block = []
                fence_character = character
                fence_length = len(delimiter)
            elif character == fence_character and len(delimiter) >= fence_length and not trailing.strip():
                # End of code block
                blocks.append(_encode_code_block('\n'.join(code_block_lines)))
                code_block_lines = []
                fence_character = None
                fence_length = 0
            else:
                code_block_lines.append(line)
            continue

        # If inside code block, collect ALL lines
        if fence_character is not None:
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
        if _parse_inline_image_block(stripped):
            if current_block:
                blocks.append('\n'.join(current_block))
                current_block = []
            blocks.append(stripped)
            continue

        current_block.append(line)

    if current_block:
        blocks.append('\n'.join(current_block))

    # Handle unclosed code block
    if fence_character is not None:
        blocks.append(_encode_code_block('\n'.join(code_block_lines)))

    return blocks


def _is_markdown_escaped(text: str, index: int) -> bool:
    slashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == '\\':
        slashes += 1
        cursor -= 1
    return slashes % 2 == 1


def _parse_balanced_pair(text: str, opening_index: int, opening: str, closing: str) -> tuple[str, int] | None:
    """Parse a balanced Markdown bracket/parenthesis pair with escapes."""
    if opening_index >= len(text) or text[opening_index] != opening:
        return None
    depth = 0
    cursor = opening_index
    while cursor < len(text):
        character = text[cursor]
        if character == '\\':
            cursor += 2
            continue
        if character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return text[opening_index + 1:cursor], cursor
        cursor += 1
    return None


def scan_inline_markdown_images(text: str) -> list[dict]:
    """Return every balanced inline image, including several images on one line.

    This scanner intentionally accepts only ``![alt](destination)``. Reference
    images remain visible to the uploader preflight, where they fail closed.
    """
    source = text or ''
    images = []
    cursor = 0
    while cursor < len(source) - 1:
        if source[cursor:cursor + 2] != '![' or _is_markdown_escaped(source, cursor):
            cursor += 1
            continue
        alt = _parse_balanced_pair(source, cursor + 1, '[', ']')
        if not alt:
            cursor += 2
            continue
        alt_text, alt_closing = alt
        destination_opening = alt_closing + 1
        if destination_opening >= len(source) or source[destination_opening] != '(':
            cursor = alt_closing + 1
            continue
        destination = _parse_balanced_pair(source, destination_opening, '(', ')')
        if not destination:
            cursor = destination_opening + 1
            continue
        destination_text, destination_closing = destination
        images.append(
            {
                "start": cursor,
                "end": destination_closing + 1,
                "alt": alt_text,
                "destination": destination_text,
                "markdown": source[cursor:destination_closing + 1],
            }
        )
        cursor = destination_closing + 1
    return images


def _parse_inline_image_block(block: str) -> tuple[str, str] | None:
    """Parse one complete balanced inline Markdown image block."""
    source = (block or '').strip()
    images = scan_inline_markdown_images(source)
    if len(images) != 1 or images[0]["start"] != 0 or images[0]["end"] != len(source):
        return None
    return images[0]["alt"], images[0]["destination"]


def strip_inline_image_tokens(text: str) -> str:
    """Remove real inline image tokens while preserving all surrounding text."""
    source = text or ""
    images = scan_inline_markdown_images(source)
    if not images:
        return source
    pieces = []
    cursor = 0
    for image in images:
        pieces.append(source[cursor:image["start"]])
        cursor = image["end"]
    pieces.append(source[cursor:])
    return "".join(pieces)


def nearest_visible_anchor_line(block: str) -> str:
    """Return the nearest complete non-empty source line without image markup."""
    visible = strip_inline_image_tokens(block or "")
    lines = [line.strip() for line in visible.split("\n") if line.strip()]
    return lines[-1] if lines else ""


def extract_images_and_dividers(markdown: str, base_path: Path) -> tuple[list[dict], list[dict], str, int]:
    """Extract images and dividers with their block index positions.

    Returns:
        (image_list, divider_list, markdown_without_images_and_dividers, total_blocks)
    """
    blocks = split_into_blocks(markdown)
    images = []
    dividers = []
    clean_blocks = []
    source_occurrences: Counter[str] = Counter()

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

        inline_image = _parse_inline_image_block(block_stripped)
        if inline_image:
            alt_text, img_path = inline_image

            # Decode URL-encoded path
            img_path_decoded = urllib.parse.unquote(img_path)

            if not os.path.isabs(img_path_decoded):
                resolved_path = str(base_path / img_path_decoded)
            else:
                resolved_path = img_path_decoded

            filename = os.path.basename(img_path_decoded)
            full_path, exists = find_image_file(resolved_path, filename, base_path)
            normalized_source_path = os.path.normcase(os.path.normpath(full_path))
            source_occurrences[normalized_source_path] += 1

            block_index = len(clean_blocks)

            after_text = ""
            text_before = ""
            block_type = "paragraph"  # default

            if clean_blocks:
                prev_block = clean_blocks[-1].strip()
                # Keep the complete nearest visible source line. Character
                # truncation makes a correct post-reload DOM paragraph look
                # misplaced, while retaining a prior image token leaks its
                # Markdown path into the semantic anchor.
                text_before = nearest_visible_anchor_line(prev_block)
                after_text = text_before

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
                "block_type": block_type,
                "source_occurrence": source_occurrences[normalized_source_path],
            })
        else:
            clean_blocks.append(block)

    # Fill text_after for each image (next block after insertion point)
    for img in images:
        next_block_index = img["block_index"] + 1
        if next_block_index < len(clean_blocks):
            next_block = clean_blocks[next_block_index].strip()
            img["text_after"] = nearest_visible_anchor_line(next_block)
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

    def split_table_row(row: str) -> list[str]:
        row = row.strip()
        if row.startswith('|'):
            row = row[1:]
        if row.endswith('|'):
            row = row[:-1]

        cells = []
        current = []
        escaped = False
        for char in row:
            if char == '\\' and not escaped:
                escaped = True
                continue
            if char == '|' and not escaped:
                cells.append(''.join(current).strip())
                current = []
                continue
            current.append(char)
            escaped = False
        cells.append(''.join(current).strip())
        return cells

    def is_table_separator(row: str) -> bool:
        cells = split_table_row(row)
        if len(cells) < 2:
            return False
        return all(re.match(r'^:?-{3,}:?$', cell.strip()) for cell in cells)

    def inline_markdown_to_html(text: str) -> str:
        # Ordinary text has already been HTML-escaped and inline code/links/
        # escaped punctuation are protected as inert tokens.
        text = text.strip()
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
        text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
        text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
        text = re.sub(r'_([^_]+)_', r'<em>\1</em>', text)
        return text

    def convert_table_block(block: str) -> str | None:
        lines = [line.strip() for line in block.split('\n') if line.strip()]
        if len(lines) < 2 or not is_table_separator(lines[1]):
            return None

        header = split_table_row(lines[0])
        separators = split_table_row(lines[1])
        if len(header) < 2 or len(separators) != len(header):
            return None

        rows = [split_table_row(line) for line in lines[2:]]

        def normalize_row(row: list[str]) -> list[str]:
            if len(row) < len(header):
                return row + [''] * (len(header) - len(row))
            return row[:len(header)]

        head_cells = ''.join(f'<th>{inline_markdown_to_html(cell)}</th>' for cell in header)
        body_rows = []
        for row in rows:
            normalized = normalize_row(row)
            cells = ''.join(f'<td>{inline_markdown_to_html(cell)}</td>' for cell in normalized)
            body_rows.append(f'<tr>{cells}</tr>')

        body = ''.join(body_rows)
        return f'<table><thead><tr>{head_cells}</tr></thead><tbody>{body}</tbody></table>'

    def convert_table_blocks(source: str) -> str:
        parts = source.split('\n\n')
        converted = []
        for part in parts:
            converted.append(convert_table_block(part.strip()) or part)
        return '\n\n'.join(converted)

    # Replace code blocks with inert tokens before any global Markdown regex.
    # Restore the escaped HTML only after headings/emphasis/links/lists finish.
    protected_code_blocks = {}

    def protect_code_block(match):
        code_content = _decode_code_block(match.group(1))
        token_index = len(protected_code_blocks)
        token = f'\ue000XCODEBLOCK{token_index:06d}\ue001'
        while token in markdown or token in protected_code_blocks:
            token_index += 1
            token = f'\ue000XCODEBLOCK{token_index:06d}\ue001'
        lines = code_content.split('\n')
        formatted = '<br>'.join(htmlmod.escape(line, quote=False) for line in lines)
        protected_code_blocks[token] = f'<blockquote>{formatted}</blockquote>'
        return f'\n\n{token}\n\n'

    html = CODE_BLOCK_TOKEN_RE.sub(protect_code_block, html)

    reference_definitions = {}

    def remove_reference_definition(match):
        label = re.sub(r'\s+', ' ', re.sub(r'\\(.)', r'\1', match.group(1)).strip()).lower()
        destination = match.group(2).strip()
        if destination.startswith('<') and destination.endswith('>'):
            destination = destination[1:-1]
        reference_definitions[label] = re.sub(r'\\(.)', r'\1', destination)
        return ''

    html = re.sub(
        r'^ {0,3}\[([^\]\n]+)\]:[ \t]*(<[^>\n]+>|\S+)(?:[ \t]+[^\n]*)?$',
        remove_reference_definition,
        html,
        flags=re.MULTILINE,
    )

    protected_inline = {}

    def protect_inline(rendered_html: str) -> str:
        token_index = len(protected_inline)
        token = f'\ue110XINLINE{token_index:06d}\ue111'
        while token in html or token in protected_inline:
            token_index += 1
            token = f'\ue110XINLINE{token_index:06d}\ue111'
        protected_inline[token] = rendered_html
        return token

    def visible_link_label(label: str) -> str:
        visible = htmlmod.unescape(label or '')
        visible = re.sub(r'(?<!\\)(`+)(.+?)(?<!`)\1(?!`)', r'\2', visible, flags=re.DOTALL)
        for pattern in (
            r'(?<!\\)(\*\*|__|~~)(?=\S)(.+?)(?<=\S)\1',
            r'(?<!\\)(\*|_)(?=\S)(.+?)(?<=\S)\1',
        ):
            previous = None
            while previous != visible:
                previous = visible
                visible = re.sub(pattern, r'\2', visible, flags=re.DOTALL)
        visible = re.sub(rf'\\([{MARKDOWN_ESCAPABLE_ASCII_CLASS}])', r'\1', visible)
        return htmlmod.escape(visible, quote=False)

    def inline_destination(raw: str) -> str:
        source = (raw or '').strip()
        if source.startswith('<'):
            closing = source.find('>', 1)
            destination = source[1:closing] if closing >= 0 else source[1:]
        else:
            destination_chars = []
            cursor = 0
            while cursor < len(source):
                character = source[cursor]
                if character.isspace():
                    break
                if character == '\\' and cursor + 1 < len(source):
                    cursor += 1
                    character = source[cursor]
                destination_chars.append(character)
                cursor += 1
            destination = ''.join(destination_chars)
        return htmlmod.unescape(destination).strip()

    def protect_markdown_links(source: str) -> str:
        rendered = []
        cursor = 0
        while cursor < len(source):
            if source[cursor] != '[' or _is_markdown_escaped(source, cursor):
                rendered.append(source[cursor])
                cursor += 1
                continue
            if cursor > 0 and source[cursor - 1] == '!' and not _is_markdown_escaped(source, cursor - 1):
                rendered.append(source[cursor])
                cursor += 1
                continue
            label = _parse_balanced_pair(source, cursor, '[', ']')
            if not label:
                rendered.append(source[cursor])
                cursor += 1
                continue
            raw_label, label_closing = label
            following = label_closing + 1
            href = ''
            closing = label_closing
            if following < len(source) and source[following] == '(':
                destination = _parse_balanced_pair(source, following, '(', ')')
                if destination:
                    href = inline_destination(destination[0])
                    closing = destination[1]
            elif following < len(source) and source[following] == '[':
                reference = _parse_balanced_pair(source, following, '[', ']')
                if reference:
                    reference_label = reference[0] or raw_label
                    normalized = re.sub(
                        r'\s+',
                        ' ',
                        re.sub(r'\\(.)', r'\1', reference_label).strip(),
                    ).lower()
                    href = reference_definitions.get(normalized, '')
                    closing = reference[1]
            else:
                normalized = re.sub(
                    r'\s+',
                    ' ',
                    re.sub(r'\\(.)', r'\1', raw_label).strip(),
                ).lower()
                href = reference_definitions.get(normalized, '')
            if not href:
                rendered.append(source[cursor])
                cursor += 1
                continue
            rendered.append(
                protect_inline(
                    f'<a href="{htmlmod.escape(href, quote=True)}">'
                    f'{visible_link_label(raw_label)}</a>'
                )
            )
            cursor = closing + 1
        return ''.join(rendered)

    # Inline code is protected before emphasis so literal `**`/`_` stays text.
    def protect_code_span(match):
        content = re.sub(r'[\r\n]+', ' ', match.group(2))
        if len(content) >= 2 and content.startswith(' ') and content.endswith(' ') and content.strip():
            content = content[1:-1]
        return protect_inline(f'<code>{htmlmod.escape(content, quote=False)}</code>')

    html = re.sub(
        r'(?<!\\)(`+)(.+?)(?<!`)\1(?!`)',
        protect_code_span,
        html,
        flags=re.DOTALL,
    )
    html = protect_markdown_links(html)

    def protect_autolink(match):
        target = match.group(1)
        href = target if ':' in target.split('@', 1)[0] else f'mailto:{target}'
        return protect_inline(
            f'<a href="{htmlmod.escape(href, quote=True)}">'
            f'{htmlmod.escape(target, quote=False)}</a>'
        )

    html = re.sub(
        r'<((?:[A-Za-z][A-Za-z0-9+.-]{1,31}:[^<>\s]*)|(?:[^\s<>]+@[^\s<>]+))>',
        protect_autolink,
        html,
    )

    def protect_escaped_punctuation(match):
        return protect_inline(htmlmod.escape(match.group(1), quote=False))

    html = re.sub(
        rf'\\([{MARKDOWN_ESCAPABLE_ASCII_CLASS}])',
        protect_escaped_punctuation,
        html,
    )
    # Escape all remaining ordinary source text. This prevents an unmatched
    # `<tagless` fragment from being interpreted as HTML and swallowing the tail.
    html = htmlmod.escape(htmlmod.unescape(html), quote=False)

    # Convert pipe tables before global inline Markdown replacements so cell
    # formatting such as **bold** stays as real rich HTML.
    html = convert_table_blocks(html)

    # H1 -> H2 (X Articles uses H2 for section headers)
    html = re.sub(r'^# (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)

    # Headers
    html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
    html = re.sub(r'^### (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)

    # Bold
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'__(.+?)__', r'<strong>\1</strong>', html)

    # Strikethrough
    html = re.sub(r'~~(.+?)~~', r'<s>\1</s>', html)

    # Italic
    html = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', html)
    html = re.sub(r'_([^_]+)_', r'<em>\1</em>', html)

    # Blockquotes
    html = re.sub(r'^&gt; (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)

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
        if part in protected_code_blocks or part.startswith(('<h2>', '<h3>', '<blockquote>', '<ul>', '<ol>', '<table>')):
            processed_parts.append(part)
        else:
            part = part.replace('\n', '<br>')
            processed_parts.append(f'<p>{part}</p>')

    # Add UTF-8 encoding marker as defense layer
    # Note: X Articles editor may strip <meta> tags, but we add this as standard practice
    utf8_marker = '<!-- UTF-8 Encoding Marker -->\n'
    rendered = utf8_marker + ''.join(processed_parts)
    for token, inline_html in protected_inline.items():
        rendered = rendered.replace(token, inline_html)
    for token, code_html in protected_code_blocks.items():
        rendered = rendered.replace(token, code_html)
    return rendered


class _VisibleInlineTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def normalize_title_visible_text(value: str) -> str:
    """Compare a filename title and source H1 by rendered visible semantics."""
    parser = _VisibleInlineTextParser()
    parser.feed(markdown_to_html(value or ""))
    parser.close()
    return re.sub(r"\s+", " ", "".join(parser.parts)).strip()


def parse_markdown_file(filepath: str) -> dict:
    """Parse a markdown file and return structured data."""
    print(f"[parse_markdown] === Starting to parse: {filepath} ===", file=sys.stderr)

    path = Path(filepath)
    base_path = path.parent

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    # Skip YAML frontmatter only when both delimiters are independent lines.
    content = strip_yaml_frontmatter(content)

    # Clean markdown errors first
    content, errors_fixed = clean_markdown_errors(content)
    if errors_fixed:
        for err in errors_fixed:
            print(f"[parse_markdown] {err}", file=sys.stderr)

    # Extract title from filename (preferred) and content H1
    filename_title = extract_title_from_filename(filepath)
    content_title, content_without_title = extract_title(content)

    # Use filename title if it looks meaningful, otherwise use content title
    if filename_title and filename_title != "Untitled" and len(filename_title) > 3:
        title = filename_title
        source_h1_was_removed = content_without_title != content
        if (
            source_h1_was_removed
            and normalize_title_visible_text(filename_title)
            == normalize_title_visible_text(content_title)
        ):
            # A matching filename/H1 pair is the same Article title expressed
            # twice, so keep it out of the body. A semantically different H1 is
            # a real section and remains below as an X-compatible H2.
            content = content_without_title
    else:
        title = content_title
        content = content_without_title

    # Extract images and dividers with block indices
    images, dividers, clean_markdown, total_blocks = extract_images_and_dividers(content, base_path)

    # X Articles currently accepts native tables through its table block editor,
    # not through rich HTML paste. Keep exact Markdown tables as upload metadata
    # and leave temporary markers in the pasted body for precise placement.
    clean_markdown, tables = extract_tables_and_placeholders(clean_markdown)

    # Convert to HTML
    html = markdown_to_html(clean_markdown)
    table_count = len(tables)

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
    print(f"[parse_markdown] - Tables: {table_count}", file=sys.stderr)

    # List each content image with status
    for i, img in enumerate(content_images):
        status = "✓" if img['exists'] else "✗"
        img_name = Path(img['path']).name
        print(f"[parse_markdown] [{status}] Image {i+1}: {img_name}", file=sys.stderr)

    # Verify image count matches expected
    expected_count = sum(
        1 for block in split_into_blocks(content)
        if _parse_inline_image_block(block)
    )
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
        "cover_image_item": images[0] if images else None,
        "cover_exists": cover_exists,
        "content_images": content_images,
        "dividers": dividers,
        "tables": tables,
        "html": html,
        "table_count": table_count,
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
