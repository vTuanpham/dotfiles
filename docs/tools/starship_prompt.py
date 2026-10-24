"""starship/docs/prompt.svg: the shared Starship prompt, drawn with the terminal's own font.

The palette, separators, symbols and format come from starship/.config/starship.toml; values the config
leaves open (user, directory, branch, version, time) are demo data. The prompts are PNG insets in the SVG
so they use the real Nerd Font glyphs, at 12 pt (16 px) on a 3x raster.

    uv run --with pillow python docs/tools/starship_prompt.py OUT.svg [--font FILE]

Fonts are found by statusline.font(): the terminal face (default SauceCodeProNerdFontPropo-SemiBold.ttf)
from NERD_FONT_DIR or the Windows user fonts folder; a character it lacks (the Zsh indicator's Old Turkic
letter, the ahead arrow) uses Segoe UI Historic or Symbol from C:\\Windows\\Fonts in this preview.
A character no font has stops the run.
"""

import argparse
import base64
import io
import re
import sys
import tomllib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from statusline import font  # noqa: E402

CONFIG = Path(__file__).resolve().parents[2] / "starship/.config/starship.toml"
TERM = "#282c34"  # the terminal background the prompt sits on
SCALE = 3  # raster pixels per SVG pixel
SIZE = 16 * SCALE  # 12 pt at 96 dpi
FALLBACKS = ("seguihis.ttf", "seguisym.ttf")
AHEAD = "\u21e1"  # Starship's default ahead symbol; the config does not override it
X, IMAGE_Y = 40, (170, 274)  # inset position in the SVG


def ink(face, char):
    canvas = Image.new("L", (SIZE * 3, SIZE * 3))
    ImageDraw.Draw(canvas).text((SIZE, SIZE), char, font=face, fill=255)
    return canvas.tobytes()


class Faces:
    def __init__(self, main):
        self.faces = [ImageFont.truetype(font(False, name), SIZE) for name in (main, *FALLBACKS)]
        self.absent = [ink(face, "\U0010fffe") for face in self.faces]  # what a missing glyph draws
        self.ascent, descent = self.faces[0].getmetrics()
        self.height = self.ascent + descent

    def pick(self, char):
        for face, absent in zip(self.faces, self.absent):
            if char.isspace() or ink(face, char) != absent:
                return face
        sys.exit(f"No font has U+{ord(char):04X}")

    def runs(self, text):
        """(face, text) runs, one face per run."""
        out = []
        for char in text:
            face = self.pick(char)
            if out and out[-1][0] is face:
                out[-1][1] += char
            else:
                out.append([face, char])
        return out


def style(spec):
    """'bold fg:color_a bg:color_b' or a bare 'color_a' (a foreground) -> {'fg': ..., 'bg': ...}"""
    result = {}
    for token in spec.split():
        if token == "bold":
            continue
        kind, _, name = token.rpartition(":")
        result[kind or "fg"] = name
    return result


def load():
    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    palette = config["palettes"][config["palette"]]
    marks = [(text, style(spec))
             for text, spec in re.findall(r"\[([^\[\]$]+)\]\(([^)]*)\)", config["format"])]
    cap, *seps, end = marks  # the rounded left cap, six separators, the closing cap
    assert len(seps) == 6, "starship.toml format changed: expected six separators"
    def symbol(key):
        match = re.fullmatch(r"\[(.)\]\((.*)\)", config["character"][key])
        assert match is not None, "character format changed"
        return match.group(1), style(match.group(2))["fg"]

    return {
        "color": palette,
        "cap": cap,
        "seps": seps,
        "end": end,
        "os": config["os"]["symbols"]["Ubuntu"],
        "zsh": config["shell"]["zsh_indicator"],
        "branch": config["git_branch"]["symbol"],
        "node": config["nodejs"]["symbol"],
        "clock": re.search(r"\[\[ (\S) \$time", config["time"]["format"]).group(1),
        "elided": config["directory"]["truncation_symbol"],
        "ok": symbol("success_symbol"),
        "fail": symbol("error_symbol"),
    }


def scene(cfg, directory, git, language, clock, status):
    """Groups of (cell text, fg, bg) in format order, named for the labels above them."""
    c, seps = cfg["color"], cfg["seps"]
    fg0 = c["color_fg0"]
    # os, shell, dir, git, language, environment, time
    bgs = [c[cfg["cap"][1]["fg"]]] + [c[sep[1]["bg"]] for sep in seps]

    def sep(i):
        return (seps[i][0], c[seps[i][1]["fg"]], c[seps[i][1]["bg"]])

    def cell(text, bg):
        return (text, fg0, bg)

    groups = [
        ("os · user", [(cfg["cap"][0], bgs[0], TERM), (cfg["os"] + " dev ", fg0, bgs[0])]),
        ("shell", [sep(0), cell(f" {cfg['zsh']} ", bgs[1])]),
        ("directory", [sep(1), cell(f" {directory} ", bgs[2])]),
        ("git branch · status",
         [sep(2)] + ([cell(f" {cfg['branch']} main !?{AHEAD} ", bgs[3])] if git else [])),
        ("language", [sep(3)] + ([cell(f" {cfg['node']} v20.0.0 ", bgs[4])] if language else [])),
        ("", [sep(4), sep(5)]),
        ("time", [cell(f" {cfg['clock']} {clock} ", bgs[6]), (cfg["end"][0], bgs[6], TERM)]),
    ]
    glyph, color = cfg[status]
    return groups, (glyph + " ", c[color])


