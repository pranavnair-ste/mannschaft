"""Pi-OpenAI ClawTeam profile specs.

ClawTeam profiles (v0.2.x) are single (agent CLI, model, provider) tuples
registered via ``clawteam profile set NAME --agent ... --model ...``. To pin
reasoning vs. fast model tiers to different role groups, the harness registers
**two** profiles:

- ``pi-openai-reasoning`` — heavier tier; mapped to orchestrator + reviewer
- ``pi-openai-fast``       — cheap tier; mapped to builder + scout

Per-role profile assignment lives in the team template (see Plan 7). This
module just owns the spec data + a regenerable documentation TOML committed at
``profiles/pi-openai.toml``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import tomli_w

from pi_harness.config import Config

__all__ = [
    "PROFILE_NAME_REASONING",
    "PROFILE_NAME_FAST",
    "DEFAULT_AGENT_CLI",
    "ROLE_PROFILE_MAP",
    "ProfileSpec",
    "build_profile_specs",
    "generate_pi_openai_profile",
    "write_pi_openai_profile",
]

PROFILE_NAME_REASONING = "pi-openai-reasoning"
PROFILE_NAME_FAST = "pi-openai-fast"

DEFAULT_AGENT_CLI = "codex"

ROLE_PROFILE_MAP: Dict[str, str] = {
    "orchestrator": PROFILE_NAME_REASONING,
    "reviewer": PROFILE_NAME_REASONING,
    "builder": PROFILE_NAME_FAST,
    "scout": PROFILE_NAME_FAST,
}


@dataclass(frozen=True)
class ProfileSpec:
    """Everything needed to register a single ClawTeam profile.

    Attributes:
        name: Profile name (positional arg to ``clawteam profile set``).
        agent: One of ClawTeam's known agent-CLI names (``--agent``).
        model: Model identifier passed to the agent CLI (``--model``).
        api_key_env: Source env var holding the API key (``--api-key-env``).
        tier: ``"reasoning"`` or ``"fast"`` — documentation only.
        description: Human-readable description (``--description``).
        command: Override the agent command (e.g. ``"pi-coding-agent"``).
        base_url: Optional provider base URL (``--base-url``).
    """

    name: str
    agent: str
    model: str
    api_key_env: str
    tier: str
    description: str
    command: Optional[str] = None
    base_url: Optional[str] = None

    def to_set_args(self) -> List[str]:
        """Return positional + flag args for ``clawteam profile set``.

        The full subprocess call is ``["clawteam", "profile", "set", *args]``.
        """
        args: List[str] = [
            self.name,
            "--agent", self.agent,
            "--model", self.model,
            "--api-key-env", self.api_key_env,
            "--description", self.description,
        ]
        if self.command is not None:
            args.extend(["--command", self.command])
        if self.base_url is not None:
            args.extend(["--base-url", self.base_url])
        return args


def build_profile_specs(config: Config) -> List[ProfileSpec]:
    """Build the two profile specs from a Config snapshot."""
    return [
        ProfileSpec(
            name=PROFILE_NAME_REASONING,
            agent=DEFAULT_AGENT_CLI,
            model=config.reasoning_model,
            api_key_env="OPENAI_API_KEY",
            tier="reasoning",
            description=(
                "Pi-Agent Harness reasoning tier — used by orchestrator + reviewer roles."
            ),
        ),
        ProfileSpec(
            name=PROFILE_NAME_FAST,
            agent=DEFAULT_AGENT_CLI,
            model=config.fast_model,
            api_key_env="OPENAI_API_KEY",
            tier="fast",
            description=(
                "Pi-Agent Harness fast tier — used by builder + scout roles."
            ),
        ),
    ]


def _spec_to_doc_dict(spec: ProfileSpec) -> dict:
    d = {
        "name": spec.name,
        "agent": spec.agent,
        "model": spec.model,
        "api_key_env": spec.api_key_env,
        "tier": spec.tier,
        "description": spec.description,
    }
    if spec.command is not None:
        d["command"] = spec.command
    if spec.base_url is not None:
        d["base_url"] = spec.base_url
    return d


def generate_pi_openai_profile(config: Config) -> str:
    """Return a documentation-only TOML describing both profile specs.

    This file is *not* consumed by ClawTeam directly (ClawTeam registers
    profiles via ``clawteam profile set`` CLI args). It exists so the intended
    profile shapes are reviewable in git and regenerable from
    :class:`Config`.
    """
    doc = {
        "documentation": {
            "note": (
                "This TOML is a human-readable mirror of "
                "pi_harness.clawteam_profile.build_profile_specs(config). "
                "Profiles are actually registered with `clawteam profile set`. "
                "Regenerate via the snippet in docs/README-FOUNDATION.md."
            ),
        },
        "role_profile_map": dict(ROLE_PROFILE_MAP),
        "profiles": [_spec_to_doc_dict(s) for s in build_profile_specs(config)],
    }
    return tomli_w.dumps(doc)


def write_pi_openai_profile(config: Config, target: Path) -> Path:
    """Write the documentation TOML to ``target`` and return the path."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generate_pi_openai_profile(config))
    return target
