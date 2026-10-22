# docs/tools

[← Dotfiles](../../README.md) · **Repository tooling** · nothing here is installed

Generators for the animated images in `docs/images/`. They draw the real things (the Wake renderer, the
Claude Code status line, the Agent Baton page server and the diagram sources) with demo values, so a
README capture never needs a screenshot of a live session and never shows personal data.

| Script | Makes | Source of the pixels |
| --- | --- | --- |
| `readme_gifs.py` | `hero.gif`, `wake-landscapes.gif`, `wake-dock.gif` | Wake's `dev/showcase.ts` and `dev/dock.ts` frames; `statusline.py`; `../hero.html` |
| `baton_gif.py` | `baton.gif` | The real Baton page server, screenshotted by Chrome; `baton-toast.png` is a real capture of its toast |
| `flow_gifs.py` | one GIF per diagram in `flows/*.svg` | The SVG itself, rendered by Chrome with a packet on every arrow |
| `statusline.py` | (library) | Runs `claude/.claude/statusline.py` with demo input and a fake clock, then draws its ANSI output |

Run them from the repository root with `README_WORK=<scratch dir> uv run --with pillow python docs/tools/<script>`
(`baton_gif.py` from `agent-baton/`, with `AGENT_BATON_HOME` set to a short path). They need `bun`,
`google-chrome`, `gifsicle` and a Nerd Font Mono (`NERD_FONT_DIR`, see `statusline.py`).

Every layer is scaled by a whole number and text is drawn at its native size, so the pixels stay sharp. Frames
share one palette and `gifsicle -O3` stores only what changes, which keeps each file small.
Edit a diagram in `flows/`, then regenerate its GIF.
