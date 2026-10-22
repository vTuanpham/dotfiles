import json
import os
import re
import subprocess
import sys
import time

d = json.load(sys.stdin)

# Catppuccin Mocha truecolor palette
MAUVE, BLUE, TEAL, SKY = (203, 166, 247), (137, 180, 250), (148, 226, 213), (137, 220, 235)
GREEN, YELLOW, PEACH, RED = (166, 227, 161), (249, 226, 175), (250, 179, 135), (243, 139, 168)
PINK, LAVENDER, FLAMINGO = (245, 194, 231), (180, 190, 254), (242, 205, 205)
SUBTLE, TEXT, CRUST = (108, 112, 134), (205, 214, 244), (17, 17, 27)
SURFACE0, SURFACE1, SURFACE2 = (49, 50, 68), (69, 71, 90), (88, 91, 112)
FAMILY = {"opus": MAUVE, "sonnet": BLUE, "haiku": TEAL, "fable": PEACH}
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]
SPARK = "▁▂▃▄▅▆▇█"
RESET = "\033[0m"
NOW = time.time()

# Nerd Font glyphs built with chr(): editors and copy/paste drop private-use characters
PL_LEFT, PL_ARROW, PL_RIGHT = chr(0xE0B6), chr(0xE0B0), chr(0xE0B4)
ICON_MODEL, ICON_FOLDER, ICON_BRANCH, ICON_PR = chr(0xF09D1), chr(0xF07C), chr(0xE0A0), chr(0xF407)
ICON_WORKTREE, ICON_AGENT, ICON_THINK, ICON_BOLT = chr(0xF0645), chr(0xF06A9), chr(0xF0EB), chr(0xF0E7)
ICON_CLOCK, ICON_RESET, ICON_CHECK, ICON_CROSS = chr(0xF017), chr(0xF021), chr(0xF00C), chr(0xF00D)
ICON_SUN, ICON_MOON = chr(0xF05A8), chr(0xF0594)
CARD = SURFACE0  # body colour shared by both lines


def g(*keys):
    o = d
    for k in keys:
        o = o.get(k) if isinstance(o, dict) else None
    return o


def fg(rgb, s):
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{s}{RESET}"


def on(bg, fgc, s, bold=False):
    """Text on a background colour, without resetting the background mid-badge."""
    return (f"\033[{'1' if bold else '22'};38;2;{fgc[0]};{fgc[1]};{fgc[2]}m"
            f"\033[48;2;{bg[0]};{bg[1]};{bg[2]}m{s}")


def visible(s):
    return len(re.sub(r"\033\[[0-9;]*m", "", s))


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def ramp(t):
    """green -> yellow -> peach -> red as t goes 0..1."""
    stops = [GREEN, YELLOW, PEACH, RED]
    t = max(0.0, min(1.0, t))
    i = min(int(t * 3), 2)
    return mix(stops[i], stops[i + 1], t * 3 - i)


def bar(pct, width, bg=CARD):
    """A rounded track: gradient fill on a solid groove, so the end is always visible."""
    track = SURFACE2
    eighths = round(max(0, min(100, pct)) / 100 * width * 8)
    full, part = divmod(eighths, 8)
    colors = [ramp((i + 0.5) / width) for i in range(width)]
    out = on(bg, colors[0] if eighths else track, PL_LEFT)
    for i, c in enumerate(colors):
        if i < full:
            out += on(track, c, "█")
        elif i == full and part:
            out += on(track, c, " ▏▎▍▌▋▊▉"[part])
        else:
            out += on(track, track, " ")
    return out + on(bg, colors[-1] if full == width else track, PL_RIGHT)


def shimmer(text, base, bg):
    """A glint sweeping across the badge, animated by refreshInterval; the text stays dark."""
    pos = (NOW * 5) % (len(text) + 8) - 4
    return "".join(
        on(mix(bg, (255, 255, 255), max(0.0, 1 - abs(i - pos) / 2.5) * 0.55), base, ch, bold=True)
        for i, ch in enumerate(text)
    )


def human_tokens(n):
    return f"{n / 1e6:.1f}M".replace(".0M", "M") if n >= 1e6 else f"{n / 1e3:.0f}k"


