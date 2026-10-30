# systemd

[← Packages](../README.md#packages) · **Live + reference** · `./install.sh --apply links systemd`

The reference units and PATH snippet below are live links created by `install.sh`.
The tracker unit is a reference snapshot; install its live unit through the
tracker's own CLI.

| File | What |
| --- | --- |
| `.config/environment.d/999-local-bin.conf` | Puts `~/.local/bin` on PATH for `systemd --user` units |
| `.config/systemd/user/agent-models-reference.timer` | Daily staleness check; at most weekly a worker proposes a model-reference update |
| `.config/systemd/user/agent-models-reference.service` | Runs `model-guide stale`, then `model-guide refresh` |
| `.config/systemd/user/agent-lab-gc.timer` | Weekly cleanup of expired, explicitly retired experiments |
| `.config/systemd/user/agent-lab-gc.service` | Runs `agent-lab gc --apply`; active/kept/leased labs are protected |
| `.config/systemd/user/codex-reset-tracker.service` | Reference copy of the unit that the tracker writes with `service install` |

Copying files alone enables nothing. `./install.sh --apply systemd` enables the
reference and lab-cleanup timers. The [agent-lab CLI](../agent-lab/README.md#retirement-and-cleanup)
owns retirement and deletion checks; the timer adds no age-based cleanup of active work.

## Startup and timers

These pieces run without a terminal. WSL timers and services run while WSL is
running; the Windows tracker task can wake it.

| Where | What | Notes |
| --- | --- | --- |
| WSL `systemd --user` | `codex-reset-tracker.service` | The tracker is its own repo, [vTuanpham/codex-reset-tracker](https://github.com/vTuanpham/codex-reset-tracker); the unit here is a copy of what `service install` writes |
| WSL `systemd --user` | `agent-models-reference.timer` | Daily staleness check, weekly proposal; the units are linked by hand into `~/.config/systemd/user` (Stow would collide with the tracker's real unit file there) |
| WSL `systemd --user` | `agent-lab-gc.timer` | Weekly `agent-lab gc --apply`, using each retired lab's grace period |
| WSL `systemd` | `tailscaled`, plus the `tailscale serve` TCP forwards for the baton phone path | The forwards persist in Tailscale's own state |
| User crontab | hourly Codex model-catalog refresh | Documented in `codex/.codex/model-catalogs/README.md`; check with `crontab -l` |
| Windows Task Scheduler | `CodexResetTracker`: wakes WSL and starts the tracker at logon, unlock and wake | Created by the tracker's `windows-startup install --force`; runs `wsl.exe` through `conhost.exe --headless` so no console opens |
| Windows Task Scheduler | `cua-driver-serve`: starts the cua-driver daemon at logon | Registered by cua-driver. Its PowerShell flashes a window; wrap it once with the command below, and again if an update re-registers the task |

```powershell
$a = (Get-ScheduledTask -TaskName cua-driver-serve).Actions[0]
if ($a.Execute -notmatch 'conhost') {
  Set-ScheduledTask -TaskName cua-driver-serve -Action (New-ScheduledTaskAction `
    -Execute 'C:\Windows\System32\conhost.exe' -Argument ('--headless ' + $a.Execute + ' ' + $a.Arguments))
}
```

The Windows tasks and the crontab are machine-local and are not in this repository.
To restore the tracker on a new machine: clone its repo, run `./install.sh`,
`uv run codex-reset-tracker init-config`, `uv run codex-reset-tracker telegram`,
`uv run codex-reset-tracker service install`, then `windows-startup install --force`.