def draw(faces, groups, chevron):
    """The prompt and its second line as an image, plus each group's centre in SVG pixels."""
    h = faces.height
    cells = [(text, fg, bg, i == 0 and j == 0)
             for i, (_, row) in enumerate(groups) for j, (text, fg, bg) in enumerate(row)]
    widths = [sum(round(face.getlength(run)) for face, run in faces.runs(text)) - (2 if cap else 0)
              for text, _, _, cap in cells]
    image = Image.new("RGB", (sum(widths) + 2, 2 * h), TERM)
    pen = ImageDraw.Draw(image)
    x, centres, k = 0, {}, 0
    for name, row in groups:
        start = x
        for _ in row:
            text, fg, bg, cap = cells[k]
            pen.rectangle([x, 0, x + widths[k] + (2 if cap else 0) - 1, h - 1], fill=bg)
            for face, run in faces.runs(text):
                pen.text((x, faces.ascent), run, font=face, fill=fg, anchor="ls")
                x += round(face.getlength(run))
            x += -2 if cap else 0
            k += 1
        centres[name] = (start + x) / 2 / SCALE
    glyph, color = chevron
    pen.text((0, h + faces.ascent), glyph, font=faces.pick(glyph[0]), fill=color, anchor="ls")
    return image, centres


def inset(image):
    out = io.BytesIO()
    image.save(out, "PNG", optimize=True)
    return base64.b64encode(out.getvalue()).decode()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("output", type=Path)
    parser.add_argument("--font", default="SauceCodeProNerdFontPropo-SemiBold.ttf")
    args = parser.parse_args()
    faces, cfg = Faces(args.font), load()
    a, centres = draw(faces, *scene(cfg, "~/projects/api", True, True, "14:32", "ok"))
    b, _ = draw(faces, *scene(cfg, cfg["elided"] + "work/api/src", False, False, "09:05", "fail"))
    assert max(a.width, b.width) / SCALE <= 880, "prompt wider than the panel"
    ticks = {name: round(X + at) for name, at in centres.items() if name}
    labels = "\n".join(f'      <text x="{x}" y="156">{name}</text>' for name, x in ticks.items())
    marks = "".join(f"M{x} 161V167" for x in ticks.values())
    images = "\n".join(
        f'    <image x="{X}" y="{y}" width="{img.width / SCALE:.2f}" height="{img.height / SCALE:.2f}" '
        f'xlink:href="data:image/png;base64,{inset(img)}"/>'
        for img, y in ((a, IMAGE_Y[0]), (b, IMAGE_Y[1]))
    )
    first, second = images.split("\n", 1)
    args.output.write_text(
        f"""<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="960" height="368" viewBox="0 0 960 368" role="img" aria-labelledby="title desc">
  <title id="title">The shared Starship prompt</title>
  <desc id="desc">Two prompts in the Gruvbox Dark palette, set in the terminal's Nerd Font.
    The first shows operating system and user, shell, directory, Git branch and status,
    Node.js version and time after a successful command. The second shows a failed command
    in a folder without a repository or language: the separators stay and leave thin color bands.</desc>
  <rect width="960" height="368" fill="#faf9f6"/>
  <g font-family="Arial, Helvetica, sans-serif" fill="#263733">
    <text x="40" y="38" font-size="11" letter-spacing="2.4" fill="#68766f">STARSHIP</text>
    <text x="40" y="72" font-family="Georgia, serif"
          font-size="26">One prompt for Zsh, Bash and the Claude status line</text>

    <rect x="24" y="96" width="912" height="248" rx="14" fill="{TERM}"/>

    <text x="40" y="126" font-size="13"
          fill="#a89984">Git repository with a Node.js project, last command succeeded</text>
    <g font-size="11.5" fill="#a89984" text-anchor="middle">
{labels}
    </g>
    <path d="{marks}" stroke="#665c54" stroke-width="1.5"/>
{first}

    <path d="M24 236H936" stroke="#32302f"/>

    <text x="40" y="262" font-size="13"
          fill="#a89984">Folder with no repository or language, last command failed</text>
{second}
  </g>
</svg>
""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
