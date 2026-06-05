

<!-- >>> codebase-index managed >>> -->
# codebase-index

Use the local codebase index before scanning repository files.

Skill resources: `.codex/skills/codebase-index/SKILL.md`

Run `codebase-index search "<query>" --json` for general questions, or use
`symbol`, `refs`, `impact`, and `graph` for symbol lookup, references, change
impact, and HTML graph export. Search/read commands auto-build the index when
it is missing; run `codebase-index update` when responses report stale data.
<!-- <<< codebase-index managed <<< -->

## Versioning Policy

Use Semantic Versioning in the `MAJOR.MINOR.PATCH` format.

- For fixes, maintenance, documentation, tests, small features, and other
  changes that are not broad or substantially alter the product, increment
  only `PATCH`: `1.2.3` -> `1.2.4`.
- For broad or substantial changes, new major capabilities, or notable changes
  to behavior or architecture, increment `MINOR` and reset `PATCH`:
  `1.2.3` -> `1.3.0`.
- Do not increment `MAJOR` (for example, `1.x.x` -> `2.0.0`) unless the user
  explicitly requests it or explicitly approves a breaking release.
- When uncertain, use a `PATCH` increment and do not overstate the scope of the
  release.
- When changing the version, update every canonical version location and the
  changelog together so release metadata remains consistent.

## Fork and Pull Request Workflow

When contributing from a fork, keep the pull request focused and easy to
review.

- Add the canonical repository as `upstream`; keep the contributor fork as
  `origin`.
- Never commit directly to `main`. Create a branch from the latest
  `upstream/main` using `<type>/<short-description>`.
- Keep unrelated changes in separate branches and pull requests. Do not include
  generated files, build artifacts, local configuration, credentials, or
  editor-specific files.
- Rebase the branch onto the latest `upstream/main` before opening or updating
  the pull request. Do not merge `main` into the feature branch unless a
  maintainer explicitly requests it.
- Run the relevant tests, linting, formatting, and type checks before pushing.
- Use Conventional Commits and write a pull request description that explains
  the problem, the solution, verification performed, and any compatibility or
  migration impact.
- Add user-visible changes to `CHANGELOG.md` under `[Unreleased]`, but do not
  change the project version unless a maintainer explicitly requests a release
  version bump.
- Push only the contributor branch to the fork, then open a pull request against
  the canonical repository's `main` branch. Never force-push after review has
  started unless rewriting the branch is necessary and clearly communicated.
