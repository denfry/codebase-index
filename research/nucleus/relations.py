"""Typed relation union: the completion model P(c | anchor).

The architecture's central bet is that the members of a required set are related to
*each other* by something computable, so that a high-precision anchor found by lexical
retrieval can be completed into a set. This module estimates those relations.

Five relations, chosen because `research/diagnose_structure.py` measured each of them
carrying signal on 900 real anchor->target gold pairs, and because static structure and
history were shown to contribute *uniquely* (5.3% and 9.8% of pairs respectively) —
neither subsumes the other, so a single-relation completer leaves recall on the table.

Temporal honesty
----------------
`CoChange` is the one relation that can leak. Ground truth here is mined from commits,
so a co-change model that has seen the query's own commit would be reading the answer.
`CoChangeModel.advance_to()` therefore exposes counts from commits **strictly older**
than a given commit, and the benchmark sweeps queries oldest-first so the observable
history only ever grows. There is no code path that can see a commit at or after the
query's own; the filter is a property of the data structure, not a discipline the
caller has to remember.
"""

from __future__ import annotations

import math
import re
import sqlite3
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_TEST_MARK = re.compile(r"(?:^|[._-])(?:test|tests|spec|specs)(?:$|[._-])", re.I)

# A commit touching more than this many files couples everything to everything and is
# evidence about a release process, not about a design relation.
MAX_COMMIT_FILES = 40

# Additive smoothing on co-change confidence. Without it a file that appears in one
# prior commit alongside one other file scores confidence 1.0 on a single observation.
COCHANGE_PRIOR = 2.0


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def stem_tokens(path: str) -> set[str]:
    base = _norm(path).rsplit("/", 1)[-1].split(".", 1)[0]
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", base).replace("_", " ").replace("-", " ")
    return {w.lower() for w in _WORD.findall(parts) if len(w) > 2}


def core_stem(path: str) -> str:
    base = _norm(path).rsplit("/", 1)[-1].split(".", 1)[0]
    base = re.sub(r"^(?:test|spec)[._-]?", "", base, flags=re.I)
    base = re.sub(r"[._-]?(?:test|tests|spec|specs)$", "", base, flags=re.I)
    return base.lower()


def is_testish(path: str) -> bool:
    p = _norm(path)
    return bool(_TEST_MARK.search(p)) or "/test" in p.lower()


def directory(path: str) -> str:
    p = _norm(path)
    return p.rsplit("/", 1)[0] if "/" in p else ""


# --- static structure -------------------------------------------------------


def load_static_edges(index_path: Path) -> dict[str, dict[str, float]]:
    """file -> {file: weight} from resolved import/call/reference edges.

    Symbol targets are lifted to their defining file because the unit of the ground
    truth, and of the agent's decision, is a file. Edge confidence is carried through
    as the weight: an `inferred` import-path match is weaker evidence than an
    `extracted` unique-symbol match, and the completer should know the difference.
    """
    conf_w = {"extracted": 1.0, "inferred": 0.75, "ambiguous": 0.35}
    adj: dict[str, dict[str, float]] = defaultdict(dict)
    if not index_path.exists():
        return adj
    conn = sqlite3.connect(index_path)
    try:
        rows = conn.execute(
            """
            SELECT src.path AS a,
                   CASE WHEN e.dst_kind = 'file' THEN df.path ELSE sf.path END AS b,
                   e.confidence
            FROM edges AS e
            JOIN files AS src ON src.id = e.file_id
            LEFT JOIN files   AS df ON e.dst_kind = 'file'   AND df.id = e.dst_id
            LEFT JOIN symbols AS s  ON e.dst_kind = 'symbol' AND s.id  = e.dst_id
            LEFT JOIN files   AS sf ON sf.id = s.file_id
            WHERE e.resolved = 1
            """
        ).fetchall()
    except sqlite3.Error:
        return adj
    finally:
        conn.close()
    for a, b, conf in rows:
        if not a or not b or a == b:
            continue
        a, b = _norm(a), _norm(b)
        w = conf_w.get((conf or "extracted").lower(), 0.5)
        # Undirected: "must I also look at this" is symmetric even though the edge
        # is not. Direction is kept out of the weight because the diagnostic found
        # no consistent asymmetry at file granularity.
        adj[a][b] = max(adj[a].get(b, 0.0), w)
        adj[b][a] = max(adj[b].get(a, 0.0), w)
    return adj


