"""Comparison systems, all emitting the shipped `Candidate` shape.

Every baseline goes through the same `apply_budget` with the same budget and the same
compactor, so `tokens` and `useful@budget` are measured symmetrically. A comparison
where one side pays for its context and the other does not is not a comparison.

  bm25        FTS5 Okapi BM25 over the same chunks. Pure lexical, no reranking.
  dense       LSA: tf-idf -> randomized truncated SVD -> cosine. Classical dense
              retrieval. NOT a neural code encoder -- see the honesty note below.
  rag         bm25 + dense fused by RRF. The standard hybrid-RAG configuration.
  hybrid      the shipped 1.10.0 pipeline. The strongest incumbent available here.
  graph       the shipped pipeline with `graph_source=True` AND PPR expansion forced
              on for every query. Forcing matters: commit-subject queries almost all
              classify as KEYWORD intent, whose plan sets `graph_strategy="none"`, so
              an unforced graph baseline would silently never activate and I would be
              beating a system that was switched off.

Honesty note on `dense`
-----------------------
No `sentence-transformers`, GPU, or network access exists in this environment, so the
dense baseline is Latent Semantic Analysis, not a modern neural encoder. LSA is a
legitimate dense retriever and the original one, but a code-tuned neural encoder would
very likely score higher. Therefore **no claim of the form "NUCLEUS beats embeddings"
is made anywhere in this work**. The load-bearing comparison is the paired one against
NUCLEUS's own anchor stage, which isolates accretion from retriever quality and would
hold on top of a better encoder too.
"""

from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from codebase_index.retrieval.budget import apply_budget
from codebase_index.retrieval.diversity import deduplicate
from codebase_index.retrieval.fusion import fuse
from codebase_index.retrieval.intent import detect_intent
from codebase_index.retrieval.pipeline import _diversify, _run_retrievers
from codebase_index.retrieval.rerank import rerank
from codebase_index.retrieval.skeleton import make_compactor
from codebase_index.retrieval.tuning import DEFAULT_TUNING, RetrievalTuning
from codebase_index.retrieval.types import Candidate

_TOK = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


def _subtokens(word: str) -> list[str]:
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", word).replace("_", " ").split()
    return [p.lower() for p in parts if len(p) >= 3]


def tokenize(text: str, *, cap: int = 4000) -> list[str]:
    out: list[str] = []
    for w in _TOK.findall(text or "")[:cap]:
        lw = w.lower()
        if len(lw) >= 3:
            out.append(lw)
        subs = _subtokens(w)
        if len(subs) > 1:
            out.extend(subs)
    return out


def finalize(
    candidates: list[Candidate], *, query: str, token_budget: int, limit: int,
    pool_paths: Optional[list[str]] = None,
) -> dict:
    """Shared tail: budget + payload, identical for every system under test.

    `pool_paths` is the *pre-truncation candidate pool*, which the oracle metrics are
    measured against. It must mean the same thing for every system or `oracle` and
    `cand_recall` become incomparable across the table; when a system does not
    distinguish a pool from its ranking, its full untruncated candidate list is the
    honest answer.
    """
    plan = detect_intent(query)
    ranked = candidates[:limit]
    compactor = make_compactor(intent=plan.intent, query=query, enabled=True,
                               min_reduction=0.25)
    results, recommended = apply_budget(ranked, token_budget=token_budget,
                                        compactor=compactor)
    if pool_paths is None:
        seen: list[str] = []
        for c in candidates:
            if c.path not in seen:
                seen.append(c.path)
        pool_paths = seen
    return {
        "query": query, "intent": plan.intent.value, "results": results,
        "recommended_reads": recommended, "confidence": "medium",
        "diagnostics": {"pool": [{"path": p} for p in pool_paths]},
    }


# --- BM25 --------------------------------------------------------------------


def _match_query(query: str) -> str:
    terms = {t.lower() for t in _TOK.findall(query) if len(t) >= 3}
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in sorted(terms))


