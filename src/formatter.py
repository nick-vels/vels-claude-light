"""Markdown to Telegram HTML converter.

Telegram Bot API supports a limited HTML subset:
<b>, <i>, <u>, <s>, <code>, <pre>, <a href="">, <tg-spoiler>

This module converts GitHub-flavored Markdown (from Claude Code)
into Telegram-compatible HTML.
"""
from __future__ import annotations

import html
import re

# ── Cell-level markdown helpers ────────────────────────────────────────────────

def _cell_to_html(cell: str) -> str:
    """Convert a raw Markdown cell to Telegram HTML.

    1. Strip markdown markers and convert to HTML
    """
    text = cell

    # Bold: **text** → <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"⟨B⟩\1⟨/B⟩", text)
    # Italic: *text*
    text = re.sub(r"(?<!\w)\*([^*\n]+?)\*(?!\w)", r"⟨I⟩\1⟨/I⟩", text)
    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'⟨A⟩\1⟨HREF⟩\2⟨/A⟩', text)

    # HTML-escape
    text = html.escape(text)

    # Restore tags
    text = text.replace("⟨B⟩", "<b>").replace("⟨/B⟩", "</b>")
    text = text.replace("⟨I⟩", "<i>").replace("⟨/I⟩", "</i>")
    text = re.sub(r"⟨A⟩(.+?)⟨HREF⟩(.+?)⟨/A⟩", r'<a href="\2">\1</a>', text)

    return text


# ── Table rendering ────────────────────────────────────────────────────────────

def _extract_tables(text: str, table_blocks: list[str]) -> str:
    """Scan *text* for Markdown tables, render them as card-style HTML.

    Must be called BEFORE the main HTML-escape pass.
    """
    lines = text.split("\n")
    result: list[str] = []
    current_table: list[str] = []
    in_table = False

    for line in lines:
        stripped = line.strip()
        is_table_line = bool(re.match(r"^\|.*\|$", stripped))

        if is_table_line:
            if not in_table:
                in_table = True
                current_table = []
            current_table.append(stripped)
        else:
            if in_table:
                block = _render_table(current_table)
                table_blocks.append(block)
                result.append(f"\x00TABLE{len(table_blocks) - 1}\x00")
                current_table = []
                in_table = False
            result.append(line)

    if in_table and current_table:
        block = _render_table(current_table)
        table_blocks.append(block)
        result.append(f"\x00TABLE{len(table_blocks) - 1}\x00")

    return "\n".join(result)


def _render_table(lines: list[str]) -> str:
    """Render a Markdown table as card-style HTML entries.

    Instead of <pre> with column alignment (which breaks on mixed scripts),
    each row becomes a compact card with header labels.

    For small tables (≤4 columns): horizontal format
        <b>1.</b> Value1 · Value2 · Value3

    For large tables (>4 columns): two-line format
        <b>Title</b>
        key1: val1 | key2: val2 | key3: val3
    """
    if not lines:
        return ""

    # Parse cells
    rows: list[list[str]] = []
    headers: list[str] = []
    has_separator = False

    for line in lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(re.match(r"^[-:]+$", c.strip()) for c in cells if c.strip()):
            has_separator = True
            continue
        rows.append(cells)

    if not rows:
        return ""

    # First row = headers
    if has_separator and len(rows) > 1:
        headers = rows[0]
        data_rows = rows[1:]
    else:
        headers = []
        data_rows = rows

    if not data_rows:
        return ""

    # Detect which column is the "title" (longest average text)
    # Usually it's the 2nd column (index 1) — after the # column
    num_cols = max(len(r) for r in data_rows)

    # Find the main title column (skip short numeric columns)
    title_col = 0
    if num_cols > 1:
        avg_lens = []
        for j in range(num_cols):
            lengths = [len(r[j]) for r in data_rows if j < len(r)]
            avg_lens.append(sum(lengths) / max(len(lengths), 1))
        title_col = avg_lens.index(max(avg_lens))

    formatted: list[str] = []

    for row in data_rows:
        # Get the title cell
        title = _cell_to_html(row[title_col]) if title_col < len(row) else ""

        # Determine row number (from first column if it's numeric)
        row_num = ""
        if num_cols > 1 and row[0].strip().isdigit():
            row_num = row[0].strip()

        # Collect remaining fields with their header labels
        fields: list[str] = []
        for j in range(num_cols):
            if j == title_col:
                continue
            if j == 0 and row_num:
                continue  # Skip the # column
            val = _cell_to_html(row[j]) if j < len(row) else ""
            if not val.strip():
                continue
            label = html.escape(headers[j]) if j < len(headers) else ""
            if label:
                fields.append(f"{label}: {val}")
            else:
                fields.append(val)

        # Format the entry
        if row_num:
            line_out = f"<b>{row_num}.</b> {title}"
        else:
            line_out = f"<b>{title}</b>"

        if fields:
            line_out += "\n    " + " · ".join(fields)

        formatted.append(line_out)

    return "\n\n".join(formatted)


