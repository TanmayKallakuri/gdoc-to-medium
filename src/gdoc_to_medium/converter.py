"""Pure transform: Google Docs `document` resource -> (markdown, [ImageRef], Metadata).

No network, no IO. Inline images become `![alt](PLACEHOLDER:objectId)` placeholders
plus an ImageRef each; the orchestrator resolves them after upload. The function never
raises on a structurally-valid-but-unexpected document: unknown or out-of-scope elements
(tables, footnotes, suggestions, blockquotes, columns) degrade to plain text or are
dropped, and the rest of the document still converts (spec 5.2, 8).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .types import ImageRef, Metadata

# Monospace font names that mark a run/paragraph as code. Detection is by font name
# (spec 11 / risk R2); tuned empirically against real docs at the Wave 5 dry-run. Kept
# lowercase for case-insensitive comparison against Docs' weightedFontFamily.fontFamily.
MONOSPACE_FONTS = frozenset(
    {
        "consolas",
        "courier new",
        "courier",
        "roboto mono",
        "source code pro",
        "monospace",
        "menlo",
        "monaco",
        "inconsolata",
        "fira code",
        "fira mono",
        "jetbrains mono",
        "ibm plex mono",
        "ubuntu mono",
        "dejavu sans mono",
        "liberation mono",
        "cascadia code",
        "cascadia mono",
        "sf mono",
        "pt mono",
    }
)

_HEADING_HASHES = {
    "TITLE": "#",
    "HEADING_1": "#",
    "HEADING_2": "##",
    "HEADING_3": "###",
    "HEADING_4": "####",
    "HEADING_5": "#####",
    "HEADING_6": "######",
}


@dataclass
class _Block:
    """One rendered body block plus the metadata needed to join/coalesce blocks."""

    text: str
    kind: str = "para"  # para | heading | list_item | code | image_only
    # list_item only:
    list_ordered: bool = False
    # the unstyled, single-line plain text of the block, for metadata line matching
    plain: str = ""


def convert(document: dict, filename: str) -> tuple[str, list[ImageRef], Metadata]:
    """Convert a Docs `document` resource to Medium markdown, image refs, and metadata.

    `filename` is the Drive doc name and becomes the post title (spec 4). Robust to a
    `document` that is None, missing `body`, or missing `body.content`.
    """
    image_refs: list[ImageRef] = []
    lists = _safe_dict(document, "lists")
    inline_objects = _safe_dict(document, "inlineObjects")

    content = []
    if isinstance(document, dict):
        body = document.get("body")
        if isinstance(body, dict) and isinstance(body.get("content"), list):
            content = body["content"]

    blocks: list[_Block] = []
    for element in content:
        if not isinstance(element, dict):
            continue
        blocks.extend(_render_structural_element(element, lists, inline_objects, image_refs))

    blocks = _coalesce_code_blocks(blocks)
    metadata = _extract_metadata(blocks, filename)
    markdown = _join_blocks(blocks)
    return markdown, image_refs, metadata


def _safe_dict(document: object, key: str) -> dict:
    if isinstance(document, dict) and isinstance(document.get(key), dict):
        return document[key]
    return {}


def _render_structural_element(
    element: dict, lists: dict, inline_objects: dict, image_refs: list[ImageRef]
) -> list[_Block]:
    if "paragraph" in element and isinstance(element["paragraph"], dict):
        block = _render_paragraph(element["paragraph"], lists, inline_objects, image_refs)
        return [block] if block is not None else []
    if "table" in element:
        return _render_table(element["table"], lists, inline_objects, image_refs)
    # sectionBreak (incl. multi-column), tableOfContents, unknown: drop, neighbors still convert (spec 5.2).
    return []


def _render_paragraph(
    paragraph: dict, lists: dict, inline_objects: dict, image_refs: list[ImageRef]
) -> _Block | None:
    elements = paragraph.get("elements")
    if not isinstance(elements, list):
        elements = []

    style = paragraph.get("paragraphStyle")
    named = style.get("namedStyleType") if isinstance(style, dict) else None

    inline_text, plain_text, all_mono, had_text, had_image = _render_inline_elements(
        elements, inline_objects, image_refs
    )

    bullet = paragraph.get("bullet")
    if isinstance(bullet, dict):
        ordered = _list_is_ordered(bullet.get("listId"), lists)
        text = inline_text.strip()
        if not text and not had_image:
            return None
        return _Block(text=text, kind="list_item", list_ordered=ordered, plain=plain_text.strip())

    if isinstance(named, str) and named in _HEADING_HASHES:
        text = inline_text.strip()
        if not text:
            return None
        prefix = _HEADING_HASHES[named]
        return _Block(text=f"{prefix} {text}", kind="heading", plain=plain_text.strip())

    if all_mono and not had_image and had_text:
        if not plain_text.strip():
            # A blank monospace line is an empty separator, NOT code, so it splits two
            # adjacent code blocks into separate fences during coalescing.
            return _Block(text="", kind="para", plain="")
        # Raw plain text keeps indentation verbatim and avoids leaking inline backticks into the fence.
        return _Block(text=plain_text.rstrip("\n"), kind="code", plain=plain_text.strip())

    text = inline_text.strip()
    if not text:
        return None
    kind = "image_only" if had_image and not plain_text.strip() else "para"
    return _Block(text=text, kind=kind, plain=plain_text.strip())


def _render_inline_elements(
    elements: list, inline_objects: dict, image_refs: list[ImageRef]
) -> tuple[str, str, bool, bool, bool]:
    """Render a paragraph's elements to markdown.

    Returns (markdown, plain_text, all_text_runs_monospace, had_text, had_image).
    `all_text_runs_monospace` is True only when at least one text run exists and every
    non-empty text run uses a monospace font (drives code-block detection).
    """
    parts: list[str] = []
    plain_parts: list[str] = []
    had_text = False
    had_image = False
    all_mono = True

    for el in elements:
        if not isinstance(el, dict):
            continue
        if "textRun" in el:
            run = el["textRun"]
            if not isinstance(run, dict):
                continue
            raw = run.get("content")
            if not isinstance(raw, str) or raw == "":
                continue
            had_text = True
            plain_parts.append(raw)
            style = run.get("textStyle") if isinstance(run.get("textStyle"), dict) else {}
            if not _run_is_monospace(style):
                all_mono = False
            parts.append(_render_text_run(raw, style))
        elif "inlineObjectElement" in el:
            obj = el["inlineObjectElement"]
            if not isinstance(obj, dict):
                continue
            object_id = obj.get("inlineObjectId")
            if not isinstance(object_id, str) or not object_id:
                continue
            had_image = True
            alt, content_uri = _image_alt_and_uri(object_id, inline_objects)
            image_refs.append(ImageRef(object_id=object_id, content_uri=content_uri, alt=alt))
            parts.append(f"![{alt}](PLACEHOLDER:{object_id})")
        # footnoteReference, pageBreak, horizontalRule, equation, etc.: drop silently.

    if not had_text:
        all_mono = False
    return "".join(parts), "".join(plain_parts), all_mono, had_text, had_image


def _render_text_run(raw: str, style: dict) -> str:
    """Apply inline styling to one run's content, preserving its surrounding whitespace.

    Markers wrap only the trimmed core so leading/trailing spaces stay outside the
    emphasis (Markdown does not render `** bold **`).
    """
    if _run_is_monospace(style):
        return _wrap_preserving_space(raw, "`", "`")

    leading = raw[: len(raw) - len(raw.lstrip())]
    trailing = raw[len(raw.rstrip()):]
    core = raw.strip()
    if not core:
        return raw

    link = style.get("link") if isinstance(style.get("link"), dict) else None
    url = link.get("url") if isinstance(link, dict) else None

    if style.get("bold"):
        core = f"**{core}**"
    if style.get("italic"):
        core = f"_{core}_"
    if isinstance(url, str) and url:
        core = f"[{core}]({url})"

    return f"{leading}{core}{trailing}"


def _wrap_preserving_space(raw: str, open_mark: str, close_mark: str) -> str:
    leading = raw[: len(raw) - len(raw.lstrip())]
    trailing = raw[len(raw.rstrip()):]
    core = raw.strip()
    if not core:
        return raw
    return f"{leading}{open_mark}{core}{close_mark}{trailing}"


def _run_is_monospace(style: dict) -> bool:
    if not isinstance(style, dict):
        return False
    wff = style.get("weightedFontFamily")
    if not isinstance(wff, dict):
        return False
    family = wff.get("fontFamily")
    if not isinstance(family, str):
        return False
    return family.strip().lower() in MONOSPACE_FONTS


def _list_is_ordered(list_id: object, lists: dict) -> bool:
    """A list nesting level with a numeric glyphType (DECIMAL/ALPHA/ROMAN) is ordered."""
    if not isinstance(list_id, str):
        return False
    spec = lists.get(list_id)
    if not isinstance(spec, dict):
        return False
    props = spec.get("listProperties")
    if not isinstance(props, dict):
        return False
    levels = props.get("nestingLevels")
    if not isinstance(levels, list) or not levels:
        return False
    first = levels[0]
    if not isinstance(first, dict):
        return False
    glyph = first.get("glyphType")
    ordered_glyphs = {"DECIMAL", "ZERO_DECIMAL", "UPPER_ALPHA", "ALPHA", "UPPER_ROMAN", "ROMAN"}
    if isinstance(glyph, str) and glyph in ordered_glyphs:
        return True
    # Some docs omit glyphType but carry a numeric glyphFormat like "%0.".
    fmt = first.get("glyphFormat")
    return isinstance(fmt, str) and "%" in fmt and "." in fmt


def _image_alt_and_uri(object_id: str, inline_objects: dict) -> tuple[str, str | None]:
    obj = inline_objects.get(object_id)
    if not isinstance(obj, dict):
        return "", None
    props = obj.get("inlineObjectProperties")
    embedded = props.get("embeddedObject") if isinstance(props, dict) else None
    if not isinstance(embedded, dict):
        return "", None
    alt = embedded.get("description") or embedded.get("title") or ""
    if not isinstance(alt, str):
        alt = ""
    img = embedded.get("imageProperties")
    uri = img.get("contentUri") if isinstance(img, dict) else None
    if not isinstance(uri, str):
        uri = None
    return alt.strip(), uri


def _render_table(
    table: dict, lists: dict, inline_objects: dict, image_refs: list[ImageRef]
) -> list[_Block]:
    """Tables are out of scope (spec 5.2): pass each cell's text through as plain prose
    so its content survives, rather than dropping the table or crashing."""
    if not isinstance(table, dict):
        return []
    lines: list[str] = []
    for row in table.get("tableRows", []) or []:
        if not isinstance(row, dict):
            continue
        cell_texts: list[str] = []
        for cell in row.get("tableCells", []) or []:
            if not isinstance(cell, dict):
                continue
            for el in cell.get("content", []) or []:
                if not isinstance(el, dict) or "paragraph" not in el:
                    continue
                elements = el["paragraph"].get("elements", []) if isinstance(el["paragraph"], dict) else []
                text, _, _, _, _ = _render_inline_elements(elements, inline_objects, image_refs)
                text = text.strip()
                if text:
                    cell_texts.append(text)
        if cell_texts:
            lines.append(" ".join(cell_texts))
    if not lines:
        return []
    return [_Block(text="\n".join(lines), kind="para", plain="\n".join(lines))]


def _coalesce_code_blocks(blocks: list[_Block]) -> list[_Block]:
    """Merge runs of consecutive `code` blocks into a single fenced block.

    A non-code block between two code blocks (including a blank monospace separator
    emitted by `_render_paragraph`) ends the run, so adjacent snippets stay in distinct
    fences. The fence length adapts to the content: per CommonMark, a code body that
    itself contains a run of N backticks is wrapped in `max(3, N+1)` backticks so the
    fence cannot terminate early.
    """
    out: list[_Block] = []
    i = 0
    while i < len(blocks):
        if blocks[i].kind != "code":
            out.append(blocks[i])
            i += 1
            continue
        j = i
        lines: list[str] = []
        while j < len(blocks) and blocks[j].kind == "code":
            lines.append(blocks[j].text)
            j += 1
        body = "\n".join(lines)
        fence = "`" * max(3, _longest_backtick_run(body) + 1)
        fenced = f"{fence}\n{body}\n{fence}"
        out.append(_Block(text=fenced, kind="code", plain=body))
        i = j
    return out


def _longest_backtick_run(text: str) -> int:
    longest = 0
    current = 0
    for ch in text:
        if ch == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _extract_metadata(blocks: list[_Block], filename: str) -> Metadata:
    """Pull `Tags:`/`Status:` directive lines out of the body and into Metadata.

    `Status:` matching is case-INSENSITIVE on the key but the value comparison for
    "publish" is also case-insensitive, so `status: PUBLISH` works — authors should not
    have to remember exact casing for a publishing toggle. Directive lines are removed
    from the rendered body either way.
    """
    title = _clean_title(filename)
    tags: list[str] = []
    publish_status = "draft"

    kept: list[_Block] = []
    for block in blocks:
        plain = block.plain.strip()
        lowered = plain.lower()
        if block.kind == "para" and lowered.startswith("tags:"):
            tags = _parse_tags(plain[len("tags:"):])
            continue
        if block.kind == "para" and lowered.startswith("status:"):
            value = plain[len("status:"):].strip().lower()
            publish_status = "public" if value == "publish" else "draft"
            continue
        kept.append(block)

    blocks[:] = kept
    return Metadata(title=title, tags=tags, publish_status=publish_status)


def _parse_tags(raw: str) -> list[str]:
    seen: list[str] = []
    for piece in raw.split(","):
        tag = piece.strip()
        if tag and tag not in seen:
            seen.append(tag)
    return seen[:5]


def _clean_title(filename: str) -> str:
    if not isinstance(filename, str):
        return ""
    name = filename.strip()
    lowered = name.lower()
    for ext in (".gdoc", ".docx", ".doc", ".md", ".txt"):
        if lowered.endswith(ext):
            name = name[: -len(ext)]
            break
    return name.strip()


def _join_blocks(blocks: list[_Block]) -> str:
    parts: list[str] = []
    prev_list = False
    for block in blocks:
        is_list = block.kind == "list_item"
        if not is_list and not block.text:
            # Blank separator sentinels carry no body text; they only split code runs.
            continue
        if is_list:
            marker = "1. " if block.list_ordered else "- "
            parts.append(("\n" if prev_list else "\n\n") + marker + block.text if parts else marker + block.text)
        else:
            text = block.text
            parts.append(("\n\n" + text) if parts else text)
        prev_list = is_list
    return "".join(parts).strip()