def bm25_candidates(conn: sqlite3.Connection, query: str, *, limit: int) -> list[Candidate]:
    match = _match_query(query)
    if not match:
        return []
    try:
        rows = conn.execute(
            """
            SELECT f.path, c.line_start, c.line_end, c.content, c.token_est,
                   bm25(fts_chunks) AS s
            FROM fts_chunks
            JOIN chunks c ON c.id = fts_chunks.rowid
            JOIN files  f ON f.id = c.file_id
            WHERE fts_chunks MATCH ?
            ORDER BY s
            LIMIT ?
            """,
            (match, limit * 8),
        ).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for path, ls, le, content, tok, s in rows:
        out.append(Candidate(
            path=path.replace("\\", "/"), line_start=ls, line_end=le, source="fts",
            score=-float(s), content=content, token_est=int(tok or 0), reason="bm25",
        ))
    return out


# --- dense (LSA) -------------------------------------------------------------


@dataclass
class LSAIndex:
    """tf-idf -> randomized truncated SVD. numpy only, no scipy/sklearn available."""

    vocab: dict[str, int]
    idf: np.ndarray
    doc_emb: np.ndarray            # (n_docs, k), L2-normalised
    V: np.ndarray                  # (n_terms, k)
    meta: list[tuple[str, int, int, str, int]]

    @classmethod
    def build(cls, conn: sqlite3.Connection, *, k: int = 160, seed: int = 20260909) -> "LSAIndex":
        rows = conn.execute(
            """
            SELECT f.path, c.line_start, c.line_end, c.content, c.token_est
            FROM chunks c JOIN files f ON f.id = c.file_id
            ORDER BY c.id
            """
        ).fetchall()
        meta = [(r[0].replace("\\", "/"), int(r[1]), int(r[2]), r[3] or "", int(r[4] or 0))
                for r in rows]
        n = len(meta)
        if n == 0:
            return cls({}, np.zeros(0), np.zeros((0, k)), np.zeros((0, k)), meta)

        df: dict[str, int] = {}
        per_doc: list[dict[str, int]] = []
        for _, _, _, content, _ in meta:
            tf: dict[str, int] = {}
            for t in tokenize(content):
                tf[t] = tf.get(t, 0) + 1
            per_doc.append(tf)
            for t in tf:
                df[t] = df.get(t, 0) + 1

        # min_df 2 removes hapax noise; the upper bound removes terms so common they
        # carry no discrimination (language keywords, license headers).
        hi = max(3, int(0.30 * n))
        vocab = {t: i for i, t in enumerate(
            sorted(t for t, d in df.items() if 2 <= d <= hi)
        )}
        if not vocab:
            return cls({}, np.zeros(0), np.zeros((n, k)), np.zeros((0, k)), meta)
        idf = np.zeros(len(vocab), dtype=np.float32)
        for t, i in vocab.items():
            idf[i] = math.log(1.0 + n / df[t])

        rows_i: list[int] = []
        cols_i: list[int] = []
        vals_f: list[float] = []
        for d, tf in enumerate(per_doc):
            acc = []
            for t, c in tf.items():
                j = vocab.get(t)
                if j is not None:
                    acc.append((j, (1.0 + math.log(c)) * idf[j]))
            if not acc:
                continue
            norm = math.sqrt(sum(v * v for _, v in acc)) or 1.0
            for j, v in acc:
                rows_i.append(d)
                cols_i.append(j)
                vals_f.append(v / norm)
        R = np.asarray(rows_i, dtype=np.int32)
        C = np.asarray(cols_i, dtype=np.int32)
        Vl = np.asarray(vals_f, dtype=np.float32)
        m = len(vocab)
        k = min(k, max(2, min(n, m) - 1))

        rng = np.random.default_rng(seed)

        def A_dot(X: np.ndarray) -> np.ndarray:          # (m,k) -> (n,k)
            out = np.zeros((n, X.shape[1]), dtype=np.float32)
            for s in range(0, len(R), 200_000):
                e = s + 200_000
                np.add.at(out, R[s:e], Vl[s:e, None] * X[C[s:e]])
            return out

        def AT_dot(X: np.ndarray) -> np.ndarray:         # (n,k) -> (m,k)
            out = np.zeros((m, X.shape[1]), dtype=np.float32)
            for s in range(0, len(R), 200_000):
                e = s + 200_000
                np.add.at(out, C[s:e], Vl[s:e, None] * X[R[s:e]])
            return out

        Omega = rng.standard_normal((m, k)).astype(np.float32)
        Y = A_dot(Omega)
        Y = A_dot(AT_dot(Y))                              # one power iteration
        Q, _ = np.linalg.qr(Y)
        BT = AT_dot(Q)                                    # (m,k) == B^T
        Ub, Sb, Vbt = np.linalg.svd(BT, full_matrices=False)
        V = Ub                                            # (m,k) right singular vecs of A
        doc = A_dot(V)
        norms = np.linalg.norm(doc, axis=1, keepdims=True)
        doc = doc / np.maximum(norms, 1e-8)
        return cls(vocab, idf, doc.astype(np.float32), V.astype(np.float32), meta)

    def query(self, text: str, *, limit: int) -> list[Candidate]:
        if not self.vocab or self.doc_emb.size == 0:
            return []
        tf: dict[str, int] = {}
        for t in tokenize(text):
            tf[t] = tf.get(t, 0) + 1
        vec = np.zeros(len(self.vocab), dtype=np.float32)
        for t, c in tf.items():
            j = self.vocab.get(t)
            if j is not None:
                vec[j] = (1.0 + math.log(c)) * self.idf[j]
        nrm = float(np.linalg.norm(vec))
        if nrm <= 0:
            return []
        q = (vec / nrm) @ self.V
        qn = float(np.linalg.norm(q))
        if qn <= 0:
            return []
        sims = self.doc_emb @ (q / qn)
        take = min(limit * 8, sims.shape[0])
        idx = np.argpartition(-sims, take - 1)[:take]
        idx = idx[np.argsort(-sims[idx])]
        out = []
        for i in idx:
            path, ls, le, content, tok = self.meta[int(i)]
            out.append(Candidate(
                path=path, line_start=ls, line_end=le, source="vector",
                score=float(sims[int(i)]), content=content, token_est=tok,
                reason="lsa cosine",
            ))
        return out


