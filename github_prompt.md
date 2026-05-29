You are a senior open-source product engineer, GitHub repository maintainer, technical writer, SEO strategist, and Claude Code ecosystem expert.

Your task is to turn this repository into a polished, professional, discoverable, and SEO-optimized open-source GitHub project for a Claude Code Skill.

Project name: `codebase-index`

Repository name: `claude-code-codebase-index-skill`

One-line positioning:
`A local-first Claude Code Skill that builds a hybrid index of your codebase so Claude can find the right files, symbols, and context without wasting tokens.`

Core product idea:
This is a Claude Code Skill that gives Claude Code Cursor-like project indexing. The user asks a question about a project, and Claude first searches a local hybrid index instead of scanning the whole repository. The skill returns compact, ranked retrieval packets with files, symbols, line ranges, snippets, and “next files to read”, helping Claude answer codebase questions with fewer tokens.

The repository must look like a popular, production-quality Claude Code Skill project, not a rough prototype.

Your goals:

1. Make the GitHub repository visually and structurally professional.
2. Optimize it for GitHub search, Google search, AI answer engines, and Claude Skill directories.
3. Make it clear, trustworthy, local-first, and easy to install.
4. Prepare it for inclusion in “awesome Claude Code skills” lists and skill marketplaces.
5. Improve README, docs, metadata, badges, examples, issue templates, and release structure.
6. Do not overhype. Be accurate, technical, and credible.

Important target keywords:

* Claude Code Skill
* Claude Code skills
* Claude Code codebase indexing
* Claude Code project index
* Claude Code semantic search
* Claude Code local search
* Claude Code token optimization
* Claude Code context management
* Cursor-like indexing for Claude Code
* local-first codebase index
* AI codebase search
* codebase RAG
* hybrid code search
* AST code indexing
* Tree-sitter code index
* SQLite FTS5 code search
* semantic code search
* code retrieval for AI agents
* AI coding agent context
* repository indexing for Claude Code

Suggested GitHub repository description:
`Local-first Claude Code Skill for Cursor-like codebase indexing, hybrid code search, symbol lookup, and token-efficient project context.`

Suggested GitHub topics:
`claude-code`, `claude-code-skill`, `claude-skills`, `ai-coding`, `codebase-indexing`, `semantic-code-search`, `code-search`, `rag`, `codebase-rag`, `tree-sitter`, `sqlite`, `fts5`, `developer-tools`, `ai-agents`, `cursor-alternative`, `context-engineering`, `token-optimization`, `local-first`, `python`, `cli`

Expected final repository structure:

```text
.
├── README.md
├── LICENSE
├── CHANGELOG.md
├── CONTRIBUTING.md
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── ROADMAP.md
├── .gitignore
├── .editorconfig
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.yml
│   │   ├── feature_request.yml
│   │   └── skill_listing_request.yml
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── workflows/
│   │   ├── ci.yml
│   │   └── release.yml
│   └── FUNDING.yml
├── skill/
│   ├── SKILL.md
│   ├── scripts/
│   │   ├── install.py
│   │   ├── doctor.py
│   │   └── smoke_test.py
│   └── examples/
│       ├── basic-usage.md
│       ├── claude-md-example.md
│       └── hooks-example.json
├── src/
│   └── codebase_index/
│       ├── __init__.py
│       ├── cli.py
│       ├── indexer/
│       ├── parsers/
│       ├── storage/
│       ├── retrieval/
│       ├── graph/
│       ├── embeddings/
│       ├── output/
│       └── security/
├── docs/
│   ├── INSTALLATION.md
│   ├── QUICKSTART.md
│   ├── ARCHITECTURE.md
│   ├── SKILL_DESIGN.md
│   ├── RETRIEVAL_PIPELINE.md
│   ├── DATABASE_SCHEMA.md
│   ├── SECURITY_MODEL.md
│   ├── SEO.md
│   ├── FAQ.md
│   └── COMPARISON.md
├── examples/
│   ├── sample-retrieval-output.md
│   ├── sample-queries.md
│   └── demo-project/
├── tests/
├── pyproject.toml
└── uv.lock or requirements.txt
```

README requirements:

Create a highly polished `README.md` with this structure:

1. Hero section

   * Project name: `codebase-index`
   * Short subtitle
   * Clear one-sentence value proposition
   * Badges:

     * License
     * Python version
     * CI
     * Claude Code Skill
     * Local-first
     * No telemetry
     * No network by default
     * SQLite
     * Tree-sitter
   * Optional small terminal demo block

2. Problem section
   Explain the pain:

   * Claude Code can waste tokens scanning large projects.
   * Broad Grep/Read workflows are noisy.
   * Large repositories need a compact retrieval layer.
   * Developers want Cursor-like codebase awareness inside Claude Code.

3. Solution section
   Explain:

   * Local hybrid index
   * Symbol search
   * Full-text search
   * Optional semantic search
   * Dependency/reference graph
   * Token-budgeted retrieval packets
   * Claude reads only the recommended files

