"""Persistent topology: session_id tags trajectory + corpus subset for reuse."""
from __future__ import annotations

from pi_harness.topology.base import RunSpec, TaskDef
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
        """Wrapper around Plan 3's reader.prime that forces session_id filter."""
        return reader.prime(
            classifications=spec.corpus_classifications,
            session_id=spec.session_id,
        )