def span(seconds):
    s = max(0, int(seconds))
    d_, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return f"{d_}d{h}h" if d_ else f"{h}h{m:02d}m" if h else f"{m}m{s % 60:02d}s" if m < 10 else f"{m}m"


def context_history(used):
    """Per-session context % samples (one per minute) for a sparkline."""
    sid = re.sub(r"[^\w-]", "", g("session_id") or "")
    if not sid:
        return []
    path = os.path.expanduser(f"~/.cache/claude-statusline/{sid}.json")
    try:
        with open(path) as f:
            hist = json.load(f)
    except (OSError, ValueError):
        hist = []
    if not hist or NOW - hist[-1][0] >= 60:
        hist.append([NOW, used])
    else:
        hist[-1][1] = used
    hist = hist[-24:]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}"
        with open(tmp, "w") as f:
            json.dump(hist, f)
        os.replace(tmp, path)
    except OSError:
        pass
    return [v for _, v in hist]


# ── line 1: powerline badges ──────────────────────────────────────────────
badges = []  # (bg, content)

model_id = g("model", "id") or ""
model = g("model", "display_name") or "Claude"
family = next((v for k, v in FAMILY.items() if k in (model_id + model).lower()), LAVENDER)
badges.append((family, on(family, CRUST, f" {ICON_MODEL} ") + shimmer(model, CRUST, family) + on(family, CRUST, " ")))

effort = g("effort", "level")
meter = ""
if effort:
    lvl = EFFORT_LEVELS.index(effort) + 1 if effort in EFFORT_LEVELS else 0
    meter = on(CARD, TEXT, " ") + "".join(
        on(CARD, ramp(i / 4) if i < lvl else SURFACE2, h) for i, h in enumerate("▁▂▄▆█")
    ) + on(CARD, ramp((lvl - 1) / 4) if lvl else TEXT, f" {effort} ", bold=True)
if g("thinking", "enabled"):
    meter += on(CARD, PINK, f"{ICON_THINK} ")
if g("fast_mode"):
    meter += on(CARD, YELLOW, f"{ICON_BOLT} ")
if meter:
    badges.append((CARD, meter))

cwd = g("workspace", "current_dir") or g("cwd") or ""
home = os.path.expanduser("~")
shown = "~" + cwd[len(home):] if cwd.startswith(home) else cwd
bits = shown.rstrip("/").split("/")
shown = "/".join(bits[-2:]) if len(bits) > 2 else shown
if shown:
    badges.append((BLUE, on(BLUE, CRUST, f" {ICON_FOLDER} {shown} ", bold=True)))

git = ""
try:
    st = subprocess.run(
        ["git", "-C", cwd or ".", "status", "--porcelain=v1", "-b", "--untracked-files=no"],
        capture_output=True, text=True, timeout=0.4,
    ).stdout.splitlines()
except Exception:
    st = []
if st and st[0].startswith("## "):
    head = st[0][3:]
    branch = head.split("...")[0].replace("No commits yet on ", "")
    git = on(TEAL, CRUST, f" {ICON_BRANCH} {branch}", bold=True)
    if m := re.search(r"ahead (\d+)", head):
        git += on(TEAL, CRUST, f" ⇡{m[1]}")
    if m := re.search(r"behind (\d+)", head):
        git += on(TEAL, CRUST, f" ⇣{m[1]}")
    if dirty := len(st) - 1:
        git += on(TEAL, (210, 15, 57), f" ●{dirty}", bold=True)
    git += on(TEAL, CRUST, " ")
if wt := g("worktree", "name") or g("workspace", "git_worktree"):
    git += on(TEAL, CRUST, f"{ICON_WORKTREE} {wt} ")
if pr := g("pr", "number"):
    mark = {"approved": f" {ICON_CHECK}", "changes_requested": f" {ICON_CROSS}"}.get(g("pr", "review_state"), "")
    git += on(TEAL, CRUST, f"{ICON_PR} #{pr}{mark} ", bold=True)
if git:
    badges.append((TEAL, git))

extras = ""
if agent := g("agent", "name"):
    extras += on(SURFACE1, PEACH, f" {ICON_AGENT} {agent} ")
if (style := g("output_style", "name")) and style != "default":
    extras += on(SURFACE1, LAVENDER, f" {style} ")