# ── Main formatter ─────────────────────────────────────────────────────────────

def format_for_telegram(text: str) -> str:
    """Convert GitHub-flavored Markdown to Telegram HTML.

    Handles: code blocks, inline code, tables, headings,
    bold, italic, strikethrough, links, checkboxes, horizontal rules.
    """
    if not text:
        return text

    # ── Step 1: Extract and protect fenced code blocks ────────────────────
    code_blocks: list[str] = []
    inline_codes: list[str] = []

    def save_code_block(match: re.Match) -> str:
        lang = match.group(1) or ""
        code = match.group(2)
        escaped = html.escape(code)
        if lang:
            block = f'<pre><code class="language-{html.escape(lang)}">{escaped}</code></pre>'
        else:
            block = f"<pre>{escaped}</pre>"
        code_blocks.append(block)
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    def save_inline_code(match: re.Match) -> str:
        code = match.group(1)
        escaped = html.escape(code)
        inline_codes.append(f"<code>{escaped}</code>")
        return f"\x00INLINE{len(inline_codes) - 1}\x00"

    # Extract fenced code blocks (``` ... ```)
    text = re.sub(r"```(\w+)?\n(.*?)```", save_code_block, text, flags=re.DOTALL)

    # Extract inline code (` ... `)
    text = re.sub(r"`([^`\n]+)`", save_inline_code, text)

    # ── Step 2: Extract thinking blocks BEFORE HTML-escaping ─────────────
    thinking_blocks: list[str] = []

    def save_thinking_block(match: re.Match) -> str:
        thinking_text = match.group(1)
        escaped = html.escape(thinking_text)
        thinking_blocks.append(f"<i>💭 {escaped}</i>")
        return f"\x01THINKING{len(thinking_blocks) - 1}\x01"

    text = re.sub(r"\x01THINKING\x02(.*?)\x02THINKING\x01", save_thinking_block, text, flags=re.DOTALL)  # noqa: E501

    # ── Step 3: Extract tables BEFORE HTML-escaping ────────────────────────
    # Critical: widths must be measured on raw text — no &amp; inflation.
    table_blocks: list[str] = []
    text = _extract_tables(text, table_blocks)

    # ── Step 4: HTML-escape remaining text (protecting all placeholders) ───
    parts = re.split(r"(\x00(?:CODEBLOCK|INLINE|TABLE)\d+\x00|\x01THINKING\d+\x01)", text)
    for i, part in enumerate(parts):
        if not part.startswith("\x00") and not part.startswith("\x01"):
            parts[i] = html.escape(part)
    text = "".join(parts)

    # ── Step 5: Convert Markdown elements in non-table, non-code text ─────

    # Headings: ## Title → <b>Title</b>
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic: *text* or _text_ (not inside words like file_name)
    text = re.sub(r"(?<!\w)\*([^*\n]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)

    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Links: [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

    # Checkboxes
    text = text.replace("- [ ]", "\u2610")
    text = text.replace("- [x]", "\u2611")
    text = text.replace("- [X]", "\u2611")

    # Horizontal rules: --- or *** or ___ → remove
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

    # ── Step 6: Restore all saved blocks ──────────────────────────────────
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", block)

    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINE{i}\x00", code)

    for i, block in enumerate(table_blocks):
        text = text.replace(f"\x00TABLE{i}\x00", block)

    for i, block in enumerate(thinking_blocks):
        text = text.replace(f"\x01THINKING{i}\x01", block)

    return text.strip()


def strip_html_tags(text: str) -> str:
    """Remove all HTML tags from text. Fallback for parse errors."""
    clean = re.sub(r"<[^>]+>", "", text)
    return html.unescape(clean)
