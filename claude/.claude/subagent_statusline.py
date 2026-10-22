import json
import re
import sys
import time

d = json.load(sys.stdin)

# Same Catppuccin palette and pill style as statusline.py
MAUVE, BLUE, TEAL = (203, 166, 247), (137, 180, 250), (148, 226, 213)
GREEN, YELLOW, PEACH, RED = (166, 227, 161), (249, 226, 175), (250, 179, 135), (243, 139, 168)
LAVENDER, SUBTLE, TEXT, CRUST = (180, 190, 254), (108, 112, 134), (205, 214, 244), (17, 17, 27)
SURFACE0, SURFACE1, SURFACE2 = (49, 50, 68), (69, 71, 90), (88, 91, 112)
CARD = SURFACE0
FAMILY = {"Opus": MAUVE, "Sonnet": BLUE, "Haiku": TEAL, "Fable": PEACH}
EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"]
SPARK = "▁▂▃▄▅▆▇█"
RESET = "\033[0m"
NOW = time.time()

# Nerd Font glyphs built with chr(): editors and copy/paste drop private-use characters
PL_LEFT, PL_ARROW, PL_RIGHT = chr(0xE0B6), chr(0xE0B0), chr(0xE0B4)
SPINNER = [chr(c) for c in range(0xF0A9E, 0xF0AA6)]  # circle slices 1-8
ICON_CLOCK, ICON_PENDING = chr(0xF017), chr(0xF110)
STATUS = {"completed": chr(0xF00C), "failed": chr(0xF00D), "killed": chr(0xF04D)}


def fg(rgb, s):
    return f"\033[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{s}{RESET}"


def on(bg, fgc, s, bold=False):
    return (f"\033[{'1' if bold else '22'};38;2;{fgc[0]};{fgc[1]};{fgc[2]}m"
            f"\033[48;2;{bg[0]};{bg[1]};{bg[2]}m{s}")


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def ramp(t):
    stops = [GREEN, YELLOW, PEACH, RED]
    t = max(0.0, min(1.0, t))
    i = min(int(t * 3), 2)
    return mix(stops[i], stops[i + 1], t * 3 - i)


def model_name(model_id):
    m = re.match(r"claude-([a-z]+)-(\d+)-(\d+)", model_id or "")
    return f"{m[1].title()} {m[2]}.{m[3]}" if m else (model_id or "…")


def span(seconds):
    s = max(0, int(seconds))
    return f"{s // 3600}h{s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m{s % 60:02d}s"


for t in d.get("tasks", []):
    status = t.get("status")
    running = status == "running"
    model = model_name(t.get("model"))
    badge_bg = FAMILY.get(model.split()[0], LAVENDER)
    if not running:  # finished rows fade toward the card colour
        badge_bg = mix(badge_bg, CARD, 0.55)
    icon = SPINNER[int(NOW * 8) % len(SPINNER)] if running else STATUS.get(status, ICON_PENDING)
    icon_color = RED if status in ("failed", "killed") else CRUST
    row = fg(badge_bg, PL_LEFT) + on(badge_bg, icon_color, f"{icon} ", bold=True)
    row += on(badge_bg, CRUST, f"{model} ", bold=True) + on(CARD, badge_bg, PL_ARROW)

    body = []
    effort = t.get("effort")
    if effort in EFFORT_LEVELS:
        lvl = EFFORT_LEVELS.index(effort) + 1
        body.append("".join(on(CARD, ramp(i / 4) if i < lvl else SURFACE2, h) for i, h in enumerate("▁▂▄▆█"))
                    + on(CARD, ramp((lvl - 1) / 4), f" {effort}", bold=True))
    elif effort is not None:
        body.append(on(CARD, TEXT, f"{effort} tok"))
    else:
        body.append(on(CARD, SUBTLE, "default effort"))

    tokens, window = t.get("tokenCount", 0), t.get("contextWindowSize")
    if window:
        pct = min(100, tokens / window * 100)
        seg = on(CARD, ramp(pct / 100), f"{tokens / 1000:.0f}k {pct:.0f}%")
        samples = t.get("tokenSamples") or []
        if len(samples) > 1:
            lo, hi = min(samples), max(samples)
            seg += on(CARD, TEXT, " ") + "".join(
                on(CARD, ramp(s / window), SPARK[int((s - lo) / (hi - lo) * 7) if hi > lo else 0]) for s in samples
            )
        body.append(seg)
    if start := t.get("startTime"):
        body.append(on(CARD, SUBTLE, f"{ICON_CLOCK} {span(NOW - start / 1000)}"))
    if label := t.get("label") or t.get("description"):
        body.append(on(CARD, TEXT if running else SUBTLE, label))

    row += on(CARD, TEXT, " ") + on(CARD, SURFACE2, " │ ").join(body) + on(CARD, TEXT, " ")
    row += RESET + fg(CARD, PL_RIGHT)
    print(json.dumps({"id": t["id"], "content": row}))