# --- history ----------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


@dataclass
class CoChangeModel:
    """Incrementally-revealed co-change counts with a hard no-lookahead guarantee.

    Commits are held oldest-last (position 0 = newest, matching `git log` order).
    `advance_to(pos)` folds in every commit strictly older than `pos`. Because the
    benchmark visits queries oldest-first, `pos` decreases monotonically and the fold
    is a single linear sweep over history per corpus rather than a rescan per query.
    """

    commits: list[tuple[int, list[str]]] = field(default_factory=list)  # (pos, files)
    _pair: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    _single: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _folded: int = 0          # index into self.commits (which is sorted oldest-first)
    _current_pos: int | None = None

    @classmethod
    def from_repo(cls, repo: Path) -> "CoChangeModel":
        order: dict[str, int] = {}
        for i, sha in enumerate(
            s.strip() for s in _git(repo, "log", "--format=%H").splitlines() if s.strip()
        ):
            order[sha[:12]] = i
        raw = _git(repo, "log", "--no-merges", "--name-only",
                   "--pretty=format:%x01%H", "--diff-filter=ACMR")
        commits: list[tuple[int, list[str]]] = []
        for rec in raw.split("\x01"):
            rec = rec.strip("\n")
            if not rec:
                continue
            head, _, body = rec.partition("\n")
            pos = order.get(head.strip()[:12])
            if pos is None:
                continue
            files = [_norm(ln.strip()) for ln in body.splitlines() if ln.strip()]
            if 0 < len(files) <= MAX_COMMIT_FILES:
                commits.append((pos, files))
        # Oldest first, so advancing toward newer queries is an append-only fold.
        commits.sort(key=lambda x: -x[0])
        return cls(commits=commits)

    def advance_to(self, pos: int) -> None:
        """Reveal every commit strictly older than `pos` (i.e. position > pos)."""
        if self._current_pos is not None and pos > self._current_pos:
            raise ValueError(
                "CoChangeModel is append-only; queries must be visited oldest-first "
                f"(asked for pos={pos} after pos={self._current_pos})"
            )
        self._current_pos = pos
        while self._folded < len(self.commits) and self.commits[self._folded][0] > pos:
            _, files = self.commits[self._folded]
            uniq = sorted(set(files))
            for f in uniq:
                self._single[f] += 1
            for i, a in enumerate(uniq):
                for b in uniq[i + 1:]:
                    self._pair[(a, b)] += 1
            self._folded += 1

    def confidence(self, a: str, b: str) -> float:
        """P(b changes | a changes), smoothed. Asymmetric by construction."""
        if a == b:
            return 0.0
        key = (a, b) if a < b else (b, a)
        joint = self._pair.get(key, 0)
        if not joint:
            return 0.0
        return joint / (self._single.get(a, 0) + COCHANGE_PRIOR)

    def neighbours(self, a: str) -> list[str]:
        """Files ever seen co-changing with `a` in the revealed history."""
        # Kept simple: the pair table is small enough (<2e5) that a per-anchor scan
        # is cheaper than maintaining a second adjacency index.
        out = []
        for (x, y), n in self._pair.items():
            if n and x == a:
                out.append(y)
            elif n and y == a:
                out.append(x)
        return out


class CoChangeIndex:
    """Adjacency view over CoChangeModel, rebuilt lazily when history advances."""

    def __init__(self, model: CoChangeModel) -> None:
        self.model = model
        self._adj: dict[str, list[str]] = {}
        self._built_at = -1

    def neighbours(self, a: str) -> list[str]:
        if self._built_at != self.model._folded:
            adj: dict[str, list[str]] = defaultdict(list)
            for (x, y), n in self.model._pair.items():
                if n:
                    adj[x].append(y)
                    adj[y].append(x)
            self._adj = adj
            self._built_at = self.model._folded
        return self._adj.get(a, [])


# --- the relation union -----------------------------------------------------


@dataclass(frozen=True)
class RelationWeights:
    """Linear weights over the relation union.

    Defaults are the leave-one-repository-out selection from `fit_weights.py`; they
    are fitted parameters and are reported as such.
    """

    edge: float = 1.0
    cochange: float = 1.0
    testlink: float = 1.0
    stem: float = 1.0
    dirw: float = 0.3

    def as_dict(self) -> dict[str, float]:
        return {"edge": self.edge, "cochange": self.cochange,
                "testlink": self.testlink, "stem": self.stem, "dir": self.dirw}


