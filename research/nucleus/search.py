"""NUCLEUS retrieval: nucleate -> accrete -> select.

The pipeline deliberately reuses the shipped retrieval stack for the *anchor* stage.
That is not laziness: the claim under test is about composition, not about lexical
matching, so the anchor stage must be the incumbent's best configuration or the
comparison is rigged. With `accrete=False` this module reproduces
`codebase_index.retrieval.pipeline.search` result-for-result — `test_nucleus.py`
asserts it — so every measured delta is attributable to accretion and selection alone.

Three stages:

  NUCLEATE  the incumbent hybrid retriever produces a ranked candidate list; the
            head of it is treated as anchors (high precision, low recall).

  ACCRETE   candidates related to the anchors are scored by the relation union
            (`relations.RelationGraph`) *conditioned on the anchors, not the query*.
            This is the stage that can retrieve a file sharing no vocabulary with
            the question.

  SELECT    accreted candidates compete for their own slot budget by coverage gain
            per token, so completions do not duplicate each other's obligations.

The budget separation is the point. Completions are appended behind a frozen anchor
head, so a completion can only ever take a slot a *lower-ranked baseline result*
would have held. The documented failure mode of graph retrieval in this codebase
(`tuning.graph_source = False`: "architectural neighbors displaced direct lexical
hits") is excluded structurally rather than by tuning.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Optional

from codebase_index.retrieval.budget import apply_budget
from codebase_index.retrieval.diversity import deduplicate, mmr_select
from codebase_index.retrieval.fusion import fuse
from codebase_index.retrieval.intent import detect_intent
from codebase_index.retrieval.pipeline import _confidence, _diversify, _run_retrievers
from codebase_index.retrieval.rerank import rerank
from codebase_index.retrieval.skeleton import make_compactor
from codebase_index.retrieval.tuning import DEFAULT_TUNING, RetrievalTuning
from codebase_index.retrieval.types import Candidate

from .relations import RelationGraph, RelationWeights, stem_tokens

_TERM_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class NucleusParams:
    """Accretion configuration. Every field is an ablation switch."""

    accrete: bool = True
    anchor_head: int = 3
    """Baseline results whose rank is frozen. Completions are inserted after these."""

    max_completions: int = 3
    """Completions to append.

    Under the eviction policy this had to be 1: `diagnose_slots.py` showed the
    marginal precision of the second and third completion (0.0166 and 0.0072
    gold/query) fell below the cost of the rank-9 and rank-8 slots they evicted
    (0.0339, 0.0247). Appending removes the eviction cost, so the binding constraint
    becomes tokens and more completions become affordable. Ablated at 1/2/3."""

    append_only: bool = True
    """Add completions beyond the baseline page instead of evicting for them.

    The slot framing was wrong. `diagnose_slots.py` shows every eviction is a losing
    trade, but that is an artifact of a fixed 10-slot page: the agent's real budget is
    tokens, and the incumbent spends only ~1093 of 1500. Rendered as contract slices
    rather than code chunks (`_completion_slice`), a completion costs a fraction of a
    chunk and evicts nothing, so its expected value no longer has to beat a rank slot
    -- only its own token cost. Compared honestly against a baseline allowed the same
    page size and the same budget."""

    compact_completions: bool = True
    """Render completions as signatures (H8) rather than bodies."""

    insert_at: str = "tail"
    """Where completions go.

    'after_head' inserts at `anchor_head + 1`, which shifts every baseline result
    below it down by one. That is what made the first benchmark run lose: it left
    recall unchanged while damaging MRR/nDCG/P@5, because a gold file at rank 4
    (density 0.096) was being pushed to rank 5+ to make room for a completion with
    precision 0.073. 'tail' spends only the last slot, whose gold density is the
    lowest on the page (0.035), and cannot reorder anything above it."""

    min_score: float = 0.6
    """Gate, selected under leave-one-repository-out by `fit_gate.py`.

    Accretion proposes nothing at all on 58% of queries, and where it does propose,
    its score is well calibrated: precision rises from 0.073 (fire always) to 0.353
    (fire on the top-scoring 10%). The gate converts a signal that is only 2.1x the
    slot cost on average into one that is several times the slot cost when it spends.

    0.6 was chosen in 7 of 8 leave-one-repository-out folds (the eighth chose 0.7)
    and sits on a plateau: net gold/query is flat at 0.021-0.024 for every tau in
    [0, 1.1]. It is a plateau interior, not a peak, which is the only kind of fitted
    value worth shipping."""

    weights: RelationWeights = RelationWeights()

    anchor_decay: float = 1.0
    """Anchor i gets weight 1/(1 + decay*i): rank-1 evidence outweighs rank-3."""

    combine: str = "sum"
    """'sum' rewards a candidate related to several anchors (evidence of belonging to
    one change-set); 'max' treats relations as independent. Ablated."""

    hub_penalty: bool = True
    """Divide by sqrt(relation degree): a file related to everything is evidence for
    nothing. The graph-retrieval god-node failure mode in miniature."""

    coverage_select: bool = True
    """H2: pick completions by coverage gain per token rather than by score alone."""


# --- obligations -------------------------------------------------------------


class ObligationIndex:
    """path -> the set of symbol/identifier obligations that file participates in.

    Obligations are the latent objects the coverage objective is defined over. They
    are approximated by identifiers, which is crude but has the two properties the
    objective needs: shared obligations really do indicate "these files implement one
    contract", and it costs one query per corpus to build.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.cov: dict[str, set[str]] = {}
        for path, name in conn.execute(
            "SELECT f.path, s.name FROM symbols s JOIN files f ON f.id = s.file_id"
        ):
            self.cov.setdefault(_norm(path), set()).add(name.lower())
        for path, name in conn.execute(
            "SELECT f.path, e.dst_name FROM edges e JOIN files f ON f.id = e.file_id "
            "WHERE e.dst_name IS NOT NULL"
        ):
            self.cov.setdefault(_norm(path), set()).add(str(name).lower())
        for path in list(self.cov):
            self.cov[path] |= stem_tokens(path)

    def of(self, path: str) -> set[str]:
        p = _norm(path)
        if p not in self.cov:
            self.cov[p] = set(stem_tokens(p))
        return self.cov[p]


