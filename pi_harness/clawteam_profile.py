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
    "BUCKET_REASONING",
    "BUCKET_FAST",
    "bucket_for_role",
]

PROFILE_NAME_REASONING = "pi-openai-reasoning"
PROFILE_NAME_FAST = "pi-openai-fast"

DEFAULT_AGENT_CLI = "pi"

ROLE_PROFILE_MAP: Dict[str, str] = {
    "orchestrator": PROFILE_NAME_REASONING,
    "reviewer": PROFILE_NAME_REASONING,
    "synthesizer": PROFILE_NAME_REASONING,
    "builder": PROFILE_NAME_FAST,
    "scout": PROFILE_NAME_FAST,
}

# Bucket names used as the agent_wrapper --bucket value. These are the
# HarnessSettings keys (orchestrator-bucket vs builder-bucket); two names
# instead of five so the UI stays at "pick a model for the orchestrator,
# pick a model for the builder."
BUCKET_REASONING = "reasoning"
BUCKET_FAST = "fast"

_PROFILE_TO_BUCKET = {
    PROFILE_NAME_REASONING: BUCKET_REASONING,
    PROFILE_NAME_FAST: BUCKET_FAST,
}


def bucket_for_role(role: str) -> str:
    """Map a role string to its HarnessSettings bucket. Unknown roles fall
    back to the fast bucket (cheap default, matches builder/scout)."""
    profile = ROLE_PROFILE_MAP.get(role, PROFILE_NAME_FAST)
    return _PROFILE_TO_BUCKET.get(profile, BUCKET_FAST)


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
    tier: str
    description: str
    api_key_env: Optional[str] = None
    command: Optional[str] = None
    base_url: Optional[str] = None

    def to_set_args(self) -> List[str]:
        """Return positional + flag args for ``clawteam profile set``.

        The full subprocess call is ``["clawteam", "profile", "set", *args]``.
        A local profile emits no ``--api-key-env`` (sovereign: no key needed)
        and carries ``--base-url`` for the local endpoint.
        """
        args: List[str] = [
            self.name,
            "--agent", self.agent,
            "--model", self.model,
        ]
        if self.api_key_env is not None:
            args.extend(["--api-key-env", self.api_key_env])
        args.extend(["--description", self.description])
        if self.command is not None:
            args.extend(["--command", self.command])
        if self.base_url is not None:
            args.extend(["--base-url", self.base_url])
        return args


def build_profile_specs(config: Config) -> List[ProfileSpec]:
    """Build the two profile specs from the live HarnessSettings (local-first).

    Provider/model/base_url come from the user's saved bucket selection
    (``settings.py``), not from ``config``. A ``local`` bucket yields a pi
    profile pointed at the local endpoint with **no** api key env; an ``api``
    bucket yields a pi profile that sources ``OPENAI_API_KEY``. ``config`` is
    retained for signature stability / future api-key-env sourcing.
    """
    from pi_harness.settings import load_settings

    settings = load_settings()

    def _spec(name: str, tier: str, bucket, description: str) -> ProfileSpec:
        if bucket.provider == "local":
            return ProfileSpec(
                name=name, agent=DEFAULT_AGENT_CLI, model=bucket.model,
                tier=tier, description=description,
                api_key_env=None, base_url=settings.local_base_url,
            )
        return ProfileSpec(
            name=name, agent=DEFAULT_AGENT_CLI, model=bucket.model,
            tier=tier, description=description,
            api_key_env="OPENAI_API_KEY", base_url=None,
        )

    return [
        _spec(PROFILE_NAME_REASONING, "reasoning", settings.orchestrator,
              "LLMCoder reasoning tier — orchestrator + reviewer roles."),
        _spec(PROFILE_NAME_FAST, "fast", settings.builder,
              "LLMCoder fast tier — builder + scout roles."),
    ]


def _spec_to_doc_dict(spec: ProfileSpec) -> dict:
    d = {
        "name": spec.name,
        "agent": spec.agent,
        "model": spec.model,
        "tier": spec.tier,
        "description": spec.description,
    }
    if spec.api_key_env is not None:
        d["api_key_env"] = spec.api_key_env
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