class RelationGraph:
    """All five relations for one corpus, with candidate generation.

    Generation is *anchor-local*: candidates come from the anchors' relation
    neighbourhoods, never from a scan of the corpus. That is what keeps completion at
    O(|A0| * deg) instead of O(|corpus|) and is why the closure stage costs ~1ms.
    """

    def __init__(
        self,
        files: list[str],
        *,
        static: dict[str, dict[str, float]],
        cochange: CoChangeModel,
    ) -> None:
        self.files = [_norm(f) for f in files]
        self.static = static
        self.cochange = cochange
        self.cochange_index = CoChangeIndex(cochange)

        self._dir: dict[str, list[str]] = defaultdict(list)
        self._by_stem_token: dict[str, list[str]] = defaultdict(list)
        self._core_stem: dict[str, list[str]] = defaultdict(list)
        self._tokens: dict[str, set[str]] = {}
        for f in self.files:
            self._dir[directory(f)].append(f)
            toks = stem_tokens(f)
            self._tokens[f] = toks
            for t in toks:
                self._by_stem_token[t].append(f)
            self._core_stem[core_stem(f)].append(f)

        n = max(1, len(self.files))
        # IDF over file-name tokens: `index` in a repo full of `*_index.py` is not
        # evidence of anything, while a token appearing in two names is strong.
        self._idf = {
            t: math.log(n / len(fs)) for t, fs in self._by_stem_token.items()
        }
        self._max_idf = max(self._idf.values(), default=1.0) or 1.0

    # -- individual relation strengths, all normalised to [0, 1] --------------

    def rel_edge(self, a: str, c: str) -> float:
        return self.static.get(a, {}).get(c, 0.0)

    def rel_cochange(self, a: str, c: str) -> float:
        return min(1.0, self.cochange.confidence(a, c))

    def rel_testlink(self, a: str, c: str) -> float:
        if is_testish(a) == is_testish(c):
            return 0.0
        cs = core_stem(a)
        return 1.0 if cs and cs == core_stem(c) else 0.0

    def rel_stem(self, a: str, c: str) -> float:
        shared = self._tokens.get(a, set()) & self._tokens.get(c, set())
        if not shared:
            return 0.0
        # Best shared token by IDF, normalised. Sum would let three generic tokens
        # outweigh one highly specific one, which is the wrong ordering.
        return max(self._idf.get(t, 0.0) for t in shared) / self._max_idf

    def rel_dir(self, a: str, c: str) -> float:
        d = directory(a)
        if d != directory(c):
            return 0.0
        # A 3-file package is a strong grouping; a 200-file dumping ground is not.
        return 1.0 / math.log2(2 + len(self._dir.get(d, ())))

    # -- candidate generation -------------------------------------------------

    def candidates(self, anchor: str, *, dir_cap: int = 12) -> set[str]:
        """Files related to `anchor` by at least one relation."""
        out: set[str] = set()
        out.update(self.static.get(anchor, {}).keys())
        out.update(self.cochange_index.neighbours(anchor))
        out.update(self._core_stem.get(core_stem(anchor), ()))
        for t in self._tokens.get(anchor, ()):
            # Generic tokens fan out to hundreds of files and contribute ~0 IDF
            # anyway; capping keeps generation bounded without changing the ranking.
            fs = self._by_stem_token.get(t, ())
            if len(fs) <= 30:
                out.update(fs)
        siblings = self._dir.get(directory(anchor), ())
        if len(siblings) <= dir_cap:
            out.update(siblings)
        out.discard(anchor)
        return out

    def score(self, anchor: str, c: str, w: RelationWeights) -> tuple[float, dict[str, float]]:
        parts = {
            "edge": self.rel_edge(anchor, c),
            "cochange": self.rel_cochange(anchor, c),
            "testlink": self.rel_testlink(anchor, c),
            "stem": self.rel_stem(anchor, c),
            "dir": self.rel_dir(anchor, c),
        }
        wd = w.as_dict()
        total = sum(wd[k] * v for k, v in parts.items())
        return total, parts
