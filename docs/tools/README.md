# docs/tools

[← Dotfiles](../../README.md) · **Repository tooling** · nothing here is installed

Generators for README visuals. They draw the real things (the Wake renderer, prompts,
Agent Baton page server and diagram sources) with demo values, so a
README capture never needs a screenshot of a live session and never shows personal data.

| Script | Makes | Source of the pixels |
| --- | --- | --- |
| `readme_gifs.py` | `hero.gif`, `wake-landscapes.gif`, `wake-dock.gif` | Wake's `dev/showcase.ts` and `dev/dock.ts` frames; `statusline.py`; `../hero.html` |
| `baton_gif.py` | `baton.gif` | The real Baton page server, screenshotted by Chrome; `baton-toast.png` is a real capture of its toast |
| `flow_gifs.py` | one GIF per diagram in `flows/*.svg` | The SVG itself, rendered by Chrome with a packet on every arrow |
| `model_effort.py` | `flows/model-effort.svg` | Exact model/setting rows in Model Guide's public benchmark snapshot, with its retrieval timestamp; no account data |
| `starship_prompt.py` | `../../starship/docs/prompt.svg` | `starship.toml` (palette, format, symbols) drawn with the terminal's Nerd Font; `uv run --with pillow python docs/tools/starship_prompt.py OUT.svg` |
| `portlink_preview.py` | `../../portlink/docs/preview.svg` | Portlink's CLI output and a demo QR, drawn with the terminal's Propo face; `uv run --project portlink --with pillow python docs/tools/portlink_preview.py` |
| `statusline.py` | (library) | Runs `claude/.claude/statusline.py` with demo input and a fake clock, then draws its ANSI output |

Run them from the repository root with `README_WORK=<scratch dir> uv run --with pillow python docs/tools/<script>`
(`baton_gif.py` from `agent-baton/`, with `AGENT_BATON_HOME` set to a short path). They need `bun`,
`google-chrome`, `gifsicle` and a Nerd Font Mono (`NERD_FONT_DIR`, see `statusline.py`).
`starship_prompt.py` needs only Pillow, the terminal's Propo face and Windows' Segoe UI Historic and Symbol
(see its docstring).

Every layer is scaled by a whole number and text is drawn at its native size, so the pixels stay sharp. Frames
share one palette and `gifsicle -O3` stores only what changes, which keeps each file small.
Edit a diagram in `flows/`, then regenerate its GIF.

Overview, selection, account, Lab, resource and Codex notification diagrams use the
same renderer; pass their SVG stems to regenerate only the changed assets. Claude
Wake captures are generated separately.

After a benchmark refresh, regenerate the effort chart from the actual snapshot:
`uv run --project agent-models python docs/tools/model_effort.py --model 'GPT-6.1 Sol'`.
The generator discovers measured settings and plot ranges, includes all measured
isolated runs for that model and records the snapshot timestamp. Missing cost
cannot become a plotted point; missing response time stays unknown. Review the
rendered chart before publishing it.
