# Generalize Skill Research Discipline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `codebase-index` skill generally better at answering codebase questions without tailoring it to any single benchmark repository.

**Architecture:** Keep the CLI and retrieval packet unchanged. Improve only the skill instructions and parity-protected copies so agents preserve token efficiency while doing enough validation for flow, architecture, and impact questions.

**Tech Stack:** Markdown skill instructions, pytest, Python packaging resources, existing skill parity tests.

---

## File Structure

- Modify: `skill/SKILL.md`
  - Canonical authored skill. This is the source text humans edit first.
- Modify: `src/codebase_index/skill_template/SKILL.md`
  - Wheel-packaged copy. Must stay byte-identical to `skill/SKILL.md`.
- Modify: `skills/codebase-index/SKILL.md`
  - Plugin skill copy. Must stay byte-identical to `skill/SKILL.md`.
- Modify: `tests/test_packaging.py`
  - Add regression assertions for the new universal guidance in the packaged template.
- Modify: `tests/test_plugin_skill_parity.py`
  - Keep existing parity test unchanged unless it fails for a legitimate path reason.

No CLI code changes are required. If implementation work discovers a missing output field or bad confidence behavior, stop and create a separate implementation plan for the retrieval pipeline instead of expanding this plan.

---

### Task 1: Add Regression Tests For Universal Skill Guidance

**Files:**
- Modify: `tests/test_packaging.py`
- Test: `tests/test_packaging.py`

- [ ] **Step 1: Add a failing packaging regression test**

Append this test to `tests/test_packaging.py` after `test_packaged_skill_matches_dev_copy`:

```python
def test_packaged_skill_defines_research_discipline():
    skill = (_template() / "SKILL.md").read_text(encoding="utf-8")

    assert "## Research modes" in skill
    assert "## Confidence handling" in skill
    assert "## Coverage gate" in skill
    assert "question-specific evidence" in skill
    assert "Do not optimize for a benchmark repository" in skill
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
pytest tests/test_packaging.py::test_packaged_skill_defines_research_discipline -q
```

Expected: FAIL because the current packaged skill does not contain the new research discipline sections.

- [ ] **Step 3: Commit the failing test**

Run:

```bash
git add tests/test_packaging.py
git commit -m "test(skill): cover generalized research guidance"
```

Expected: commit succeeds. If a hook runs tests and blocks the commit because the test is failing, keep the test staged and continue to Task 2 before committing both files together.

---

### Task 2: Rewrite The Canonical Skill Guidance

**Files:**
- Modify: `skill/SKILL.md`
- Test: `tests/test_packaging.py`

- [ ] **Step 1: Replace the current workflow and token-efficiency sections**

In `skill/SKILL.md`, replace the sections from `## Step-by-step workflow` through `## Fallback behavior` with this content:

```markdown
## Step-by-step workflow

1. **Classify the question** using the research modes below.
2. **Query the index** using the appropriate subcommand for `$QUERY`.
3. **Check index freshness** in the response:
   - `index.exists: false` -> run `codebase-index index` first, then re-query.
   - `index.stale: true` with few changes -> run `codebase-index update`, then re-query.
   - Otherwise proceed with results.
4. **Read question-specific evidence** from `recommended_reads`, starting with the smallest set that can answer the question.
5. **Validate coverage** with the coverage gate before answering.
6. **Answer with citations** using file:line references (for example, `src/auth/token.py:88-134`).
7. **Fallback** only when confidence handling allows it.

## Research modes

Choose the lightest mode that fits the user's question. Do not optimize for a benchmark repository; optimize for the user's actual intent.

| User intent | Primary command | Required evidence |
|---|---|---|
| "where is X" / locate implementation | `codebase-index search "$QUERY" --json` or `codebase-index symbol "<name>" --json` | The defining file/range and one citation. |
| "who calls X" / references | `codebase-index refs "<name>" --json` | Call sites or a clear statement that none were found. |
| "how does X work" / trace a flow | `codebase-index search "$QUERY" --json` plus `refs` for the entry point when needed | Entry point, core logic, and main consumers. |
| "what breaks if I change X" / refactoring impact | `codebase-index impact "<file-or-symbol>" --json` plus `refs` for important symbols when needed | Direct dependents, likely failure modes, and confidence level. |
| architecture / overview | 2-4 targeted `search` queries around the main nouns | Main modules, boundaries, and the parts not inspected. |
| bug / stack trace | `search` exact error text or symbol names, then `refs` if a caller chain matters | Faulting location, input path, and likely cause. |

## Token-budgeted output interpretation

The index returns a **ranked retrieval packet** with:

- `rank` — result position (start with 1-3)
- `path` — file path
- `line_start` / `line_end` — exact line range to read
- `symbols` — symbols found in this range
- `score` — relevance score
- `reason` — why this result ranked (for example, "exact symbol match, 4 callers")
- `snippet` — compact code excerpt (may already answer the question)

Top-level fields:

- `recommended_reads` — the precise `{path, line_start, line_end}` list to open next. This is the read plan, not a prison.
- `confidence` — how much validation is needed before answering.
- `fallback_suggestions` — ripgrep patterns and paths to try if the index is weak.

## Confidence handling

- `high`: Trust the ranking, read only the key ranges needed for the selected research mode, then answer.
- `medium`: Read the key ranges, then run one targeted `refs`, `impact`, `symbol`, or fallback `rg` check if the answer depends on callers, configuration, or side effects.
- `low`: Use `fallback_suggestions` and say that the index was weak. If fallback also fails, state the uncertainty instead of inventing a complete answer.

High confidence does not mean "read nothing." Medium confidence does not mean "scan the repo." Match validation to the question's risk.

## Coverage gate

Before answering, verify that the evidence matches the question:

- Location questions: did you identify the defining file/range?
- Flow questions: did you inspect the entry point, core logic, and at least one consumer or exit path?
- Impact questions: did you inspect direct dependents and name likely failure modes?
- Config/data questions: did you inspect where values are loaded and where they are consumed?
- Architecture questions: did you name the boundaries and explicitly say which areas were not inspected?
- Bug questions: did you connect the observed symptom to a source path and a sink or caller path?

If the gate fails, run one more targeted index query before falling back to Grep/Glob.

## Token efficiency rules

- Trust the index. Read the **fewest** files needed for the selected research mode.
- Start with rank 1-3 and the returned `recommended_reads`.
- Read **line ranges**, not whole files. Use `line_start`/`line_end` with Read's `offset`/`limit`.
- The `snippet` may already answer a narrow location question; re-read only if citations or surrounding logic are needed.
- Prefer `search`/`symbol`/`refs`/`impact` over manual Grep/Glob. Those are targeted validation tools, not expensive fallbacks.
- Do not re-run the query with trivially reworded text. Refine with a different subcommand or a more specific symbol.

## Fallback behavior

Fall back to built-in search **only** when results are empty, `confidence` is `low`, the coverage gate fails after one more targeted index query, or the user asks for something the index clearly does not cover.

1. Use `fallback_suggestions.ripgrep` patterns from the response via Grep.
2. If still nothing, Glob for likely paths, then Grep within them.
3. As a last resort, broaden the search, but tell the user the index was weak here. It may need a rebuild with `codebase-index index`.

Never start with a full-repo scan when the index exists and is fresh.
```

