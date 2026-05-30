"""Turn the converter's markdown into the inputs the Medium web editor needs (Wave 6).

The web editor can't take markdown. The corroborated technique is to PASTE an HTML
fragment into Medium's ProseMirror editor, which parses it into native blocks
(h1->title, h2/h3->headers, pre/code->code blocks, ul/ol->lists, b/em/a->inline
marks). See docs/PLAYWRIGHT_SETUP.md and the Wave 6 research note.

Images are the exception: a local image (a sentinel URL produced by
PlaywrightBackend.upload_image) is NOT publicly reachable, so Medium can't fetch it
from an <img src>. Those must be uploaded through the editor's file input instead.
So this module turns the markdown into an ORDERED list of operations — paste-this-html
or upload-this-image — that PlaywrightBackend replays against the editor in document
order, keeping images in roughly their original place.

This converts ONLY the subset converter.py emits (it is generated, not arbitrary
user markdown): #..###### headings, **bold**, _italic_, `code`, [text](url),
![alt](url), backtick-fenced code blocks (body verbatim), and `- ` / `1. ` lists.
Pure string transform, no IO.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass

# An inline image token: ![alt](url). alt has no ']'; url has no ')' (the converter
# guarantees this — its sentinel URLs and Google alt text never contain those).
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
# A line that is only backticks (>=3) — a code fence open/close emitted by the converter.
_FENCE_RE = re.compile(r"^(`{3,})\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_UL_RE = re.compile(r"^-\s+(.*)$")
_OL_RE = re.compile(r"^\d+\.\s+(.*)$")


@dataclass(frozen=True)
class PasteOp:
    """Paste this HTML fragment into the editor at the current position."""

    html: str


@dataclass(frozen=True)
class ImageOp:
    """Upload the image identified by this markdown url (a sentinel) with this alt text."""

    url: str
    alt: str


def to_operations(markdown: str) -> list[object]:
    """Split markdown into ordered PasteOp / ImageOp operations for the editor.

    Blocks are tokenized fence-aware so a code body containing a blank line is not
    split. Within a non-code block, inline images are pulled out as ImageOps so they
    upload through the editor file input; the surrounding text stays as PasteOps.
    """
    ops: list[object] = []
    for block in _tokenize_blocks(markdown):
        if block.kind == "code":
            ops.append(PasteOp(_code_to_html(block.lines)))
            continue
        raw = "\n".join(block.lines)
        # Only paragraphs get split around images for file-upload. A heading/list with an
        # inline image (rare) renders through _block_to_html so its structure is correct
        # and the image degrades to an <img> tag — never leaks a literal '##'/'- '.
        if block.kind == "para" and _IMAGE_RE.search(raw):
            ops.extend(_split_block_with_images(raw))
            continue
        html_frag = _block_to_html(block)
        if html_frag:
            ops.append(PasteOp(html_frag))
    return ops


def markdown_to_html(markdown: str) -> str:
    """Render the whole markdown to a single HTML fragment (images become <img>).

    Used for previews/tests and as the text/plain-independent representation. The live
    editor path uses to_operations() instead so local images upload via the file input.
    """
    parts: list[str] = []
    for block in _tokenize_blocks(markdown):
        if block.kind == "code":
            parts.append(_code_to_html(block.lines))
        else:
            frag = _block_to_html(block)
            if frag:
                parts.append(frag)
    return "".join(parts)


# --- block tokenizer ---------------------------------------------------------------


@dataclass
class _Block:
    kind: str  # para | heading | list | code
    lines: list[str]


def _tokenize_blocks(markdown: str) -> list[_Block]:
    """Group lines into blocks, treating a backtick-fenced region as one opaque block.

    A blank line separates ordinary blocks; inside a fence, blank lines are part of the
    code body and never split it (the converter can emit blank lines within a snippet).
    """
    lines = (markdown or "").split("\n")
    blocks: list[_Block] = []
    i = 0
    n = len(lines)
    while i < n:
        fence = _FENCE_RE.match(lines[i])
        if fence:
            close_len = len(fence.group(1))
            body: list[str] = []
            i += 1
            while i < n:
                m = _FENCE_RE.match(lines[i])
                if m and len(m.group(1)) >= close_len:
                    i += 1  # consume the closing fence
                    break
                body.append(lines[i])
                i += 1
            blocks.append(_Block("code", body))
            continue
        if lines[i].strip() == "":
            i += 1
            continue
        if _HEADING_RE.match(lines[i]):
            blocks.append(_Block("heading", [lines[i]]))
            i += 1
            continue
        if _UL_RE.match(lines[i]) or _OL_RE.match(lines[i]):
            group: list[str] = []
            while i < n and (_UL_RE.match(lines[i]) or _OL_RE.match(lines[i])):
                group.append(lines[i])
                i += 1
            blocks.append(_Block("list", group))
            continue
        # Paragraph: consume until a blank line or a structural line.
        para: list[str] = []
        while i < n and lines[i].strip() != "" and not _FENCE_RE.match(lines[i]) \
                and not _HEADING_RE.match(lines[i]) \
                and not _UL_RE.match(lines[i]) and not _OL_RE.match(lines[i]):
            para.append(lines[i])
            i += 1
        blocks.append(_Block("para", para))
    return blocks


# --- block renderers ---------------------------------------------------------------


def _block_to_html(block: _Block) -> str:
    if block.kind == "heading":
        m = _HEADING_RE.match(block.lines[0])
        level = len(m.group(1))
        return f"<h{level}>{_inline(m.group(2).strip())}</h{level}>"
    if block.kind == "list":
        return _list_to_html(block.lines)
    # paragraph: internal newlines (e.g. flattened table rows) become <br>.
    text = "\n".join(block.lines).strip()
    if not text:
        return ""
    return "<p>" + "<br>".join(_inline(line) for line in text.split("\n")) + "</p>"


def _list_to_html(lines: list[str]) -> str:
    """Render a run of list lines. A leading ordered item makes the whole run <ol>.

    Nested lists are out of scope upstream (the converter degrades them), so every line
    is a flat <li>; this stays correct for the markdown actually produced.
    """
    ordered = bool(_OL_RE.match(lines[0]))
    items = []
    for line in lines:
        m = _OL_RE.match(line) or _UL_RE.match(line)
        items.append(f"<li>{_inline(m.group(1).strip())}</li>")
    tag = "ol" if ordered else "ul"
    return f"<{tag}>{''.join(items)}</{tag}>"


def _code_to_html(body_lines: list[str]) -> str:
    """A fenced block -> <pre><code> with the body escaped verbatim (no inline parsing)."""
    body = "\n".join(body_lines)
    return f"<pre><code>{_html.escape(body)}</code></pre>"


def _split_block_with_images(raw: str) -> list[object]:
    """Split a paragraph around inline images into PasteOp/ImageOp in document order.

    Text on either side of an image becomes a paragraph; each image becomes an ImageOp
    (uploaded through the editor file input). Most images are their own paragraph
    upstream, so this usually yields a single ImageOp.
    """
    ops: list[object] = []
    pos = 0
    for m in _IMAGE_RE.finditer(raw):
        before = raw[pos:m.start()].strip()
        if before:
            ops.append(PasteOp("<p>" + _inline(before) + "</p>"))
        ops.append(ImageOp(url=m.group(2).strip(), alt=m.group(1).strip()))
        pos = m.end()
    after = raw[pos:].strip()
    if after:
        ops.append(PasteOp("<p>" + _inline(after) + "</p>"))
    return ops


# --- inline rendering --------------------------------------------------------------


def _inline(text: str) -> str:
    """Render inline markdown to HTML, escaping anything that isn't a recognized mark.

    Order matters: code spans are pulled out first (placeholdered) so their literal
    contents are never reinterpreted as bold/italic/links, then restored last.
    """
    if not text:
        return ""

    code_spans: list[str] = []

    def _stash_code(m: re.Match) -> str:
        code_spans.append(_html.escape(m.group(1)))
        return f"\x00CODE{len(code_spans) - 1}\x00"

    # Inline code: `...`. Non-greedy, single backtick delimiters (the converter's form).
    text = re.sub(r"`([^`]+)`", _stash_code, text)

    # Inline image (rare here — usually split out already): ![alt](url) -> <img>. Stash the
    # built tag so the escape step below can't turn it into &lt;img&gt;.
    images: list[str] = []

    def _stash_img(m: re.Match) -> str:
        images.append(f'<img src="{_attr(m.group(2).strip())}" alt="{_attr(m.group(1).strip())}">')
        return f"\x00IMG{len(images) - 1}\x00"

    text = _IMAGE_RE.sub(_stash_img, text)

    # Links: [text](url). Capture before escaping so brackets aren't entity-mangled.
    links: list[str] = []

    def _stash_link(m: re.Match) -> str:
        inner = _emphasis(_escape_text(m.group(1)))
        links.append(f'<a href="{_attr(m.group(2).strip())}">{inner}</a>')
        return f"\x00LINK{len(links) - 1}\x00"

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _stash_link, text)

    # Everything left is plain text with possible **bold** / _italic_ markers.
    text = _emphasis(_escape_text(text))

    # Restore images, links, and code spans (distinct placeholders, order-independent).
    text = re.sub(r"\x00IMG(\d+)\x00", lambda m: images[int(m.group(1))], text)
    text = re.sub(r"\x00LINK(\d+)\x00", lambda m: links[int(m.group(1))], text)
    text = re.sub(r"\x00CODE(\d+)\x00", lambda m: f"<code>{code_spans[int(m.group(1))]}</code>", text)
    return text


def _escape_text(text: str) -> str:
    """Escape HTML special chars but keep our private placeholder bytes intact."""
    return _html.escape(text, quote=False)


def _emphasis(text: str) -> str:
    """Apply **bold** then _italic_ on already-escaped text.

    Italic underscores must sit at a word boundary so snake_case identifiers, paths, and
    filenames (file_name_here.py, my_var) are NOT mangled into emphasis — the converter
    passes arbitrary body prose through here. This matches Medium/CommonMark's intraword-
    underscore rule.
    """
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", text)
    return text


def _attr(value: str) -> str:
    """Escape a value for use inside a double-quoted HTML attribute."""
    return _html.escape(value, quote=True)
