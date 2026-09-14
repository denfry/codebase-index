# Demo: Find, Trace, Predict on a real repository

This demo runs `codebase-index` against [Flask](https://github.com/pallets/flask)
(about 230 files, 18k lines of Python) at a pinned commit, so what you see is what
[EXPECTED_OUTPUT.md](EXPECTED_OUTPUT.md) shows. It takes under a minute and makes no
network requests after the clone.

```bash
pip install codebase-index
bash examples/demo/run_demo.sh            # or: pwsh examples/demo/run_demo.ps1
```

Pass a path to reuse an existing Flask checkout: `bash examples/demo/run_demo.sh ~/src/flask`.

## What it shows

| Step | Question | Command | What to look at |
|---|---|---|---|
| Find | Where is the session cookie signed and saved? | `codebase-index search "where is the session cookie signed and saved" --limit 5` | All three top hits are in `src/flask/sessions.py` with exact line ranges; tests are ranked below implementation ("generated/test demoted"). |
| Trace | Who calls `open_session`? | `codebase-index refs open_session` | Definitions vs calls, and the confidence column: two callers are marked `ambiguous` because several classes define `open_session`. The tool says so instead of guessing. |
| Trace | How does a request reach the view? | `codebase-index path wsgi_app dispatch_request` | A two-hop call chain `wsgi_app → full_dispatch_request → dispatch_request`, all in `app.py`. |
| Predict | What could break if `SecureCookieSessionInterface` changes? | `codebase-index impact SecureCookieSessionInterface --direction up --depth 2` | Upstream dependents at distance 1 and 2, with the edge kind (`call`, `extends`) that connects them. |
| Predict | What does my current diff affect? | edit `sessions.py`, then `codebase-index diff-impact` | Eight affected files ranked by distance from the changed file, each with the edge kind and `extracted` confidence. |
| Agent view | Same search as JSON | `codebase-index --json search ... --limit 3` | The packet an agent receives: freshness (`index`), `confidence`, ranked results with `snippet`, and `recommended_reads` with line ranges. |

## Things worth noticing

- **Confidence is part of the answer.** `refs` labels edges `exact` or `ambiguous`;
  `impact` and `diff-impact` carry `extracted` / `inferred` / `ambiguous`. An agent can
  distinguish "nothing references this" from "the graph is unsure".
- **The read plan is bounded.** `recommended_reads` entries longer than
  `retrieval.max_read_lines` (default 120) are capped at the definition head and marked
  `truncated: true` with `line_end_full`, so a 1,500-line class does not become a
  1,500-line read.
- **Tests are demoted, not hidden.** Search ranks `tests/test_basic.py` below
  `src/flask/sessions.py` for an implementation question, but still lists it.
- **Nothing left the machine.** The index is a SQLite file under
  `.claude/cache/codebase-index/`; `codebase-index doctor --strict` audits the
  network-off default.

## Try your own questions

```bash
cd .tmp-demo/flask
codebase-index explain "how are blueprints registered"
codebase-index describe dispatch_request
codebase-index architecture
codebase-index search "jsonify" --mode symbol
```

To run the same demo on your own repository, replace the clone step with `cd your-repo`
and keep the rest. For recording a GIF or video of this session, see
[docs/DEMO.md](../../docs/DEMO.md).
