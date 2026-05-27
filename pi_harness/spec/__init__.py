"""Public surface of the spec layer (Plan 7).

Consumed by Plan 8's dashboard and by the CLI. The launch bridge
(spec_to_runspec / build_coordinator) is the single mapping point onto Plan 5.
"""
from pi_harness.spec.decomposer import (
    DecomposedTask,
    Decomposer,
    DecomposerError,
    DecompositionResult,
)
from pi_harness.spec.format import (
    Spec,
    SpecStatus,
    parse_spec,
    parse_spec_file,
    serialize_spec,
    spec_path,
    spec_storage_dir,
)
from pi_harness.spec.linter import LintResult, LintViolation, Linter, Severity
from pi_harness.spec.runspec import ROLE_TIER_MAP, build_coordinator, spec_to_runspec

__all__ = [
    "DecomposedTask",
    "Decomposer",
    "DecomposerError",
    "DecompositionResult",
    "LintResult",
    "LintViolation",
    "Linter",
    "Severity",
    "Spec",
    "SpecStatus",
    "ROLE_TIER_MAP",
    "build_coordinator",
    "parse_spec",
    "parse_spec_file",
    "serialize_spec",
    "spec_path",
    "spec_storage_dir",
    "spec_to_runspec",
]