4. Quick demo
   Include a realistic CLI/session example:

```bash
/codebase-index "where is user authentication implemented?"
```

Expected output example:

```text
Top matches:
1. src/auth/AuthService.ts:12-148
   reason: matched AuthService, login(), validatePassword()
   next read: src/auth/AuthService.ts

2. src/routes/auth.ts:20-91
   reason: /login route calls AuthService.login()
   next read: src/routes/auth.ts
```

5. Installation
   Include several options:

   * Clone directly into a project’s `.claude/skills/codebase-index`
   * Install as reusable local skill
   * Install Python package in editable mode
   * Run doctor command

Example:

```bash
git clone https://github.com/<OWNER>/claude-code-codebase-index-skill .claude/skills/codebase-index
python -m codebase_index doctor
```

6. Usage
   Include commands:

   * `/codebase-index init`
   * `/codebase-index index`
   * `/codebase-index search "query"`
   * `/codebase-index symbol "AuthService"`
   * `/codebase-index refs "AuthService.login"`
   * `/codebase-index impact "src/auth/AuthService.ts"`
   * `/codebase-index stats`
   * `/codebase-index doctor`

7. How it works
   Include a clean pipeline diagram in Markdown:

```text
User question
  ↓
Claude Code Skill
  ↓
Hybrid retrieval
  ├─ Path search
  ├─ Symbol search
  ├─ SQLite FTS5
  ├─ Optional embeddings
  └─ Graph expansion
  ↓
Ranked retrieval packet
  ↓
Claude reads only relevant files
```

8. Features
   Use checkboxes:

   * Local-first indexing
   * No network by default
   * Respects ignore files
   * SQLite storage
   * FTS5 lexical search
   * Tree-sitter AST parsing
   * Symbol extraction
   * Incremental indexing
   * Token-budgeted output
   * Secret redaction
   * Optional embeddings
   * Optional hooks
   * Optional MCP wrapper in future

9. Safety and privacy section
   Must be prominent:

   * No telemetry
   * No external API calls by default
   * Does not index `.env`, keys, certificates, private tokens
   * Respects `.gitignore`, `.claudeignore`, `.codeindexignore`
   * Index stored locally in `.claude/cache/codebase-index`
   * Optional embeddings must be local by default
   * External embeddings require explicit opt-in

10. Comparison table
    Compare with:

* manual Grep/Read
* Cursor indexing
* MCP-only tools
* Aider repo-map
* this skill

Use honest positioning:

* This project is not a full IDE.
* This project is not a replacement for Cursor.
* This project is a local retrieval layer for Claude Code.

11. Repository layout
    Explain main folders.

12. Configuration
    Document `.codeindexignore`, config file, cache location, embedding backend.

13. Claude Code integration
    Include:

* `skill/SKILL.md`
* example `.claude/CLAUDE.md`
* optional hooks config

14. SEO section
    Add a short “Keywords” paragraph written naturally, not spammy:
    Example:
    `codebase-index is a local-first Claude Code Skill for codebase indexing, semantic code search, token-efficient context retrieval, AST-based symbol search, and Cursor-like project awareness inside Claude Code.`

15. FAQ
    Include:

* Is this a Cursor replacement?
* Does it send code anywhere?
* Does it work without embeddings?
* Does it support large repositories?
* Why not just use Grep?
* Why not MCP?
* Can I use it with other agents?
* How do I reset the index?

16. Contributing
    Clear contributor setup:

* install dependencies
* run tests
* run lint
* submit PR

17. Roadmap
    Link to `ROADMAP.md`.

18. License
    Recommend MIT or Apache-2.0.
    If unsure, use MIT for maximum adoption.

Create these documentation files:

`docs/INSTALLATION.md`

* Full installation guide
* Requirements
* Python versions
* Claude Code setup
* Skill install paths
* Troubleshooting

`docs/QUICKSTART.md`

* 5-minute setup
* Run index
* Ask first question
* Interpret output

`docs/ARCHITECTURE.md`

* Component overview
* Indexer
* Parser layer
* Storage layer
* Retrieval layer
* Output layer
* Security layer

`docs/RETRIEVAL_PIPELINE.md`

* Explain ranking:

  * exact match
  * path match
  * symbol match
  * FTS5
  * vector search
  * graph expansion
  * reranking
  * confidence score

`docs/DATABASE_SCHEMA.md`

* Tables:

  * files
  * chunks
  * symbols
  * edges
  * fts_chunks
  * embeddings
  * summaries
  * metadata

`docs/SECURITY_MODEL.md`

* Local-first policy
* Secret redaction
* Ignore rules
* Threat model
* Unsafe patterns
* Hook risks
* External embedding opt-in

`docs/COMPARISON.md`

* Compare with:

  * Cursor
  * Continue
  * Aider repo-map
  * Sourcegraph Cody
  * Serena/MCP tools
  * manual grep
