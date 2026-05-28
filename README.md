# gdoc-to-medium

Write your post in Google Docs, drag the finished doc into a folder, and a Medium draft
shows up for you to review and publish. No copy-pasting, no reformatting, no re-uploading
images by hand.

You stay in control of the final step: by default the tool creates a **draft**, not a live
post. You read it over in Medium and hit publish yourself.

## What it does

- You write in Google Docs like normal. Nothing happens while you write.
- When a post is ready, you drag the doc into a `Ready to Publish` folder.
- A job on your machine checks that folder on a schedule, converts the doc to Medium
  formatting, uploads any images, and creates a **Medium draft**.
- The doc moves to a `Published` folder, and the draft's review link is written back into
  the doc so you can find it.

The folders are the whole system. A doc sitting in `Ready to Publish` is pending; once it's
in `Published` it's done; if something went permanently wrong it lands in `Failed` with the
reason noted at the top of the doc. There's no database to manage.

### Controlling the post

- **Title** comes from the doc's filename.
- **Tags** are optional: put a line like `Tags: python, automation, medium` at the top of
  the doc. Up to 5 tags; extras are ignored. The line is stripped out of the post.
- **Publish vs. draft:** by default you get a draft. To skip the review step and post live
  immediately, add a `Status: publish` line at the top. Anything else (or no line) stays a
  draft.

## What you need

- A Google account whose Drive holds your posts, and a service account that can read and
  move docs in one folder you share with it (setup walks you through this).
- **A Medium integration token issued before January 2025.** This is the one real catch:
  Medium stopped handing out new API tokens at the start of 2025, so if you don't already
  have one, you currently can't get one through Medium's settings. A browser-automation
  fallback that posts through the Medium web UI is planned for people without a token, but
  it isn't built yet. If you have an older token, you're set.
- Windows with Python 3.13.

## How it runs

It runs on your own Windows machine through Task Scheduler, checking the `Ready to Publish`
folder every few minutes. Because the folders hold the state, it only needs to run while
your PC is on — there's no catch-up logic and nothing is lost. Expect up to one polling
interval (about 5 minutes by default) between dropping a doc in and the draft appearing.

Before you ever go live, you can run a dry run that converts a doc and prints the resulting
Medium formatting without posting anything or moving any files — so you can see exactly what
the post will look like first.

## What it converts

Headings, bold and italic, bulleted and numbered lists, links, inline code, code blocks, and
inline images (downloaded from the doc and re-uploaded to Medium).

### What it does not handle

These pass through as plain text or are dropped, not converted — so there are no surprises:

- Tables
- Footnotes
- Google Docs comments and suggestions

Code-block detection uses the doc's monospace font as the signal, so format code in a
monospace font in Docs for it to come out as a code block.

## Setup

One-time setup takes about 20 minutes: create the service account, make the four folders,
share the parent folder, drop in your config, and confirm with a dry run.

- [docs/SETUP.md](docs/SETUP.md) — get from a fresh clone to a working dry run.
- [docs/SCHEDULING.md](docs/SCHEDULING.md) — register the scheduled task so it runs on its own.

The full design, including the folder model and the known limitations above, is in
[docs/superpowers/specs/2026-05-28-gdoc-to-medium-autopublisher-design.md](docs/superpowers/specs/2026-05-28-gdoc-to-medium-autopublisher-design.md).
