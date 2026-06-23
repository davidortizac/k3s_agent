"""Herramienta helm: gestión de releases. read: list/status/get; mutating: el resto."""

from __future__ import annotations

import shutil
import subprocess

from ..safety import READ, MUTATING
from .base import Tool, ToolCall, ToolContext, ToolResult

HELM_TIMEOUT = 120

HELM_READ_VERBS = frozenset({"list", "ls", "status", "get", "history", "search", "show", "version", "env"})


class HelmTool(Tool):
    name = "run_helm"
    description = (
        "Ejecuta helm. args como lista sin 'helm'. Lectura: list/status/get/history. "
        "Modificación (pide confirmación): install/upgrade/uninstall/rollback."
    )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Argumentos de helm, sin el binario.",
                },
                "reason": {"type": "string", "description": "Por qué ejecutas este comando."},
            },
            "required": ["args", "reason"],
        }

    def _args(self, call: ToolCall) -> list[str]:
        raw = call.arguments.get("args", [])
        if isinstance(raw, str):
            raw = raw.split()
        return [str(a) for a in raw]

    def classify(self, call: ToolCall) -> str:
        args = [a for a in self._args(call) if not a.startswith("-")]
        if not args:
            return READ
        return READ if args[0].lower() in HELM_READ_VERBS else MUTATING

    def display(self, call: ToolCall) -> str:
        return "helm " + " ".join(self._args(call))

    def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        args = self._args(call)
        if not args:
            return ToolResult(output="No se indicaron argumentos para helm.", ok=False)
        if shutil.which("helm") is None:
            return ToolResult(output="helm no está instalado en la imagen/PATH.", ok=False)

        cmd = ["helm"]
        if ctx.config.kubeconfig:
            cmd += ["--kubeconfig", ctx.config.kubeconfig]
        chosen = ctx.config.resolved_context()
        if chosen:
            cmd += ["--kube-context", chosen]
        cmd += args

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=HELM_TIMEOUT, shell=False)
        except subprocess.TimeoutExpired:
            return ToolResult(output=f"Timeout ejecutando: {' '.join(cmd)}", ok=False, display=" ".join(cmd))
        out = (proc.stdout or "").strip()
        errout = (proc.stderr or "").strip()
        body = out + (f"\n[stderr] {errout}" if errout else "")
        return ToolResult(output=body or f"(exit {proc.returncode})", ok=proc.returncode == 0, display=" ".join(cmd))


def register() -> Tool:
    return HelmTool()
