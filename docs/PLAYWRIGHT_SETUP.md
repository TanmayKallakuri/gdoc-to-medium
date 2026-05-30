# Posting to Medium through the browser (no token)

Medium stopped giving out API tokens in 2025. If you don't already have one, this is
your path: the tool signs in to Medium as you, once, in a real browser window, and from
then on it posts your drafts through the Medium website using that saved sign-in. No
token, no API.

You do the sign-in once. After that it runs on its own.

## 1. One-time: install the browser and sign in

From the project root, with the project installed (`pip install -e .`):

```powershell
# Download the browser the tool drives (one time, ~150 MB):
.\.venv\Scripts\python -m playwright install chromium

# Open Medium and sign in:
.\.venv\Scripts\python -m gdoc_to_medium login
```

A browser window opens on Medium. Sign in however you normally do — Google, email link,
whatever. The window waits for you; the moment you're signed in it closes by itself and
saves the session. That's it.

In your `config.toml`, make sure:

```toml
backend = "playwright"
```

## 2. Check it worked

```powershell
.\.venv\Scripts\python -m gdoc_to_medium doctor
```

This opens your saved session and confirms you're signed in and that the editor is
reachable. If it says you're not signed in, run `login` again.

## 3. Use it

Nothing changes day to day: drag a doc into **Ready to Publish**, and the next run posts
it. Try a dry run first to see the converted post without touching Medium:

```powershell
.\.venv\Scripts\python -m gdoc_to_medium --dry-run
```

Then a real run (or let the scheduled task do it — see [SCHEDULING.md](SCHEDULING.md)):

```powershell
.\.venv\Scripts\python -m gdoc_to_medium
```

By default you get a **draft** — review it on Medium and publish yourself. Add a
`Status: publish` line at the top of the doc to publish immediately instead.

## Where your sign-in is stored

The saved session lives in a `medium-session` folder next to your `config.toml` (or
wherever you point `[playwright].session_dir`). **Treat it like a password** — anyone
with that folder can post as you. It's kept out of the repo. To sign out, delete the
folder and run `login` again.

## Good to know

- **It only runs while your PC is on.** Same as the rest of the tool — no catch-up, but
  nothing is lost; a doc sitting in Ready just waits for the next run.
- **Tags on drafts:** Medium only lets you set tags at publish time, so tags from your
  doc are applied when you publish immediately (`Status: publish`). For a plain draft,
  add tags yourself in the review step. (The token path can tag drafts; the browser path
  can't.)
- **Code blocks and images** come across, but the browser path is doing real
  point-and-click on Medium's site, so the very first time you publish for real, glance
  at the draft to confirm it looks right.
- **Watch it work:** set `headless = false` under `[playwright]` in your config to see
  the browser as it posts — handy if something looks off.

## If it stops working

Medium occasionally changes its website, which can move the buttons the tool clicks. If a
run starts leaving docs in **Ready** with a "Medium's UI may have changed" note:

1. Run `doctor` — it reports which parts of the editor it can still find.
2. Your docs are safe in Ready the whole time; nothing is lost or half-posted.
3. The clickable targets live in one file (`src/gdoc_to_medium/medium/selectors.py`) with
   alternatives listed for each — updating them there fixes it without touching the rest.

If a run says your **session expired**, just run `login` again.
