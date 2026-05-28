# Example queries → commands

How natural questions map onto the CLI (and what the skill does for you).

| You ask | Detected intent | Command the skill runs |
|---|---|---|
| "Where is the rate limiter configured?" | locate_impl | `cbx search "rate limiter config" --json` |
| "How does request authentication work?" | how_it_works | `cbx explain "request authentication flow" --json` |
| "What breaks if I change the `User` model?" | impact | `cbx impact "User" --json` |
| "Who calls `send_email`?" | find_refs | `cbx refs "send_email" --json` |
| "Trace how the upload payload flows to storage." | data_flow | `cbx explain "upload payload data flow" --json` |
| "Why am I getting `KeyError: 'token'` here?" | debug_error | `cbx search "KeyError token" --json` |
| "Give me a high-level architecture overview." | architecture | `cbx explain "architecture overview" --json` |
| "Find the `WebSocketManager` class." | locate_impl | `cbx symbol "WebSocketManager" --json` |

Each returns ranked results + `recommended_reads`. Claude then opens only those line ranges.

## Direct CLI usage (outside Claude)

```bash
codebase-index index
codebase-index search "websocket reconnect" --limit 5
codebase-index symbol "WebSocketManager" --exact
codebase-index refs "send_email" --kind callers
codebase-index impact "src/models/user.py" --direction up --depth 2
codebase-index explain "how does billing work" --token-budget 2000
codebase-index stats
codebase-index doctor --strict
```