- [ ] **Step 2: Keep ASCII-safe punctuation**

Run:

```bash
python -c "from pathlib import Path; p=Path('skill/SKILL.md'); text=p.read_text(encoding='utf-8'); assert '→' not in text and '—' not in text"
```

Expected: command exits with status 0.

- [ ] **Step 3: Run the focused regression test against the packaged copy**

Run:

```bash
pytest tests/test_packaging.py::test_packaged_skill_defines_research_discipline -q
```

Expected: still FAIL, because only the canonical skill was updated and the packaged copy has not been synchronized yet.

---

### Task 3: Synchronize Skill Copies

**Files:**
- Modify: `src/codebase_index/skill_template/SKILL.md`
- Modify: `skills/codebase-index/SKILL.md`
- Test: `tests/test_packaging.py`, `tests/test_plugin_skill_parity.py`

- [ ] **Step 1: Copy the canonical skill into both parity-protected copies**

Run:

```bash
python -c "from pathlib import Path; src=Path('skill/SKILL.md').read_text(encoding='utf-8'); Path('src/codebase_index/skill_template/SKILL.md').write_text(src, encoding='utf-8'); Path('skills/codebase-index/SKILL.md').write_text(src, encoding='utf-8')"
```

Expected: both copied files now match `skill/SKILL.md`.

- [ ] **Step 2: Verify byte parity manually**

Run:

```bash
python -c "from pathlib import Path; a=Path('skill/SKILL.md').read_text(encoding='utf-8'); b=Path('src/codebase_index/skill_template/SKILL.md').read_text(encoding='utf-8'); c=Path('skills/codebase-index/SKILL.md').read_text(encoding='utf-8'); assert a == b == c"
```

Expected: command exits with status 0.

- [ ] **Step 3: Run parity and packaging tests**

Run:

```bash
pytest tests/test_packaging.py tests/test_plugin_skill_parity.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit the synchronized skill change**

Run:

```bash
git add skill/SKILL.md src/codebase_index/skill_template/SKILL.md skills/codebase-index/SKILL.md tests/test_packaging.py
git commit -m "docs(skill): generalize research discipline"
```

Expected: commit succeeds. If Task 1 could not be committed separately because hooks blocked the failing test, this creates the combined passing commit.

---

### Task 4: Verify Installed Behavior Does Not Regress

**Files:**
- No source edits expected.
- Test: `tests/test_packaging.py`, `tests/test_plugin_skill_parity.py`, optionally `tests/test_init_cli.py`

- [ ] **Step 1: Run skill-specific tests**

Run:

```bash
pytest tests/test_packaging.py tests/test_plugin_skill_parity.py tests/test_init_cli.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Inspect the diff for accidental benchmark-specific wording**

Run:

```bash
git show --stat --oneline HEAD
git show --word-diff -- skill/SKILL.md
```

Expected: the diff contains generic guidance only. It must not mention project-specific class names, domain-specific product names, or any benchmark repository from the screenshot.

- [ ] **Step 3: Confirm working tree status**

Run:

```bash
git status --short
```

Expected: no modified tracked files remain from this plan. Pre-existing unrelated untracked files, such as screenshots, may still appear and should not be committed unless the user explicitly asks.

---

## Self-Review

Spec coverage:
- Universal rather than benchmark-specific behavior is covered by Task 2's research modes and explicit "Do not optimize for a benchmark repository" instruction.
- Confidence semantics are covered by `## Confidence handling`.
- Sufficient investigation without full-repo scanning is covered by `## Coverage gate` and `## Token efficiency rules`.
- Existing packaging/plugin copies are covered by Task 3 parity checks.

Placeholder scan:
- This plan contains no placeholder tokens, deferred implementation notes, or generic "write tests" steps.

Type and path consistency:
- The plan uses existing paths from the repository: `skill/SKILL.md`, `src/codebase_index/skill_template/SKILL.md`, `skills/codebase-index/SKILL.md`, `tests/test_packaging.py`, and `tests/test_plugin_skill_parity.py`.
