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
    terms always keep a strictly higher weight so precision is preserved.

    1.10.0 tried to delete this. On the 420-query git-derived benchmark the
    vocabulary is worth nothing measurable — MRR -0.0022 (p=0.40) when removed —
    and the flag's apparent +0.006 turned out to come from it also swapping the
    symbol retriever's tokenizer, not from the synonyms.

    It survives because the git benchmark cannot see what it does. A commit
    subject is written by someone looking at the identifiers they just changed,
    so it reuses the codebase's own spelling; a user asking a question does not.
    On the 36 hand-written natural-language queries — the only set that phrases
    things the way a person would — removing the vocabulary cost -0.060 MRR,
    because "where are secrets redacted" has to reach `redact_snippet` and
    "how does authentication work" has to reach `auth/`. Both benchmark families
    are needed to make this call, and only one of them can measure this."""

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

    name_cooccurrence: bool = True
    """Reward query terms that co-occur in one candidate *name* (file basename +
    symbol), superlinearly, over and above their independent per-term matches.

    RRF sums independent per-term verdicts, so it cannot distinguish a candidate
    that matched one query term very well from one that matched three terms in a
    single name. Measured over eight repositories and 420 queries, that confusion
    was the largest single reranking loss: the correct answer sat in the candidate
    pool with a better name-level match and lost to a one-term winner.

    See `retrieval/features.py` for the feature and the variants it beat."""

    name_cooccurrence_weight: float = 1.8
    """Bonus at full co-occurrence (every query term present in one name).

    Chosen on a plateau, not at a peak. Pooled MRR rises to w≈1.8 and then flattens
    (0.599 at 1.8, 0.603 at 4.0, saturating at 0.603 beyond); past 1.8 the extra
    movement is churn, with per-query wins flat and losses nearly doubling
    (37W/19L at 1.8 against 39W/32L at 4.0), because a larger bonus turns the
    feature into the primary sort key and reduces fusion to a tiebreak. Every
    value in 1.0-4.0 leaves all eight corpora at or above 1.9.0; 1.8 is the
    interior of that region with the strongest significance (p=0.004)."""

    name_cooccurrence_demoted_scale: float = 0.5
    """Fraction of the co-occurrence bonus granted to test/generated sources.

    1.0 lets descriptive test function names outrank implementations on questions
    like "where are secrets redacted before output"; 0.0 over-corrects, since on
    git-derived ground truth the changed file often *is* the test.

    Decided by splitting the benchmark on whether its own ground truth is a test:
    across the 261 queries whose answer is *not* a test, the gain is flat at
    +0.020 MRR for every scale, so the whole aggregate difference between 0.5 and
    1.0 comes from the 159 test-answer queries — an artifact of mining ground
    truth from commits, which touch tests. 0.5 is the only setting that improves
    both partitions (+0.015 test-answer, +0.020 implementation-answer)."""

    resource_priors: bool = True
    """Extend the source priors past code/test/docs: localisation catalogues and
    workflow artifacts (review diffs, patches, agent scratch directories) are
    demoted to the level of generated code.

    Found on a Minecraft monorepo: for "how does the town treasury work" the page
    held the English and Russian language files (every UI string about the treasury
    lives there) and five review diffs of the commits that built it, while the
    SavedData class the question was about fell off the page.

    A wider variant also stripped data files (`.json`, `.yml`) of the implementation
    bonus; it cost TerraForge a query whose answer is `.github/workflows/release.yml`
    and was dropped: configuration is sometimes the answer."""

    stem_match: bool = True
    """Credit a file whose name *is* one of the query terms (`Treasury.java` for
    "how does the treasury store items"). Name co-occurrence deliberately gives a
    single matched term nothing, and the symbol bonus only fires for symbol-level
    hits, so a file-level chunk of the class named after the subject got no credit
    for it."""

    stem_match_weight: float = 0.20
    """Bonus for a file stem equal to a query term; see `stem_match`.

    Swept 0.10 / 0.20 / 0.30 over 342 queries on six query sets: 0.20 improved or
    held every corpus; 0.30 added recall on two and cost terra-incognita MRR."""

    candidate_pool_floor: int = 20
    """Minimum candidate pool when the pool is over-fetched (multiplier > 1)."""

    question_pool_floor: int = 40
    """Candidate-pool floor for a question-form query (see `intent.is_question`).

    On 24 natural-language questions over a 5.9k-file monorepo, a 40-deep pool
    raised MRR 0.436 -> 0.472 and recall@10 0.750 -> 0.833: the class a question
    paraphrases is often ranked 20-40 by every retriever and only the reranker's
    name signals can lift it. On 318 commit-subject queries a 40-deep pool was
    MRR-neutral (-0.009, p=0.36) at +17 ms p50, so the wider pool is spent only
    where it pays. 0 disables it."""

    # --- selection, continued -----------------------------------------------
    max_per_file: int = 1
    """Hits from one file kept in place before the rest are pushed to the tail.

    The agent's unit of decision is "which file do I open", so a page of 10
    results that spends three slots on three regions of one file offers seven
    choices, not ten. Measured across eight repositories the page held 7.1
    distinct files on average, and 45 of 57 queries whose answer was in the
    candidate pool but absent from the page had it sitting past rank 10.

    Monotone over 1-5 (1 > 2 > 3 > 4 > 5), so this is a plateau boundary rather
    than a fitted peak: recall@10 +0.045 and nDCG@10 +0.015 against 3, at
    unchanged token cost and with no metric or corpus regressing. Nothing is
    dropped — overflow hits keep their relative order at the tail — so a file
    with several relevant regions still surfaces them below the first page.
    """

    # --- fixed parameters ----------------------------------------------------
    rrf_k: int = 60
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
            name_cooccurrence=False,
            # 1.7.0 had no over-fetch: the pool was exactly the requested page,
            # and it kept up to three hits from any one file.
            candidate_pool_multiplier=1,
            max_per_file=3,
            resource_priors=False,
            stem_match=False,
            question_pool_floor=0,
        )

    @classmethod
    def v190(cls) -> RetrievalTuning:
        """The 1.9.0 shipped configuration, as the immutable "before" column.

        `baseline()` reaches back to 1.7.0 and answers "was any of this worth it";
        this answers the narrower question every 1.10.0 change is judged on: is it
        better than the release it replaces. Both must keep working, so a later
        default change can never silently redefine its own comparison point.
        """
        return cls(
            name_cooccurrence=False, max_per_file=3,
            resource_priors=False, stem_match=False, question_pool_floor=0,
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
