"""Retrieval tuning knobs — the ablation contract.

Every ranking signal added after 1.7.0 sits behind a flag here so it can be
switched off independently and measured (`tests/eval/run_eval.py --ablate`).
A signal that cannot demonstrate a win in the eval harness does not ship.

`RetrievalTuning.baseline()` reproduces the pre-1.8.0 pipeline byte-for-byte and
is the honest "before" column in every benchmark table.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace


@dataclass(frozen=True)
class RetrievalTuning:
    """Immutable retrieval configuration.

    Invariants:
      * Every field is either a bool feature flag or a bounded numeric parameter.
      * Defaults are the shipped configuration, chosen by benchmark, not taste.
      * `baseline()` must keep matching the 1.7.0 behaviour; the ablation table is
        meaningless if the baseline drifts.
    """

    # --- candidate generation ------------------------------------------------
    fuzzy_symbols: bool = True
    """Acronym / concatenation / edit-distance identifier matching in the symbol
    retriever, so `userid` and `get user` both reach `getUserById`.

    Runs only as a *recall fallback* (see `fuzzy_fallback_min`). Measured on 305
    queries across three repositories it changed no ranking metric while costing
    ~20% of query latency, because real queries name identifiers correctly often
    enough that the precise lookup already answers them. Gating it behind an
    empty-handed precise lookup keeps the typo/acronym capability at ~zero cost.
    """
    fuzzy_threshold: float = 0.55
    """Minimum identifier similarity for fuzzy symbol candidates."""

    fuzzy_fallback_min: int = 3
    """Run fuzzy identifier matching only when the precise symbol lookup returned
    fewer than this many rows and found no exact match. 0 restores always-on."""

    query_expansion: bool = True
    """Down-weighted code-synonym expansion (auth->authentication, ...). Original
    terms always keep a strictly higher weight so precision is preserved."""

    graph_source: bool = False
    """Personalized-PageRank candidate source seeded from lexical/symbol hits.
    Disabled by default: the self-repository ablation showed lower MRR when
    architectural neighbors displaced direct lexical hits.
    """

    soft_lexical: bool = True
    """Coverage-scored lexical matching instead of a hard AND over every term.

    Measured cause of the baseline's concept-query collapse: a question like
    "how does incremental update avoid reparsing everything" AND-ed five terms,
    two of which ("avoid", "everything") appear in no code chunk, so FTS returned
    nothing from the target file. Soft matching requires a *fraction* of terms and
    ranks by how many matched."""

    min_term_coverage: float = 0.5
    """Fraction of salient query terms a chunk must contain under soft matching."""

    candidate_pool_multiplier: int = 2
    """Over-fetch factor for the pre-selection candidate pool.

    Selection stages (dedup, MMR, per-file diversification) drop or reorder
    candidates, so the pool must be wider than the requested limit or the page
    ends up short. Previously this widening was an implicit side effect of
    `dedup or mmr` being enabled; making it explicit is what let the ablation
    show that the measured "dedup win" was really a pool-size win.
    """
    # --- selection -----------------------------------------------------------
    mmr: bool = False
    """Maximal Marginal Relevance re-selection of the ranked list.
    Disabled by default: the benchmark's direct file-level metrics favored
    relevance-only selection; enable it when snippet diversity is the priority.
    """

    mmr_lambda: float = 0.7
    """MMR relevance/diversity trade-off. 1.0 == pure relevance (no diversity)."""

    dedup: bool = True
    """SimHash near-duplicate suppression across returned chunks."""

    dedup_hamming: int = 3
    """Max Hamming distance between 64-bit SimHashes still considered duplicate."""

    source_priors: bool = True
    """Prefer implementation files over their tests and over prose docs when both
    match a code question. Measured: tests/test_fusion.py outranked fusion.py."""

    file_agreement: bool = True
    """Credit a candidate for retrievers that found its *file* at another locator.

    RRF fuses on (path, line-bucket), but a symbol hit at line 40 and a lexical
    hit at line 120 in the same file land in different buckets, so cross-retriever
    agreement — the entire point of fusion — never fired. This adds the missing
    evidence back at reduced weight without double-counting a retriever already
    counted at the candidate's own locator."""

    file_agreement_weight: float = 0.4
    """Discount applied to same-file, different-locator evidence. Tuned on 305
    queries over three repositories; the 0.3-0.6 plateau peaks here."""

    # --- fixed parameters ----------------------------------------------------
    rrf_k: int = 60
    max_per_file: int = 3
    graph_damping: float = 0.85
    graph_iterations: int = 12
    graph_weight: float = 0.1
    expansion_weight: float = 0.35
    graph_depth: int = 2
    graph_node_cap: int = 40

    @classmethod
    def baseline(cls) -> RetrievalTuning:
        return cls(
            fuzzy_symbols=False,
            query_expansion=False,
            graph_source=False,
            soft_lexical=False,
            mmr=False,
            dedup=False,
            source_priors=False,
            file_agreement=False,
            # 1.7.0 had no over-fetch: the pool was exactly the requested page.
            candidate_pool_multiplier=1,
        )

    def without(self, flag: str) -> RetrievalTuning:
        """Return a copy with one boolean signal disabled (single-signal ablation)."""
        field_names = {f.name for f in fields(self)}
        if flag not in field_names:
            raise KeyError(f"unknown tuning flag: {flag!r}")
        value = getattr(self, flag)
        if not isinstance(value, bool):
            raise TypeError(f"tuning flag {flag!r} is not a boolean signal")
        return replace(self, **{flag: False})


DEFAULT_TUNING = RetrievalTuning()
"""Module-level default so call sites never construct ad-hoc tunings."""
