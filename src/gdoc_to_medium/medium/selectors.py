"""Every Medium web-UI selector the PlaywrightBackend depends on, in one place (Wave 6).

Medium ships no stable contract for these elements — data-testid values and button
text change without notice (Wave 6 research, risk R3). So each thing we touch has an
ORDERED list of candidate selectors: the backend tries them in order and uses the first
that resolves, and the `doctor` self-test reports which (if any) still match. When
Medium changes its UI, a user can edit this list instead of the code.

CSS where possible; Playwright text/has-text pseudo-selectors for buttons whose only
stable handle is their visible label.
"""

from __future__ import annotations

# Where a new draft is created.
NEW_STORY_URL = "https://medium.com/new-story"
# Hitting this while logged out redirects here (host used to detect "not signed in").
SIGNIN_URL_FRAGMENT = "/m/signin"

# The editable story surface (ProseMirror). First match wins.
EDITOR: tuple[str, ...] = (
    '[data-testid="editor"]',
    'div.section-inner [contenteditable="true"]',
    'div[contenteditable="true"][role="textbox"]',
    'article [contenteditable="true"]',
)

# The title field is the first graf inside the editor; some builds tag it explicitly.
TITLE: tuple[str, ...] = (
    '[data-testid="editor"] h3[name="Title"]',
    'h3.graf--title',
    '[data-testid="editor"] [contenteditable="true"]',
)

# Hidden file input behind the inline "+" image control (for uploading local images).
IMAGE_FILE_INPUT: tuple[str, ...] = (
    'input[type="file"][accept*="image"]',
    'input[type="file"]',
)

# Opens the publish settings dialog.
PUBLISH_BUTTON: tuple[str, ...] = (
    '[data-testid="publish-button"]',
    'button[data-action="show-publish-confirm"]',
    'button:has-text("Publish")',
)

# Tag entry inside the publish dialog (up to 5).
TAG_INPUT: tuple[str, ...] = (
    'input[placeholder*="topic" i]',
    'input[placeholder*="tag" i]',
    'div[role="dialog"] input[type="text"]',
)

# The final confirm inside the publish dialog.
PUBLISH_NOW_BUTTON: tuple[str, ...] = (
    '[data-testid="publish-now-button"]',
    'button[data-action="publish"]',
    'button:has-text("Publish now")',
)

# A signal the session is authenticated (any one present => logged in).
SIGNED_IN_MARKERS: tuple[str, ...] = (
    '[data-testid="editor"]',
    '[data-testid="headerWriteButton"]',
    'a[href="/new-story"]',
    'img[alt="Me"]',
)
