# Converter test fixtures

Hand-authored minimal Google Docs API `documents.get` resources, used to verify the
pure `converter` unit (spec 5.2). Each file is a trimmed-but-shape-faithful `document`
resource: `body.content[]` of StructuralElements, with `lists`, `inlineObjects`, and
`footnotes` maps populated only where a fixture exercises them.

They are intentionally hand-written, not API captures, so they stay small and readable
and contain no real document content. They follow the resource shape pinned in the plan's
"Research already resolved" note. The real-doc dry-run in Wave 5 (T5.5) is what guards
against any drift from the live API shape (risk R7).

## In-scope mapping fixtures (one per spec 5.2 row, plus combined)

| Fixture | Exercises |
|---|---|
| `title_and_headings.json` | `TITLE`, `HEADING_1`..`HEADING_6`, `NORMAL_TEXT` paragraphs |
| `inline_styles.json` | bold, italic, link, bold+italic, bold link, whitespace run, run with no `textStyle` |
| `lists.json` | bulleted list, numbered list, list after heading, single-item list, consecutive items |
| `nested_list.json` | nested list (out-of-scope nesting) degrades to a flat list, no crash |
| `code.json` | inline monospace run, multi-paragraph monospace block coalesced into one fence |
| `images.json` | multiple inline images, image with no alt, image alone in a paragraph |
| `metadata.json` | `Tags:` line (whitespace/empty entries, >5 truncation), `Status: publish` |
| `metadata_minimal.json` | no `Tags:` line, no `Status:` line (defaults: empty tags, draft) |
| `combined.json` | title + tags + status + heading + mixed inline + list + code block + image together |

## Out-of-scope graceful-degradation fixtures (spec 5.2 "Out of scope")

These must NOT raise; the converter drops or plain-text-passes the unsupported element and
still converts the rest of the document.

| Fixture | Out-of-scope element |
|---|---|
| `out_of_scope_table.json` | table (`table` structural element) |
| `out_of_scope_footnote.json` | footnote reference + `footnotes` map |
| `out_of_scope_suggestion.json` | tracked suggestions (`suggestedInsertionIds` / `suggestedDeletionIds`) |
| `out_of_scope_blockquote.json` | indented "blockquote" paragraph |
| `out_of_scope_columns.json` | multi-column `sectionBreak` |

## Defensive / edge fixtures

| Fixture | Exercises |
|---|---|
| `empty.json` | document whose only content is an empty paragraph |
| `gappy.json` | missing/empty `elements`, `textRun` with no `content`, dangling `listId`, dangling `inlineObjectId` |
