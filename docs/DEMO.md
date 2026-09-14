# Recording the demo

The repository ships a reproducible terminal demo, [examples/demo](../examples/demo/),
and a static SVG rendering of its output, `assets/demo-terminal.svg`, which the README
embeds. This page is the recipe for turning the same session into an animated GIF or a
short video without fabricating anything: every frame comes from the real script.

## What to record

`examples/demo/run_demo.sh` (or `run_demo.ps1`) against Flask at the pinned commit.
Steps 2, 3, 5 and 6 (search, refs, impact, diff-impact) are the ones worth showing;
the JSON step is for the README text, not for a recording.

Keep it under 45 seconds. Viewers stop at the first table.

## Prerequisites

```bash
pip install codebase-index
git clone https://github.com/pallets/flask.git .tmp-demo/flask
git -C .tmp-demo/flask checkout d318b683471101618febed18996405ad26462110
```

Use a terminal that is 100 columns wide and about 34 rows tall so the Markdown
tables do not wrap. A dark theme with a monospace font at 14-16 px reads best in a
README at 960 px width.

## Option A: VHS (recommended, fully scripted)

[VHS](https://github.com/charmbracelet/vhs) renders a `.tape` script to GIF/MP4/WebM
deterministically, so the recording is as reproducible as the demo itself.

`docs/demo.tape`:

```tape
Output assets/demo.gif
Set FontSize 15
Set Width 1200
Set Height 720
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Type "cd .tmp-demo/flask && codebase-index index"
Enter
Sleep 4s

Type 'codebase-index search "where is the session cookie signed and saved" --limit 3'
Enter
Sleep 5s

Type "codebase-index refs open_session"
Enter
Sleep 4s

Type "codebase-index impact SecureCookieSessionInterface --direction up --depth 2"
Enter
Sleep 5s

Type "codebase-index diff-impact"
Enter
Sleep 6s
```

Make the throwaway edit before recording (`run_demo.sh` shows the `sed` line) so
`diff-impact` has something to report, and revert it afterwards.

```bash
vhs docs/demo.tape
```

## Option B: asciinema + agg

```bash
asciinema rec --cols 100 --rows 34 demo.cast
bash examples/demo/run_demo.sh .tmp-demo/flask
exit
agg --theme monokai --font-size 15 demo.cast assets/demo.gif
```

Trim the `.cast` file to the interesting steps before converting; `agg` supports
`--idle-time-limit 2` to compress pauses.

## Option C: static SVG (what the README uses today)

`scripts/gen_terminal_svg.py` renders a captured transcript into an SVG "terminal
card". It has no dependencies and is what produced `assets/demo-terminal.svg`:

```bash
bash examples/demo/run_demo.sh .tmp-demo/flask > /tmp/demo.txt 2>&1
python scripts/gen_terminal_svg.py /tmp/demo.txt --out assets/demo-terminal.svg
```

The script strips ANSI colour, keeps the `$ command` lines highlighted, and cuts at
the first `--json` step so the card stays short.

## Checklist before publishing a recording

- The commit hash in the first frame matches `examples/demo/run_demo.sh`.
- No path from your home directory is visible (use a relative `.tmp-demo`).
- File size: GIF under 3 MB for the README; put the MP4 in the GitHub release, not
  in git.
- Update `examples/demo/EXPECTED_OUTPUT.md` if the codebase-index version changed and
  the output moved.
