"""A fake Playwright page for unit-testing PlaywrightBackend with no real browser.

It records every interaction in `events` and resolves selectors against a configurable
`present` set (None => every selector matches). Mirrors only the slice of the Playwright
sync Page API the backend uses: goto/url/wait_for_selector/query_selector/evaluate/
click/set_input_files/keyboard/wait_for_timeout.
"""

from __future__ import annotations

SIGNIN_URL = "https://medium.com/m/signin?redirect=%2Fnew-story"


class FakeHandle:
    def __init__(self, page: "FakePage", selector: str) -> None:
        self._page = page
        self.selector = selector

    def click(self) -> None:
        self._page.events.append(("handle_click", self.selector))


class FakeKeyboard:
    def __init__(self, page: "FakePage") -> None:
        self._page = page

    def type(self, text: str) -> None:
        self._page.events.append(("type", text))

    def press(self, key: str) -> None:
        self._page.events.append(("press", key))


class FakePage:
    def __init__(
        self,
        *,
        url: str = "https://medium.com/new-story",
        present=None,
        draft_url: str | None = None,
        signed_in: bool = True,
    ) -> None:
        self._url = url
        # None => everything present; otherwise an explicit set of resolvable selectors.
        self.present = set(present) if present is not None else None
        self.draft_url = draft_url
        self.signed_in = signed_in
        self.events: list[tuple] = []
        self.keyboard = FakeKeyboard(self)

    @property
    def url(self) -> str:
        return self._url

    def goto(self, url: str, wait_until: str | None = None) -> None:
        self.events.append(("goto", url))
        if "new-story" in url and not self.signed_in:
            self._url = SIGNIN_URL
        elif "new-story" in url and self.draft_url:
            self._url = self.draft_url
        else:
            self._url = url

    def _matches(self, selector: str) -> bool:
        return True if self.present is None else selector in self.present

    def wait_for_selector(self, selector: str, timeout=None):
        parts = [s.strip() for s in selector.split(",")]
        if any(self._matches(p) for p in parts):
            return FakeHandle(self, selector)
        raise TimeoutError(f"no element for {selector!r}")

    def query_selector(self, selector: str):
        return FakeHandle(self, selector) if self._matches(selector) else None

    def evaluate(self, expression: str, arg=None):
        html = arg.get("html") if isinstance(arg, dict) else arg
        self.events.append(("paste", html))
        return True

    def click(self, selector: str, timeout=None) -> None:
        if self.present is not None and selector not in self.present:
            raise RuntimeError(f"cannot click {selector!r}")
        self.events.append(("click", selector))

    def set_input_files(self, selector: str, files) -> None:
        self.events.append(("set_input_files", selector, files))

    def wait_for_timeout(self, ms: int) -> None:
        self.events.append(("wait", ms))

    # convenience accessors for assertions
    def pastes(self) -> list[str]:
        return [e[1] for e in self.events if e[0] == "paste"]

    def typed(self) -> list[str]:
        return [e[1] for e in self.events if e[0] == "type"]

    def kinds(self) -> list[str]:
        return [e[0] for e in self.events]
