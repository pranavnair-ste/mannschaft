"""Persistent topology: session_id tags trajectory + corpus subset for reuse."""
from __future__ import annotations

from pi_harness.corpus.format import Classification
from pi_harness.topology.base import DEFAULT_PRIME_TOKEN_BUDGET, RunSpec, TaskDef
from pi_harness.topology.sequential import SequentialTopology


class PersistentTopology(SequentialTopology):
    """Sequential shape, but binds the run to a session_id used by Plan 3's
    corpus reader to filter prime entries and by Plan 4's improve runner to
    append back into the same session subset.

    This IS pillar 1's storage mechanism — runs in the same session compound."""

    def plan(self, spec: RunSpec, depth: int = 0) -> list[TaskDef]:
        if not spec.session_id:
            raise ValueError(
                "PersistentTopology requires RunSpec.session_id to bind the "
                "run to a session for corpus + trajectory reuse"
            )
        return super().plan(spec, depth=depth)

    def build_template_dict(self, spec: RunSpec) -> dict:
        dct = super().build_template_dict(spec)
        dct["template"].setdefault("metadata", {})["session_id"] = spec.session_id
        return dct

    def prime_corpus(self, spec: RunSpec, reader) -> list:
        """Wrapper around the corpus reader's prime that forces the session_id filter.

        Persistent runs prime from their own session's accumulated knowledge plus
        global (session-less) entries — see CorpusReader.prime session semantics.
        """
        classifications = (
            [Classification(c) for c in spec.corpus_classifications]
            if spec.corpus_classifications
            else None
        )
        return reader.prime(
            token_budget=DEFAULT_PRIME_TOKEN_BUDGET,
            classifications=classifications,
            session_id=spec.session_id,
        )