* Be fair and factual.
* Position this project as Claude Code Skill-first and local-first.

`docs/FAQ.md`

* Practical user questions.

`docs/SEO.md`

* Repository SEO plan:

  * GitHub description
  * topics
  * README headings
  * keyword map
  * launch checklist
  * backlink targets
  * awesome lists to submit to
  * release announcement template
  * social post template

Create `skill/SKILL.md`:

Requirements:

* Use YAML frontmatter.
* `name: codebase-index`
* Strong `description` for automatic selection.
* Include safe `allowed-tools`.
* Tell Claude when to use the skill.
* Tell Claude not to scan the whole repository first.
* Tell Claude to call the local CLI.
* Explain fallback behavior.
* Explain token-budgeted output interpretation.

Draft the skill around this behavior:

```md
---
name: codebase-index
description: Use this skill before answering questions about a repository's architecture, implementation locations, symbols, references, dependencies, refactoring impact, data flow, bugs, or where something is implemented. It searches a local hybrid codebase index so Claude reads only the most relevant files instead of scanning the entire project.
allowed-tools: Bash(python *), Bash(python3 *), Read, Grep, Glob
---

# Codebase Index

Use this skill first for codebase questions.

Never scan the entire repository before searching the index.

...
```

Create `.github` files:

1. `ISSUE_TEMPLATE/bug_report.yml`
2. `ISSUE_TEMPLATE/feature_request.yml`
3. `ISSUE_TEMPLATE/skill_listing_request.yml`
4. `PULL_REQUEST_TEMPLATE.md`
5. `workflows/ci.yml`
6. `workflows/release.yml`

CI should:

* install dependencies
* run tests
* run lint
* run type checks if configured
* run skill smoke test

Create `SECURITY.md`:

* Vulnerability reporting
* Supported versions
* Secret handling
* No telemetry promise
* Disclosure policy

Create `CONTRIBUTING.md`:

* Development setup
* Commit style
* Branch naming
* Test requirements
* Documentation requirements
* PR checklist

Create `CHANGELOG.md` using Keep a Changelog style.

Create `ROADMAP.md`:
Milestones:

* M0: repository packaging
* M1: SQLite + FTS5 index
* M2: Tree-sitter symbol extraction
* M3: hybrid retrieval
* M4: graph expansion
* M5: token-budgeted retrieval packets
* M6: optional local embeddings
* M7: optional hooks
* M8: optional MCP bridge
* M9: public release and awesome-list submissions

SEO optimization tasks:

1. Optimize repository name:
   Preferred: `claude-code-codebase-index-skill`

2. Optimize GitHub About description:
   Use:
   `Local-first Claude Code Skill for Cursor-like codebase indexing, hybrid code search, symbol lookup, and token-efficient project context.`

3. Add repository website if available:
   If GitHub Pages exists, use docs site.
   Otherwise leave blank.

4. Add topics:
   Include the suggested topics from above.

5. README SEO:
   Ensure the first 150 words contain:

   * Claude Code Skill
   * codebase indexing
   * local-first
   * Cursor-like indexing
   * token-efficient context
   * semantic code search
   * AST symbol search

6. Heading SEO:
   Use searchable headings:

   * “Claude Code Skill for Codebase Indexing”
   * “Cursor-like Project Indexing for Claude Code”
   * “Token-Efficient Codebase Search”
   * “Local-First Semantic Code Search”
   * “How Codebase Index Works”

7. Add natural keyword mentions:
   Do not keyword-stuff.
   Use each primary keyword naturally 1–3 times.

8. Add badges:
   Create shields.io badge Markdown for:

   * Claude Code Skill
   * Local First
   * No Telemetry
   * No Network By Default
   * Python
   * SQLite
   * Tree-sitter
   * License
   * CI

9. Add image/social preview recommendation:
   If possible, create or request:

   * `assets/social-preview.png`
   * GitHub social preview dimensions
   * text: “codebase-index — Cursor-like indexing for Claude Code”

10. Add launch checklist:

* Create v0.1.0 release
* Add GitHub topics
* Add repo social preview
* Submit to awesome Claude skills lists
* Submit to awesome AI coding tools lists
* Post on X/Twitter, Reddit, Hacker News, Dev.to
* Add demo GIF or terminal recording
* Add comparison page
* Add security model page

Output expectations:

First, inspect the current repository structure.
Then produce a concrete plan.
Then implement the repository packaging files.
Then show a summary of created/modified files.
Then list manual GitHub UI actions I still need to do:

* add topics
* set description
* set social preview
* create release
* enable discussions if useful
* pin repository if needed

Be careful:

* Do not invent features that are not implemented.
* Mark planned features clearly as “planned”.
* Separate “available now” from “roadmap”.
* Do not claim production-ready unless tests and CI exist.
* Do not claim zero security risk.
* Emphasize local-first and no network by default.
* Make installation instructions realistic.
* Make the README clean, skimmable, and credible.
* Use English for repository docs.
* Use concise professional language.
