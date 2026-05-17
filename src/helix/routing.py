"""Model & provider router (HELIX.md §11.2, §9.9, §7.3, §11.1).

Nothing in the workflow hard-codes a model — agents request a *role*
and the router resolves it to a concrete ``provider:model`` through one
small registry (``~/.helix/models.toml``).

Resolution precedence (most specific wins, §11.2)::

    per-step flag  >  per-project  >  role default  >  global default
       --model X       [project.<n>.roles]   [roles]        [default]

Cross-cutting rules this module owns:

* **Privacy (§9.9):** ``privacy=strict`` forces every role to a local
  or zero-data-retention provider, overriding less-specific API-key
  settings; the substitution is *recorded* (``degraded_from``) so the
  trade-off is visible, never silent.
* **Fail-closed (§11.2):** an unresolvable role, an unconfigured
  provider, or privacy that cannot be honored raises — the run pauses,
  it never silently falls back to a different model. (Missing API key /
  unreachable local endpoint is a separate *readiness* concern, for
  ``helix doctor``; resolution itself stays pure and deterministic so
  it can feed Snapshot ``model_routing`` reproducibly, §7.3.)
* **Zero-integration (§11.1):** common providers are built in, so a
  minimal config is just ``[default] model = "..."``.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

# Canonical role keys = the §5.1 agent roster (Scout surfaces as
# "explore", §9.8) + Atlas ops. resolve_all() covers exactly these, so
# the Snapshot model_routing map is complete and reproducible (§7.3).
ROLES: Tuple[str, ...] = (
    "explore",
    "critic-methods",
    "planner",
    "builder",
    "validator",
    "critic-results",
    "maintainer",
    "watcher",
    "atlas-embed",
)

# Built-in provider knowledge so zero-integration works with only
# [default] set (§11.1). User [providers.*] entries override/extend.
_BUILTIN_PROVIDERS: Dict[str, Dict[str, object]] = {
    "anthropic": {"key_env": "ANTHROPIC_API_KEY"},
    "openai": {"key_env": "OPENAI_API_KEY"},
    "google": {"key_env": "GOOGLE_API_KEY"},
    "openrouter": {
        "key_env": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
    },
    "local": {"runtime": "ollama", "endpoint": "http://localhost:11434"},
}

_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


class RoutingError(RuntimeError):
    """Base for fail-closed routing failures (the run pauses, §11.2)."""


class UnresolvableRole(RoutingError):
    pass


class UnknownProvider(RoutingError):
    pass


class PrivacyUnsatisfiable(RoutingError):
    pass


@dataclass(frozen=True)
class ModelRef:
    """A parsed ``provider:model`` value.

    Split on the FIRST colon only: ``local:qwen2.5-coder:32b`` →
    provider ``local``, model ``qwen2.5-coder:32b``.
    """

    provider: str
    model: str

    @classmethod
    def parse(cls, value: str) -> "ModelRef":
        if not value or ":" not in value:
            raise ValueError(
                f"model ref must be 'provider:model', got {value!r}"
            )
        provider, model = value.split(":", 1)
        if not provider or not model:
            raise ValueError(f"empty provider or model in {value!r}")
        return cls(provider, model)

    def __str__(self) -> str:
        return f"{self.provider}:{self.model}"


@dataclass(frozen=True)
class Provider:
    name: str
    key_env: Optional[str] = None      # API-key-backed
    base_url: Optional[str] = None
    runtime: Optional[str] = None      # local runtime (ollama/vllm/…)
    endpoint: Optional[str] = None     # local endpoint URL
    zdr: bool = False                  # zero-data-retention contract

    @property
    def is_local(self) -> bool:
        return self.name == "local" or self.runtime is not None

    @property
    def privacy_safe(self) -> bool:
        """May serve a strict-privacy role (§9.9): local or ZDR."""
        return self.is_local or self.zdr


@dataclass
class Resolution:
    """A resolved role binding. ``source`` says which layer won so
    ``helix model list`` can show it (§11.2)."""

    role: str
    ref: ModelRef
    source: str                        # step|project|role|default|privacy
    degraded_from: Optional[ModelRef] = None  # set when privacy substituted

    @property
    def degraded(self) -> bool:
        return self.degraded_from is not None


@dataclass
class Readiness:
    ok: bool
    reason: str = ""


@dataclass
class ModelConfig:
    """In-memory mirror of ``models.toml`` (the only mutable copy)."""

    default_model: Optional[str] = None
    privacy_model: Optional[str] = None          # [privacy] model
    roles: Dict[str, str] = field(default_factory=dict)
    project_roles: Dict[str, Dict[str, str]] = field(default_factory=dict)
    providers: Dict[str, Provider] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "ModelConfig":
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text())
        providers: Dict[str, Provider] = {}
        for name, pd in (data.get("providers") or {}).items():
            providers[name] = Provider(
                name=name,
                key_env=pd.get("key_env"),
                base_url=pd.get("base_url"),
                runtime=pd.get("runtime"),
                endpoint=pd.get("endpoint"),
                zdr=bool(pd.get("zdr", False)),
            )
        project_roles = {
            proj: dict(pv.get("roles") or {})
            for proj, pv in (data.get("project") or {}).items()
        }
        return cls(
            default_model=(data.get("default") or {}).get("model"),
            privacy_model=(data.get("privacy") or {}).get("model"),
            roles=dict(data.get("roles") or {}),
            project_roles=project_roles,
            providers=providers,
        )


def default_config_toml(ref: str) -> str:
    """The minimal config `helix setup` writes from the one decision
    (§11.1): a single provider:model as the global default."""
    ModelRef.parse(ref)  # validate
    return (
        "# Helix model routing — `helix model` manages this file.\n"
        "# Precedence: per-step > per-project > role > [default].\n\n"
        "[default]\n"
        f'model = "{ref}"\n'
    )


class Router:
    """Resolves roles to ``provider:model`` and persists config edits."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.config = ModelConfig.load(self.path)

    # ---- provider lookup --------------------------------------------

    def provider(self, name: str) -> Provider:
        if name in self.config.providers:
            return self.config.providers[name]
        if name in _BUILTIN_PROVIDERS:
            return Provider(name=name, **_BUILTIN_PROVIDERS[name])  # type: ignore[arg-type]
        raise UnknownProvider(
            f"provider {name!r} is not configured (add it with "
            f"`helix provider add {name} ...`)"
        )

    # ---- resolution (pure, deterministic) ---------------------------

    def _raw_ref(
        self,
        role: str,
        *,
        project: Optional[str],
        step_override: Optional[str],
    ) -> Tuple[str, str]:
        """Return (ref_str, source) by precedence, before privacy."""
        if step_override:
            return step_override, "step"
        if project:
            pr = self.config.project_roles.get(project, {})
            if role in pr:
                return pr[role], "project"
        if role in self.config.roles:
            return self.config.roles[role], "role"
        if self.config.default_model:
            return self.config.default_model, "default"
        raise UnresolvableRole(
            f"role {role!r} has no model: set [roles].{role}, a project "
            f"override, or [default] in {self.path.name} (fail-closed)"
        )

    def resolve(
        self,
        role: str,
        *,
        project: Optional[str] = None,
        step_override: Optional[str] = None,
        privacy_strict: bool = False,
    ) -> Resolution:
        ref_str, source = self._raw_ref(
            role, project=project, step_override=step_override
        )
        ref = ModelRef.parse(ref_str)
        prov = self.provider(ref.provider)  # validates provider exists

        if not privacy_strict or prov.privacy_safe:
            return Resolution(role=role, ref=ref, source=source)

        # Strict privacy and the resolved provider is neither local nor
        # ZDR → must substitute, and record the degradation (§9.9).
        if not self.config.privacy_model:
            raise PrivacyUnsatisfiable(
                f"role {role!r} resolves to {ref} (non-private) under "
                f"privacy=strict and no [privacy] model is configured "
                f"— fail-closed (HELIX.md §9.9)"
            )
        safe = ModelRef.parse(self.config.privacy_model)
        safe_prov = self.provider(safe.provider)
        if not safe_prov.privacy_safe:
            raise PrivacyUnsatisfiable(
                f"[privacy] model {safe} is not local/ZDR — cannot honor "
                f"privacy=strict for role {role!r} (fail-closed)"
            )
        return Resolution(
            role=role, ref=safe, source="privacy", degraded_from=ref
        )

    def resolve_all(
        self,
        *,
        project: Optional[str] = None,
        privacy_strict: bool = False,
    ) -> Tuple[Dict[str, str], List[str]]:
        """Resolve every canonical role for a Snapshot's ``model_routing``
        (§7.3). Returns ``(routing, degraded_roles)`` — ``degraded_roles``
        feeds Forge ``privacy_degraded`` (§5.5, §9.9)."""
        routing: Dict[str, str] = {}
        degraded: List[str] = []
        for role in ROLES:
            r = self.resolve(
                role, project=project, privacy_strict=privacy_strict
            )
            routing[role] = str(r.ref)
            if r.degraded:
                degraded.append(role)
        return routing, degraded

    def table(
        self,
        *,
        project: Optional[str] = None,
        privacy_strict: bool = False,
    ) -> List[Resolution]:
        """For `helix model list`: resolved model + winning layer per
        role, so the effective config is never a mystery (§11.2)."""
        return [
            self.resolve(role, project=project, privacy_strict=privacy_strict)
            for role in ROLES
        ]

    # ---- readiness (side-effecting; for helix doctor) ---------------

    def readiness(
        self,
        resolution: Resolution,
        *,
        env: Optional[Mapping[str, str]] = None,
        probe=None,
    ) -> Readiness:
        """Is the resolved model actually usable *now*? (§11.2)

        Separate from resolution so resolution stays pure/reproducible.
        ``helix doctor`` calls this; the run fails closed if not ready
        rather than silently switching models.
        """
        env = os.environ if env is None else env
        prov = self.provider(resolution.ref.provider)
        if prov.is_local:
            if probe is not None and not probe(prov):
                return Readiness(
                    False,
                    f"local endpoint {prov.endpoint} for "
                    f"{resolution.ref} is unreachable",
                )
            return Readiness(True)
        if prov.key_env and not env.get(prov.key_env):
            return Readiness(
                False,
                f"${prov.key_env} is not set — required for "
                f"{resolution.ref} (role {resolution.role})",
            )
        return Readiness(True)

    # ---- mutators (CLI `helix model`/`provider` call these) ---------

    def set_global(self, ref: str) -> None:
        ModelRef.parse(ref)
        self.config.default_model = ref
        self._save()

    def set_role(self, role: str, ref: str) -> None:
        ModelRef.parse(ref)
        self.config.roles[role] = ref
        self._save()

    def set_project_role(self, project: str, role: str, ref: str) -> None:
        ModelRef.parse(ref)
        self.config.project_roles.setdefault(project, {})[role] = ref
        self._save()

    def set_privacy_model(self, ref: str) -> None:
        ModelRef.parse(ref)
        self.config.privacy_model = ref
        self._save()

    def add_provider(self, name: str, **kw) -> None:
        self.config.providers[name] = Provider(name=name, **kw)
        self._save()

    # ---- canonical TOML writer --------------------------------------

    @staticmethod
    def _key(k: str) -> str:
        return k if _BARE_KEY.match(k) else '"' + k.replace('"', '\\"') + '"'

    @staticmethod
    def _val(v) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _save(self) -> None:
        c = self.config
        out: List[str] = [
            "# Helix model routing — `helix model` manages this file.",
            "# Precedence: per-step > per-project > role > [default].",
            "",
        ]
        if c.default_model:
            out += ["[default]", f'model = {self._val(c.default_model)}', ""]
        if c.privacy_model:
            out += ["[privacy]", f'model = {self._val(c.privacy_model)}', ""]
        for name, p in sorted(c.providers.items()):
            out.append(f"[providers.{self._key(name)}]")
            for fld in ("key_env", "base_url", "runtime", "endpoint"):
                val = getattr(p, fld)
                if val is not None:
                    out.append(f"{fld} = {self._val(val)}")
            if p.zdr:
                out.append("zdr = true")
            out.append("")
        if c.roles:
            out.append("[roles]")
            for role, ref in sorted(c.roles.items()):
                out.append(f"{self._key(role)} = {self._val(ref)}")
            out.append("")
        for proj, roles in sorted(c.project_roles.items()):
            if not roles:
                continue
            out.append(f"[project.{self._key(proj)}.roles]")
            for role, ref in sorted(roles.items()):
                out.append(f"{self._key(role)} = {self._val(ref)}")
            out.append("")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text("\n".join(out).rstrip() + "\n")
        tmp.replace(self.path)  # atomic on POSIX
        self.config = ModelConfig.load(self.path)  # re-parse: writer is sound