if vim := g("vim", "mode"):
    extras += on(SURFACE1, YELLOW, f" {vim} ", bold=True)
if extras:
    badges.append((SURFACE1, extras))

hour = time.localtime(NOW).tm_hour
clock = f" {ICON_SUN if 6 <= hour < 18 else ICON_MOON} {time.strftime('%H:%M', time.localtime(NOW))} "
badges.append((CARD, on(CARD, FLAMINGO, clock)))

# ── line 2: one continuous gauge pill on the card colour ─────────────────
divider = on(CARD, SURFACE2, " │ ")
gauges = []

used = g("context_window", "used_percentage")
if used is None and (left := g("context_window", "remaining_percentage")) is not None:
    used = 100 - left
if used is not None:
    size = g("context_window", "context_window_size") or 0
    seg = on(CARD, SUBTLE, " ctx ") + bar(used, 18) + on(CARD, ramp(used / 100), f" {used:.0f}%", bold=True)
    if size:
        seg += on(CARD, SUBTLE, f" {human_tokens(size * used / 100)}/{human_tokens(size)}")
    hist = context_history(used)
    lo, hi = min(hist, default=0), max(hist, default=0)
    if hi - lo >= 1:  # scaled to its own range; hidden while usage is flat
        seg += on(CARD, TEXT, " ") + "".join(
            on(CARD, ramp(v / 100), SPARK[round((v - lo) / (hi - lo) * 7)]) for v in hist
        )
    gauges.append(seg)

for key, label in (("five_hour", "5h"), ("seven_day", "7d"), ("spend_limit", "$")):
    pct = g("rate_limits", key, "used_percentage")
    if pct is None:
        continue
    seg = on(CARD, SUBTLE, f"{label} ") + bar(pct, 6) + on(CARD, ramp(pct / 100), f" {pct:.0f}%", bold=True)
    if resets := g("rate_limits", key, "resets_at"):
        seg += on(CARD, SUBTLE, f" {ICON_RESET} {span(resets - NOW)}")
    gauges.append(seg)

cost = g("cost", "total_cost_usd")
dur = g("cost", "total_duration_ms")
added, removed = g("cost", "total_lines_added"), g("cost", "total_lines_removed")
tail = []
if cost:
    rate = f" ({cost / (dur / 3.6e6):.2f}/h)" if dur and dur > 600_000 else ""
    tail.append(on(CARD, GREEN, f"${cost:.2f}") + on(CARD, SUBTLE, rate))
if dur:
    tail.append(on(CARD, SKY, f"{ICON_CLOCK} {span(dur / 1000)}"))
if added or removed:
    tail.append(on(CARD, GREEN, f"+{added or 0}") + on(CARD, RED, f" −{removed or 0}"))
if tail:
    gauges.append(on(CARD, SURFACE2, " · ").join(tail))

# ── assemble: two rounded pills joined by a tree connector ────────────────
# Half-round caps stacked in the same column pinch into a notch, so the gauge
# pill is indented under the connector and the two right ends are kept apart.
body1 = ""
for i, (bg, content) in enumerate(badges):
    nxt = badges[i + 1][0] if i + 1 < len(badges) else None
    body1 += content + (on(nxt, bg, PL_ARROW) if nxt else "")
body2 = divider.join(gauges) + on(CARD, TEXT, " ") if gauges else ""

if body2:
    lead1, lead2 = "╭─", "╰───"
    end1, end2 = len(lead1) + visible(body1), len(lead2) + visible(body2)
    if abs(end1 - end2) < 2:  # nudge the longer pill so the caps don't touch
        pad = on(CARD, TEXT, " " * (2 - abs(end1 - end2)))
        body1, body2 = (body1 + pad, body2) if end1 >= end2 else (body1, body2 + pad)
    print(fg(SURFACE2, lead1) + fg(family, PL_LEFT) + body1 + RESET + fg(CARD, PL_RIGHT))
    print(fg(SURFACE2, lead2) + fg(CARD, PL_LEFT) + body2 + RESET + fg(CARD, PL_RIGHT))
else:
    print(fg(family, PL_LEFT) + body1 + RESET + fg(CARD, PL_RIGHT))
