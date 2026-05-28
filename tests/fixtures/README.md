# Test fixtures

`sample_repo/` (to be added in M1, see docs/ROADMAP.md task 5) is a tiny multi-language repo used
across discovery/parsing/retrieval/graph tests. It deliberately includes things that MUST be
excluded so we can assert the security gates:

```
sample_repo/
├── src/
│   ├── auth/token.py        # has refresh_access_token() — symbol/refs target
│   └── models/user.py       # impact-test target (imported widely)
├── web/app.ts               # tree-sitter TS coverage
├── .env                     # MUST be excluded (secret file)
├── secrets.pem              # MUST be excluded (private key)
├── node_modules/...         # MUST be excluded (dependency dir)
├── dist/bundle.min.js       # MUST be excluded (generated)
├── logo.png                 # MUST be excluded (binary)
└── huge.json                # > max_file_bytes -> excluded
```

Tests assert: secrets/binaries/generated/oversized never appear in `files`; symbols resolve;
`impact("User")` returns the importers of `models/user.py`.
