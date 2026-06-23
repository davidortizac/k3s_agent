"""Herramienta kubectl: ejecuta kubectl vía subprocess (nunca shell=True).

Porta la lógica del prototipo:
  - clasificación read/mutating (safety.classify_kubectl),
  - inyección de --kubeconfig, --context y namespace,
  - validación del contexto contra la allowlist de Config.contexts.
"""

from __future__ import annotations

import shutil
import subprocess

from ..safety import classify_kubectl, render_kubectl, READ, MUTATING
from .base import Tool, ToolCall, ToolContext, ToolResult

KUBECTL_TIMEOUT = 60  # segundos


class KubectlTool(Tool):
    name = "run_kubectl"
    description = (
        "Ejecuta un comando kubectl contra el cluster. Pasa los argumentos como una "
        "lista (sin incluir 'kubectl'). Ejemplo: args=['get','pods','-A']. "
        "Indica SIEMPRE 'reason' explicando qué buscas. Usa 'context' solo si "
        "necesitas un contexto distinto al por defecto."
    )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Argumentos de kubectl, sin el binario. P.ej. ['get','nodes'].",
                },
                "reason": {
                    "type": "string",
                    "description": "Por qué ejecutas este comando (diagnóstico/objetivo).",
                },
                "context": {
                    "type": "string",
                    "description": "Contexto kube opcional. Debe estar en la allowlist.",
                },
            },
            "required": ["args", "reason"],
        }

    # -- clasificación ------------------------------------------------------
    def _args(self, call: ToolCall) -> list[str]:
        raw = call.arguments.get("args", [])
        if isinstance(raw, str):
            # Algunos modelos flojos mandan una string; la troceamos de forma simple.
            raw = raw.split()
        return [str(a) for a in raw]

    def classify(self, call: ToolCall) -> str:
        return classify_kubectl(self._args(call))

    def display(self, call: ToolCall) -> str:
        return render_kubectl(self._args(call))

    # -- construcción del comando real -------------------------------------
    def _build_command(self, call: ToolCall, ctx: ToolContext) -> tuple[list[str], str | None]:
        """Devuelve (argv_completo, error). Inyecta kubeconfig/context/namespace."""
        cfg = ctx.config
        args = self._args(call)
        if not args:
            return [], "No se indicaron argumentos para kubectl."

        cmd = ["kubectl"]

        # Contexto: validado contra allowlist si hay alguna definida.
        chosen = call.arguments.get("context") or cfg.resolved_context()
        if chosen:
            if cfg.contexts and chosen not in cfg.contexts:
                return [], (
                    f"Contexto '{chosen}' no permitido. Allowlist: {', '.join(cfg.contexts)}."
                )
            cmd += ["--context", chosen]

        if cfg.kubeconfig:
            cmd += ["--kubeconfig", cfg.kubeconfig]
        if cfg.insecure_skip_tls_verify:
            cmd += ["--insecure-skip-tls-verify=true"]

        # Namespace por defecto, salvo que el modelo ya lo especifique o pida todos.
        if not _has_namespace_flag(args) and cfg.namespace:
            cmd += ["--namespace", cfg.namespace]

        cmd += args
        return cmd, None

    # -- ejecución ----------------------------------------------------------
    def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        cmd, err = self._build_command(call, ctx)
        if err:
            return ToolResult(output=err, ok=False, display=self.display(call))

        if shutil.which("kubectl") is None:
            return ToolResult(
                output="kubectl no está instalado o no está en el PATH.",
                ok=False,
                display=" ".join(cmd),
            )

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=KUBECTL_TIMEOUT,
                shell=False,  # NUNCA shell=True
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                output=f"Timeout ({KUBECTL_TIMEOUT}s) ejecutando: {' '.join(cmd)}",
                ok=False,
                display=" ".join(cmd),
            )
        except Exception as e:  # pragma: no cover - defensivo
            return ToolResult(output=f"Error al ejecutar kubectl: {e}", ok=False, display=" ".join(cmd))

        out = (proc.stdout or "").strip()
        errout = (proc.stderr or "").strip()
        ok = proc.returncode == 0
        body = out
        if errout:
            body = (body + "\n" if body else "") + f"[stderr] {errout}"
        if not body:
            body = f"(exit {proc.returncode}, sin salida)"
        return ToolResult(output=body, ok=ok, display=" ".join(cmd))


def _has_namespace_flag(args: list[str]) -> bool:
    for a in args:
        if a in ("-n", "--namespace") or a.startswith("--namespace=") or a == "-A" or a == "--all-namespaces":
            return True
    return False


def register() -> Tool:
    return KubectlTool()