# --- shipped pipeline variants ----------------------------------------------


def product_candidates(
    conn: sqlite3.Connection, query: str, *, limit: int, tuning: RetrievalTuning,
    force_graph: bool = False,
) -> tuple[list[Candidate], list[str]]:
    """Returns (ranked candidates, pre-rerank pool paths)."""
    plan = detect_intent(query)
    pool_mult = max(1, tuning.candidate_pool_multiplier)
    pool_limit = limit if pool_mult == 1 else max(limit * pool_mult, 20)
    lists, weights = _run_retrievers(
        conn, query, mode="hybrid", limit=pool_limit, weights=plan.weights,
        backend=None, tuning=tuning, graph_depth=tuning.graph_depth,
        graph_node_cap=tuning.graph_node_cap,
        graph_strategy=(
            ("both" if force_graph else plan.graph_strategy)
            if tuning.graph_source else "none"
        ),
    )
    fused = fuse(lists, weights=weights, k=tuning.rrf_k,
                 file_agreement=tuning.file_agreement_weight if tuning.file_agreement else 0.0)
    pool_paths: list[str] = []
    for c in fused:
        p = c.path.replace("\\", "/")
        if p not in pool_paths:
            pool_paths.append(p)
    ranked = rerank(fused, query=query, intent=plan.intent, tuning=tuning)
    if tuning.dedup:
        ranked = deduplicate(ranked, hamming_distance=tuning.dedup_hamming)
    ranked = _diversify(ranked, per_file=tuning.max_per_file)
    return ranked, pool_paths


def rrf_hybrid(a: list[Candidate], b: list[Candidate], *, k: int = 60) -> list[Candidate]:
    return fuse({"fts": a, "vector": b}, weights={"fts": 1.0, "vector": 1.0}, k=k,
                file_agreement=0.0)


# --- graph PPR baseline uses the shipped pipeline with graph_source on -------

GRAPH_TUNING = RetrievalTuning(graph_source=True)