def _norm(p: str) -> str:
    return p.replace("\\", "/")


# --- completion snippets -----------------------------------------------------


def _completion_slice(
    conn: sqlite3.Connection, path: str
) -> Optional[tuple[int, int, str, int, Optional[str]]]:
    """A file's *contract*: its declarations, not its body (hypothesis H8).

    An accreted file is proposed because something the agent is already looking at is
    coupled to it -- not because it matched the question. What the agent needs is
    enough to decide whether to open it: what lives here, and what it is called. A
    signature digest answers that in a fraction of the tokens a code chunk costs, and
    the ratio is what makes appending completions affordable at all.
    """
    rows = conn.execute(
        """
        SELECT s.name, s.kind, s.signature, s.line_start, s.line_end
        FROM symbols s JOIN files f ON f.id = s.file_id
        WHERE f.path = ?
        ORDER BY (s.parent_id IS NOT NULL), s.line_start
        LIMIT 8
        """,
        (path,),
    ).fetchall()
    if not rows:
        return None
    lines = [f"# {path} (related to your anchors; contract only)"]
    for name, kind, sig, ls, _le in rows:
        text = (sig or name or "").strip().splitlines()[0][:140] if (sig or name) else ""
        if text:
            lines.append(f"{ls}: {kind or 'symbol'} {text}")
    body = "\n".join(lines)
    if len(lines) <= 1:
        return None
    first, last = int(rows[0][3]), int(rows[-1][4])
    # Matches the indexer's estimator (~4 chars/token) so the accounting stays
    # symmetric with every other result on the page.
    return (first, max(first, last), body, max(1, len(body) // 4), rows[0][0])


def _completion_chunk(
    conn: sqlite3.Connection, path: str, terms: set[str]
) -> Optional[tuple[int, int, str, int, Optional[str]]]:
    """Best chunk of `path` to show for an accreted file.

    An accreted file frequently shares no vocabulary with the query — that is the
    whole reason it had to be reached by relation rather than by search. When no
    chunk matches a query term we fall back to the file's first symbol-bearing chunk,
    i.e. its declaration/header region, which is the most informative fixed-size
    window for orienting an agent that has never seen the file.
    """
    rows = conn.execute(
        """
        SELECT c.line_start, c.line_end, c.content, c.token_est, c.symbol_names
        FROM chunks c JOIN files f ON f.id = c.file_id
        WHERE f.path = ?
        ORDER BY c.line_start
        """,
        (path,),
    ).fetchall()
    if not rows:
        return None
    best = None
    best_hits = 0
    for r in rows:
        content = (r[2] or "").lower()
        hits = sum(1 for t in terms if t and t in content)
        if hits > best_hits:
            best_hits, best = hits, r
    if best is None:
        for r in rows:
            if (r[4] or "").strip():
                best = r
                break
        best = best or rows[0]
    return (int(best[0]), int(best[1]), best[2] or "", int(best[3] or 0), best[4])


# --- accretion ---------------------------------------------------------------


def accrete(
    conn: sqlite3.Connection,
    *,
    anchors: list[str],
    graph: RelationGraph,
    obligations: ObligationIndex,
    params: NucleusParams,
    exclude: set[str],
    query_terms: set[str],
) -> list[tuple[str, float, dict[str, float]]]:
    """Score files related to the anchor set. Returns [(path, score, parts)] desc."""
    if not anchors:
        return []
    contrib = contributions(anchors=anchors, graph=graph, params=params, exclude=exclude)
    ranked = rank_contributions(contrib, weights=params.weights, min_score=params.min_score)
    return ranked


def contributions(
    *, anchors: list[str], graph: RelationGraph, params: NucleusParams,
    exclude: set[str],
) -> dict[str, dict[str, float]]:
    """Per-candidate, per-relation evidence, aggregated over anchors.

    Deliberately kept **linear in the relation weights**: the score is
    `sum_r theta_r * contrib[c][r]`, so refitting theta never requires re-walking the
    graph. That is what makes the leave-one-repository-out fit in `fit_weights.py`
    affordable, and it means the fitted weights are fitted against exactly the
    quantities the retriever will use at query time.

    The hub normaliser is folded in here (not applied to the final score) so it scales
    every relation identically and cannot be confused with a relation weight.
    """
    contrib: dict[str, dict[str, float]] = {}
    for i, a in enumerate(anchors):
        alpha = 1.0 / (1.0 + params.anchor_decay * i)
        for c in graph.candidates(a):
            if c in exclude:
                continue
            _s, parts = graph.score(a, c, params.weights)
            if not any(parts.values()):
                continue
            acc = contrib.setdefault(c, {})
            for k, v in parts.items():
                if v <= 0.0:
                    continue
                if params.combine == "max":
                    acc[k] = max(acc.get(k, 0.0), alpha * v)
                else:
                    acc[k] = acc.get(k, 0.0) + alpha * v

    if params.hub_penalty:
        # A file reachable from several anchors is genuine evidence; a file reachable
        # from *everything* is a hub. The normaliser is the candidate's total relation
        # degree over the corpus, so multi-anchor support is still rewarded while a
        # god-node is damped -- the graph-retrieval failure mode in miniature.
        for c, acc in contrib.items():
            deg = len(graph.static.get(c, {})) + len(graph.cochange_index.neighbours(c))
            f = (1.0 + deg) ** 0.5
            for k in acc:
                acc[k] /= f
    return contrib


def rank_contributions(
    contrib: dict[str, dict[str, float]], *, weights: RelationWeights, min_score: float,
) -> list[tuple[str, float, dict[str, float]]]:
    wd = weights.as_dict()
    scored = [
        (p, sum(wd.get(k, 0.0) * v for k, v in acc.items()), acc)
        for p, acc in contrib.items()
    ]
    scored.sort(key=lambda t: (-t[1], t[0]))
    return [t for t in scored if t[1] >= min_score]


def _select_completions(
    ranked: list[tuple[str, float, dict[str, float]]],
    *,
    covered: set[str],
    obligations: ObligationIndex,
    params: NucleusParams,
    conn: sqlite3.Connection,
    query_terms: set[str],
) -> list[tuple[str, float, dict[str, float]]]:
    """H2: budgeted greedy coverage over obligations, instead of plain top-C.

    Score alone will happily pick three files that all cover the same contract. The
    marginal-gain rule prefers a slightly weaker candidate that covers something not
    yet covered, which is what "minimal sufficient set" means operationally.
    """
    if not params.coverage_select:
        return ranked[: params.max_completions]

    chosen: list[tuple[str, float, dict[str, float]]] = []
    seen = set(covered)
    pool = list(ranked[: params.max_completions * 6])
    while pool and len(chosen) < params.max_completions:
        best = None
        best_gain = -1.0
        for item in pool:
            path, score, _ = item
            new = obligations.of(path) - seen
            # Marginal value per unit of score-normalised novelty. Token cost is
            # nearly constant across chunks here (chunking is size-bounded), so
            # novelty is the term that actually discriminates; keeping score as a
            # multiplier stops a junk file with exotic identifiers from winning.
            gain = score * (1.0 + len(new)) ** 0.5
            if gain > best_gain:
                best_gain, best = gain, item
        if best is None:
            break
        chosen.append(best)
        seen |= obligations.of(best[0])
        pool.remove(best)
    return chosen


# --- the pipeline ------------------------------------------------------------


def nucleus_search(
    conn: sqlite3.Connection,
    query: str,
    *,
    mode: str = "hybrid",
    limit: int = 10,
    token_budget: int = 1500,
    tuning: Optional[RetrievalTuning] = None,
    graph: Optional[RelationGraph] = None,
    obligations: Optional[ObligationIndex] = None,
    params: NucleusParams = NucleusParams(),
    explain: bool = False,
) -> dict:
    tuning = tuning or DEFAULT_TUNING
    plan = detect_intent(query)
    base_limit = limit
    if token_budget <= 0:
        token_budget = plan.token_budget

    # --- NUCLEATE: the incumbent pipeline, unmodified -----------------------
    pool_mult = max(1, tuning.candidate_pool_multiplier)
    pool_limit = limit if pool_mult == 1 else max(limit * pool_mult, 20)
    lists, weights = _run_retrievers(
        conn, query, mode=mode, limit=pool_limit, weights=plan.weights,
        backend=None, tuning=tuning, graph_depth=tuning.graph_depth,
        graph_node_cap=tuning.graph_node_cap, graph_strategy=plan.graph_strategy,
    )
    fused = fuse(lists, weights=weights, k=tuning.rrf_k,
                 file_agreement=tuning.file_agreement_weight if tuning.file_agreement else 0.0)
    pool_paths: list[str] = []
    for c in fused:
        p = _norm(c.path)
        if p not in pool_paths:
            pool_paths.append(p)
    ranked = rerank(fused, query=query, intent=plan.intent, tuning=tuning)
    if tuning.dedup:
        ranked = deduplicate(ranked, hamming_distance=tuning.dedup_hamming)
    if tuning.mmr:
        ranked = mmr_select(ranked, limit, tuning.mmr_lambda)
    else:
        ranked = _diversify(ranked, per_file=tuning.max_per_file)
    baseline = ranked[:base_limit]

    accretion_log: list[dict] = []
    final = baseline

    # --- ACCRETE + SELECT ---------------------------------------------------
    if params.accrete and graph is not None and obligations is not None and baseline:
        terms = {t.lower() for t in _TERM_RE.findall(query) if len(t) > 2}
        head = baseline[: params.anchor_head]
        anchors: list[str] = []
        for c in head:
            p = _norm(c.path)
            if p not in anchors:
                anchors.append(p)
        # Only files already on the page are excluded from accretion; a file the
        # baseline ranked below the page is a legitimate promotion target.
        on_page = {_norm(c.path) for c in head}
        if params.insert_at != "after_head":
            # With tail placement a "promotion" from mid-page to the last slot is a
            # demotion, not a gain, so only genuinely new files are worth a slot.
            on_page = {_norm(c.path) for c in baseline}
        covered: set[str] = set(terms)
        for a in anchors:
            covered |= obligations.of(a)

        cands = accrete(
            conn, anchors=anchors, graph=graph, obligations=obligations,
            params=params, exclude=on_page, query_terms=terms,
        )
        picked = _select_completions(
            cands, covered=covered, obligations=obligations, params=params,
            conn=conn, query_terms=terms,
        )

        split = params.anchor_head if params.insert_at == "after_head" else len(baseline)
        tail = baseline[split:]
        tail_by_path: dict[str, Candidate] = {}
        for c in baseline[params.anchor_head:]:
            tail_by_path.setdefault(_norm(c.path), c)

        promoted: list[Candidate] = []
        consumed: set[int] = set()
        for path, score, parts in picked:
            existing = tail_by_path.get(path)
            if existing is not None:
                # Promotion: reuse the baseline candidate so its query-matched
                # snippet (better than a synthesized one) is preserved.
                promoted.append(existing)
                consumed.add(id(existing))
            else:
                chunk = None
                if params.compact_completions:
                    chunk = _completion_slice(conn, path)
                if chunk is None:
                    chunk = _completion_chunk(conn, path, terms)
                if chunk is None:
                    continue
                ls, le, content, tok, symnames = chunk
                why = ",".join(f"{k}={v:.2f}" for k, v in sorted(parts.items()) if v > 0)
                promoted.append(
                    Candidate(
                        path=path, line_start=ls, line_end=le, source="accretion",
                        score=score, kind=None,
                        symbol=(symnames or "").split()[0] if symnames else None,
                        content=content, token_est=tok,
                        reason=f"accreted from anchors ({why})",
                    )
                )
            accretion_log.append({"path": path, "score": round(score, 4), "parts": parts})

        if params.append_only:
            # Nothing is evicted; the page grows and the token budget arbitrates.
            final = [c for c in baseline if id(c) not in consumed] + promoted
        elif params.insert_at == "after_head":
            rest = [c for c in tail if id(c) not in consumed]
            final = (head + promoted + rest)[:limit]
        else:
            # Tail placement: completions claim the last `len(promoted)` slots of the
            # page and nothing above them moves. When the baseline under-fills the
            # page the slots are free and nothing is evicted at all.
            kept = [c for c in baseline if id(c) not in consumed]
            keep_n = max(0, limit - len(promoted))
            final = kept[:keep_n] + promoted

    confidence = _confidence(final)
    compactor = make_compactor(intent=plan.intent, query=query, enabled=True,
                               min_reduction=0.25)
    results, recommended = apply_budget(final, token_budget=token_budget,
                                        compactor=compactor)

    payload: dict = {
        "query": query,
        "intent": plan.intent.value,
        "mode": mode,
        "confidence": confidence.value,
        "results": results,
        "recommended_reads": recommended,
        "fallback_suggestions": {},
    }
    if explain:
        payload["diagnostics"] = {
            "pool": [{"path": p} for p in pool_paths],
            "pool_size": len(pool_paths),
            "accreted": accretion_log,
        }
    return payload
