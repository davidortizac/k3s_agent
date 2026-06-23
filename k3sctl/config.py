"""Configuración del agente: flags de CLI + variables de entorno + defaults.

Precedencia (de mayor a menor): flag de CLI > variable de entorno > default.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_BASE_URL = "http://localhost:11434/v1"  # Ollama local
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_NAMESPACE = "default"
DEFAULT_CONTEXT_BUDGET = 8000  # tokens aprox; mantener por debajo de num_ctx en Ollama
DEFAULT_KEEP_TURNS = 6
DEFAULT_MAX_STEPS = 25  # tope de tool-calls por turno (anti-bucle)

# Endpoints conocidos (solo documentación / ayuda).
KNOWN_ENDPOINTS = {
    "ollama": "http://localhost:11434/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openai": "https://api.openai.com/v1",
}


def state_dir() -> Path:
    """Directorio de estado persistente. Override con K3SCTL_HOME."""
    home = os.environ.get("K3SCTL_HOME")
    base = Path(home) if home else Path.home() / ".k3sctl"
    return base


@dataclass
class Config:
    # --- LLM / backend ---
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str = "ollama"  # Ollama ignora la key pero el SDK exige una no vacía.

    # --- kubectl / cluster ---
    kubeconfig: str | None = None
    contexts: list[str] = field(default_factory=list)  # allowlist de contextos
    default_context: str | None = None
    namespace: str = DEFAULT_NAMESPACE
    insecure_skip_tls_verify: bool = False

    # --- seguridad ---
    read_only: bool = False
    enable: list[str] = field(default_factory=list)   # tools a forzar-activar
    disable: list[str] = field(default_factory=list)  # tools a forzar-desactivar

    # --- contexto / compactación ---
    context_budget: int = DEFAULT_CONTEXT_BUDGET
    keep_turns: int = DEFAULT_KEEP_TURNS
    max_steps: int = DEFAULT_MAX_STEPS

    # --- estado en disco ---
    home: Path = field(default_factory=state_dir)

    @property
    def memory_path(self) -> Path:
        return self.home / "memory.json"

    @property
    def sessions_dir(self) -> Path:
        return self.home / "sessions"

    def resolved_context(self) -> str | None:
        """Contexto por defecto efectivo: el explícito, o el primero de la lista."""
        if self.default_context:
            return self.default_context
        return self.contexts[0] if self.contexts else None

    def with_overrides(self, **kw) -> "Config":
        return replace(self, **kw)


def _env(name: str) -> str | None:
    val = os.environ.get(name)
    return val if val else None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="k3sctl",
        description="Agente conversacional para administrar clusters k3s (TUI).",
    )
    # LLM
    p.add_argument("--base-url", help="Endpoint OpenAI-compat (default: Ollama local).")
    p.add_argument("--model", help="Identificador del modelo.")
    p.add_argument("--api-key", help="API key del LLM (o env K3SCTL_API_KEY).")
    # kubectl
    p.add_argument("--kubeconfig", help="Ruta al kubeconfig.")
    p.add_argument(
        "--context",
        action="append",
        dest="contexts",
        metavar="CTX",
        help="Contexto permitido (repetible). El primero es el por defecto.",
    )
    p.add_argument("--default-context", help="Contexto por defecto explícito.")
    p.add_argument("--namespace", "-n", help="Namespace por defecto.")
    p.add_argument(
        "--insecure-skip-tls-verify",
        action="store_true",
        default=None,
        help="Saltar verificación TLS (cert autofirmado de k3s).",
    )
    # seguridad
    p.add_argument(
        "--read-only",
        action="store_true",
        default=None,
        help="Bloquea TODA operación mutating de TODAS las tools.",
    )
    p.add_argument(
        "--enable", action="append", metavar="TOOL", help="Forzar activación de una tool (repetible)."
    )
    p.add_argument(
        "--disable", action="append", metavar="TOOL", help="Forzar desactivación de una tool (repetible)."
    )
    # contexto
    p.add_argument("--context-budget", type=int, help="Presupuesto de tokens antes de compactar.")
    p.add_argument("--keep-turns", type=int, help="Turnos recientes a preservar al compactar.")
    p.add_argument("--max-steps", type=int, help="Tope de tool-calls por turno.")
    return p


def load_config(argv: list[str] | None = None) -> Config:
    """Combina defaults + entorno + flags en un Config inmutable-ish."""
    args = build_parser().parse_args(argv)

    cfg = Config()

    # Entorno (capa intermedia).
    cfg = cfg.with_overrides(
        base_url=_env("K3SCTL_BASE_URL") or cfg.base_url,
        model=_env("K3SCTL_MODEL") or cfg.model,
        api_key=_env("K3SCTL_API_KEY") or cfg.api_key,
        kubeconfig=_env("KUBECONFIG") or cfg.kubeconfig,
        namespace=_env("K3SCTL_NAMESPACE") or cfg.namespace,
    )
    if _env("K3SCTL_CONTEXTS"):
        cfg = cfg.with_overrides(contexts=[c.strip() for c in _env("K3SCTL_CONTEXTS").split(",") if c.strip()])

    # Flags (capa superior). Solo aplican si el usuario los pasó.
    overrides: dict = {}
    if args.base_url:
        overrides["base_url"] = args.base_url
    if args.model:
        overrides["model"] = args.model
    if args.api_key:
        overrides["api_key"] = args.api_key
    if args.kubeconfig:
        overrides["kubeconfig"] = args.kubeconfig
    if args.contexts:
        overrides["contexts"] = args.contexts
    if args.default_context:
        overrides["default_context"] = args.default_context
    if args.namespace:
        overrides["namespace"] = args.namespace
    if args.insecure_skip_tls_verify:
        overrides["insecure_skip_tls_verify"] = True
    if args.read_only:
        overrides["read_only"] = True
    if args.enable:
        overrides["enable"] = args.enable
    if args.disable:
        overrides["disable"] = args.disable
    if args.context_budget is not None:
        overrides["context_budget"] = args.context_budget
    if args.keep_turns is not None:
        overrides["keep_turns"] = args.keep_turns
    if args.max_steps is not None:
        overrides["max_steps"] = args.max_steps

    return cfg.with_overrides(**overrides)
