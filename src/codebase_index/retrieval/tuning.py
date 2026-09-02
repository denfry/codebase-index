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
    retriever, so `userid` and `get user` both reach `getUserById`."""
    fuzzy_threshold: float = 0.55
    """Minimum identifier similarity for fuzzy symbol candidates."""

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
        )

    def without(self, flag: str) -> RetrievalTuning:
        """Return a copy with one boolean signal disabled (single-signal ablation)."""
        field_names = {f.name for f in fields(self)}
        if flag not in field_names:
            raise KeyError(f"unknown tuning flag: {flag!r}")
        return replace(self, **{flag: False})


DEFAULT_TUNING = RetrievalTuning()
"""Module-level default so call sites never construct ad-hoc tunings."""
