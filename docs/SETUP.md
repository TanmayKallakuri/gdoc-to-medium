# Setup — one-time

This gets you from a fresh clone to a working `--dry-run`. Budget ~20 minutes.
You do this once; after that, publishing is just dragging a doc into a folder.

## 0. Prerequisites

- Python 3.13 on Windows.
- A Google account whose Drive will hold your posts.
- (For live posting) a Medium integration token issued **before 2025-01-01** —
  Medium stopped issuing new ones. If you don't have one, you can still use
  everything except the final post step; see [the token note](#4-medium-token).

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

## 4. Medium token

If you have a pre-2025 integration token, you'll paste it into the config in the
next step. To check whether you can get one: Medium → Settings → **Security and
apps → Integration tokens**. If that section exists, generate a token there. If
it's gone, leave the token blank and set `backend = "playwright"` (the browser
fallback — note that path isn't built yet; it's the next milestone if you need it).

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
- `medium_token` — your token (or leave blank for the Playwright fallback).
- `backend` — `"token"` (default) or `"playwright"`.
- `[folders]` — paste the three ids from step 3 into `ready`, `published`, `failed`.

Lock the config directory down to your user account only.

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
