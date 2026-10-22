"""images/<name>.gif for each diagram in tools/flows/*.svg: a packet travels every arrow, one after another,
and the dashed connectors march. Frames are the SVG itself rendered by google-chrome, so text stays vector-sharp.

    README_WORK=<scratch dir> uv run --with pillow python docs/tools/flow_gifs.py [name ...]
"""

import re
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import readme_gifs as gifs  # noqa: E402

FLOWS = Path(__file__).parent / "flows"
FRAMES = 30
COLORS = ["#23786f", "#a35e43", "#65598a", "#506b90"]
ARROW = re.compile(r'<path d="(M[^"]+)"([^>]*?marker-(?:end|start)="url\(#arrow\)"[^>]*?)/>')
DASH = re.compile(r'stroke-dasharray="3 5"')


def ease(x):
    return x * x * (3 - 2 * x)


def frame_svg(source, t):
    """The diagram at time t in [0, 1): packets in flight along each arrow, dashed lines shifted."""
    arrows = list(ARROW.finditer(source))
    packets = []
    for i, match in enumerate(arrows):
        local = (t - i * 0.09) % 1.0  # arrows fire in document order
        if local > 0.5:
            continue
        run = ease(local / 0.5)
        if "marker-start" in match.group(2) and i % 2:  # a two-way arrow alternates direction
            run = 1 - run
        color = COLORS[i % len(COLORS)]
        d = match.group(1)
        style = f"offset-path:path('{d}');offset-distance:{run * 100:.2f}%;offset-rotate:0deg"
        packets.append(f'<circle r="9" fill="{color}" opacity=".16" style="{style}"/><circle r="4.2" fill="{color}" style="{style}"/>')
    out = DASH.sub(f'stroke-dasharray="3 5" stroke-dashoffset="{-8 * t:.2f}"', source)
    return out.replace("</g>\n</svg>", "".join(packets) + "</g>\n</svg>")


def render(path):
    source = path.read_text(encoding="utf-8")
    height = int(re.search(r'height="(\d+)"', source).group(1))
    frames = []
    for k in range(FRAMES):
        svg = gifs.WORK / f"{path.stem}-{k}.svg"
        svg.write_text(frame_svg(source, k / FRAMES), encoding="utf-8")
        png = gifs.WORK / f"{path.stem}-{k}.png"
        gifs.run(
            "google-chrome", "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
            "--force-device-scale-factor=1", f"--window-size=1040,{height}", f"--screenshot={png}", f"file://{svg}",
        )
        frames.append(Image.open(png).convert("RGB"))
    gifs.save_gif(frames, gifs.IMAGES / f"{path.stem}.gif", 70)


if __name__ == "__main__":
    gifs.WORK.mkdir(parents=True, exist_ok=True)
    wanted = sys.argv[1:]
    for svg in sorted(FLOWS.glob("*.svg")):
        if not wanted or svg.stem in wanted:
            render(svg)
