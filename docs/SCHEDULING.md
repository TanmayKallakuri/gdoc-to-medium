# Scheduling — run it automatically

Once `--dry-run` looks right ([SETUP.md](SETUP.md)), schedule the publisher so it
checks the `Ready to Publish` folder on its own.

## Register the task

From the project root, in PowerShell:

```powershell
.\scripts\register_task.ps1
```

That registers a Windows scheduled task named `gdoc-to-medium` that runs every
5 minutes. To use a different interval:

```powershell
.\scripts\register_task.ps1 -IntervalMinutes 10
```

## What it does

- Runs `python -m gdoc_to_medium` (no `--dry-run`) every N minutes via
  `scripts\run.cmd`, which cd's to the project root and appends all output to
  `logs\run.log` (gitignored).
- Runs **only while the PC is on**. It won't wake the machine and won't "catch up"
  on missed runs — folder state is the source of truth, so a doc left in
  `Ready to Publish` is simply picked up on the next run after the PC is awake.
- Each run: any doc in `Ready to Publish` is converted, posted to Medium as a
  draft, then moved to `Published` (with the draft URL written back into the doc).
  A permanent failure moves the doc to `Failed` with the reason noted; a transient
  failure leaves it in `Ready` to retry next time.

## Manage it

```powershell
Get-ScheduledTask -TaskName 'gdoc-to-medium'      # confirm it's registered
Start-ScheduledTask -TaskName 'gdoc-to-medium'    # run once right now
Get-Content .\logs\run.log -Tail 20               # see recent output
schtasks /Delete /TN 'gdoc-to-medium' /F          # remove it
```

## Latency

Expect up to one interval (≈5 min by default) between dragging a doc into
`Ready to Publish` and the draft appearing in Medium.
