"""Topology layer — 5 named execution modes + Coordinator.

Public surface used by Plans 6, 7, 8.
"""
from pi_harness.topology.base import (
    AgentSpec,
    ModelTier,
    Role,
    RunHandle,
    RunResult,
    RunSpec,
    SyncMode,
    TaskDef,
    Topology,
    TopologyMode,
)
from pi_harness.topology.coordinator import Coordinator
from pi_harness.topology.nested import NestedTopology
from pi_harness.topology.parallel import ParallelTopology
from pi_harness.topology.persistent import PersistentTopology
from pi_harness.topology.sequential import SequentialTopology
from pi_harness.topology.synthesis import SynthesisTopology

__all__ = [
    "AgentSpec",
    "Coordinator",
    "ModelTier",
    "NestedTopology",
    "ParallelTopology",
    "PersistentTopology",
    "Role",
    "RunHandle",
    "RunResult",
    "RunSpec",
    "SequentialTopology",
    "SyncMode",
    "SynthesisTopology",
    "TaskDef",
    "Topology",
    "TopologyMode",
]
