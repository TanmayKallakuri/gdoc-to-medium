# Setup — one-time

This gets you from a fresh clone to a working `--dry-run`. Budget ~20 minutes.
You do this once; after that, publishing is just dragging a doc into a folder.

## 0. Prerequisites

- Python 3.13 on Windows.
- A Google account whose Drive will hold your posts.
- A way to post to Medium — either sign in through the browser (no token needed) or a
  Medium integration token from **before 2025-01-01** (Medium stopped issuing new ones).
  Most people use the browser path; see [section 4](#4-how-the-tool-reaches-medium).

## 1. Install

From the project root:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\pip install -e .
```

## 2. Google Cloud: a service account that can read your docs and move files

The tool authenticates as a **service account** — a robot Google identity — so it
never needs your password and can only touch folders you explicitly share with it.

1. Go to <https://console.cloud.google.com/> and create a project (or pick one).
2. **Enable two APIs** for that project (APIs & Services → Library): search for and
   enable **Google Docs API** and **Google Drive API**.
3. **Create the service account**: IAM & Admin → Service Accounts → Create. Give it
   any name (e.g. `gdoc-to-medium`). You don't need to grant it project roles.
4. **Make a key**: open the service account → Keys → Add Key → Create new key →
   **JSON**. A `.json` file downloads. This is a credential — treat it like a password.
5. Note the service account's **email** (it looks like
   `gdoc-to-medium@your-project.iam.gserviceaccount.com`). You'll share folders with it.

## 3. Drive: the four folders

In Google Drive, create this structure under one parent folder you own:

```
Posts/
  Ready to Publish/
  Published/
  Failed/
```

- Write each post as a normal Google Doc anywhere convenient.
- When a post is ready, **drag it into `Ready to Publish`** — that's the trigger.
- `Published` and `Failed` are where the tool moves docs after it runs. You don't
  put anything there yourself.

**Share access with the service account:** right-click the **`Posts`** parent
folder → Share → paste the service account email from step 2.5 → give it **Editor**
(it needs edit to move docs between folders). Sharing only this parent is the whole
security boundary — the service account can't see anything else in your Drive.

**Get each folder's id:** open a folder in the browser; the id is the last path
segment of the URL, e.g. `https://drive.google.com/drive/folders/THIS_PART`.
You need the ids for `Ready to Publish`, `Published`, and `Failed`.

## 4. How the tool reaches Medium

Pick one and set `backend` in the config (next step) to match.

**Browser (recommended, no token):** set `backend = "playwright"`. After the config
step you run a one-time sign-in. Full walkthrough: [PLAYWRIGHT_SETUP.md](PLAYWRIGHT_SETUP.md).
In short:

```powershell
.\.venv\Scripts\python -m playwright install chromium   # one-time browser download
.\.venv\Scripts\python -m gdoc_to_medium login          # sign in to Medium once
```

The login window stays open until you're signed in, then saves your session so future
runs post on their own. You don't need a token.

**Token (only if you already have one):** set `backend = "token"` and paste a pre-2025
integration token in the next step. To check if you have one: Medium → Settings →
**Security and apps → Integration tokens**. New tokens can't be created anymore, so if
that section is empty, use the browser path above.

## 5. Config file

Copy the example into your gitignored config directory and fill it in:

```powershell
# Preferred location (create it if needed):
#   %LOCALAPPDATA%\gdoc-to-medium\config.toml
# Fallback (gitignored): <project-root>\.secrets\config.toml
copy config.example.toml "$env:LOCALAPPDATA\gdoc-to-medium\config.toml"
```

Then edit that `config.toml`:

- `service_account_file` — path to the JSON key from step 2.4. Keep the key file in
  the same config directory and **never commit it**.
- `backend` — `"playwright"` for the browser path (no token) or `"token"` if you have one.
- `medium_token` — your pre-2025 token for `backend = "token"`; leave blank for `playwright`.
- `[folders]` — paste the three ids from step 3 into `ready`, `published`, `failed`.

Lock the config directory down to your user account only.

If you chose the browser path, run the one-time sign-in now (section 4):
`.\.venv\Scripts\python -m playwright install chromium` then
`.\.venv\Scripts\python -m gdoc_to_medium login`.

## 6. Verify with a dry run

Put one test doc in `Ready to Publish`, then:

```powershell
.\.venv\Scripts\python -m gdoc_to_medium --dry-run
```

This converts the doc and **prints the Medium markdown** — it makes no Medium calls
and moves no files. If the markdown looks right (headings, lists, links, images
shown as `PLACEHOLDER:` refs), you're ready to schedule it. See
[SCHEDULING.md](SCHEDULING.md).

If you see `Configuration error: ...`, the message names exactly what's missing.
