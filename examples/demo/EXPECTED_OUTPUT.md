# Expected output

Captured by running `examples/demo/run_demo.sh` against
[pallets/flask](https://github.com/pallets/flask) at commit `d318b683` with
codebase-index 1.9.0 on 2026-09-04. Timestamps and ordering of equal-score rows
may differ on your machine; file paths, line ranges and edge kinds should not.

```text
$ codebase-index index
Indexed 230 files (0 pruned).
  parse failures: 0; tree-sitter files with 0 symbols: 17

$ codebase-index search where is the session cookie signed and saved --limit 5
**Query:** where is the session cookie signed and saved  
**Intent:** `locate_impl` · **Confidence:** medium

| # | Path | Lines | Reason |
|---|------|-------|--------|
| 1 | `src/flask/sessions.py` | 24-54 | in src/flask/ · 2 callers · source prior +0.08 |
| 2 | `src/flask/sessions.py` | 284-385 | in src/flask/ · 2 callers · source prior +0.08 |
| 3 | `src/flask/sessions.py` | 57-80 | in src/flask/ · 1 callers · source prior +0.08 |
| 4 | `tests/test_basic.py` | 542-600 | source prior -0.06 · generated/test demoted |
| 5 | `tests/test_reqctx.py` | 201-249 | source prior -0.06 · generated/test demoted |

`src/flask/sessions.py:24-54`
```
class SessionMixin(MutableMapping[str, t.Any]):
```
`src/flask/sessions.py:284-385`
```
class SecureCookieSessionInterface(SessionInterface):
```
`src/flask/sessions.py:57-80`
```
class SecureCookieSession(CallbackDict[str, t.Any], SessionMixin):
```
`tests/test_basic.py:542-600`
```
def test_session_vary_cookie(app, client):
```
`tests/test_reqctx.py:201-249`
```
def test_session_dynamic_cookie_name():
```

**Recommended reads:**
- `src/flask/sessions.py:24-54`
- `src/flask/sessions.py:284-385`
- `src/flask/sessions.py:57-80`
- `tests/test_basic.py:542-600`
- `tests/test_reqctx.py:201-249`

$ codebase-index refs open_session
**query:** open_session  |  **index:** fresh

| kind | path | line | confidence |
|------|------|------|------------|
| call | `src/flask/ctx.py` | 388 | ? ambiguous |
| definition | `src/flask/sessions.py` | 249 | exact |
| definition | `src/flask/sessions.py` | 323 | exact |
| call | `src/flask/testing.py` | 165 | ? ambiguous |
| definition | `tests/test_reqctx.py` | 182 | exact |
| definition | `tests/test_session_interface.py` | 16 | exact |


$ codebase-index path wsgi_app dispatch_request
**path:** `wsgi_app` → `dispatch_request`  ·  **2 hop(s)**

`wsgi_app` (src/flask/app.py)
  → _call_ →
`full_dispatch_request` (src/flask/app.py)
  → _call_ →
`dispatch_request` (src/flask/app.py)


$ codebase-index impact SecureCookieSessionInterface --direction up --depth 2
**impact:** `SecureCookieSessionInterface`  ·  **direction:** up  ·  **depth:** 2  ·  **affected files:** 2

| dist | via | kind | node | location |
|------|-----|------|------|----------|
| 1 | call | symbol | `Flask` | `src/flask/app.py:110` |
| 1 | extends | symbol | `PathAwareSessionInterface` | `tests/test_reqctx.py:204` |
| 2 | call | symbol | `CustomFlask` | `tests/test_reqctx.py:211` |


$ codebase-index diff-impact
**diff impact:** `HEAD` → working tree  
**direction:** `up` · **depth:** 2

**changed files (1):**
- `src/flask/sessions.py`

**affected files (8):**
| distance | path | changed by | edge | confidence |
|---:|---|---|---|---|
| 1 | `src/flask/app.py` | `src/flask/sessions.py` | call | extracted |
| 1 | `src/flask/ctx.py` | `src/flask/sessions.py` | call | extracted |
| 1 | `src/flask/globals.py` | `src/flask/sessions.py` | extends | extracted |
| 1 | `src/flask/testing.py` | `src/flask/sessions.py` | call | extracted |
| 1 | `tests/test_reqctx.py` | `src/flask/sessions.py` | extends | extracted |
| 1 | `tests/test_session_interface.py` | `src/flask/sessions.py` | extends | extracted |
| 2 | `tests/test_signals.py` | `src/flask/sessions.py` | call | extracted |
| 2 | `tests/test_testing.py` | `src/flask/sessions.py` | call | extracted |


$ codebase-index --json search where is the session cookie signed and saved --limit 3
{
  "query": "where is the session cookie signed and saved",
  "intent": "locate_impl",
  "mode": "hybrid",
  "index": {
    "exists": true,
    "stale": false,
    "files_changed_since_build": 0,
    "built_at": "2026-09-04T13:13:31Z",
    "head_commit": "d318b683471101618febed18996405ad26462110"
  },
  "confidence": "medium",
  "results": [
    {
      "path": "src/flask/sessions.py",
      "line_start": 24,
      "line_end": 54,
      "symbols": [
        "SessionMixin"
      ],
      "score": 1.9301,
      "reason": "in src/flask/ · 2 callers · source prior +0.08",
      "token_est": 11,
      "rank": 1,
      "skeletonized": false,
      "elided_lines": 0,
      "snippet": "class SessionMixin(MutableMapping[str, t.Any]):"
    },
    {
      "path": "src/flask/sessions.py",
      "line_start": 284,
      "line_end": 385,
      "symbols": [
        "SecureCookieSessionInterface"
      ],
      "score": 1.8766,
      "reason": "in src/flask/ · 2 callers · source prior +0.08",
      "token_est": 13,
      "rank": 2,
      "skeletonized": false,
      "elided_lines": 0,
      "snippet": "class SecureCookieSessionInterface(SessionInterface):"
    },
    {
      "path": "src/flask/sessions.py",
      "line_start": 57,
      "line_end": 80,
      "symbols": [
        "SecureCookieSession"
      ],
      "score": 1.8679,
      "reason": "in src/flask/ · 1 callers · source prior +0.08",
      "token_est": 16,
      "rank": 3,
      "skeletonized": false,
      "elided_lines": 0,
      "snippet": "class SecureCookieSession(CallbackDict[str, t.Any], SessionMixin):"
    }
  ],
  "recommended_reads": [
    {
      "path": "src/flask/sessions.py",
      "line_start": 24,
      "line_end": 54
    },
    {
      "path": "src/flask/sessions.py",
      "line_start": 284,
      "line_end": 385
    },
    {
      "path": "src/flask/sessions.py",
      "line_start": 57,
      "line_end": 80
    }
  ],
  "fallback_suggestions": {}
}

Done. Index lives in C:/Users/dabin/AppData/Local/Temp/claude/D--Projects-codebase-index/7f35eb46-c8c9-49e7-9d02-4c510c6877d0/scratchpad/repos/flask/.claude/cache/codebase-index/ and nothing was sent anywhere.
```
