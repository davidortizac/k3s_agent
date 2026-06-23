"""Herramienta shell: ejecuta comandos de SO. DESACTIVADA POR DEFECTO.

Si se habilita (--enable shell), TODO se trata como mutating (confirmación
siempre). Se ejecuta sin shell=True: el comando se trocea con shlex, de modo que
no hay expansión de la shell (ni pipes, ni redirecciones, ni `;`).
"""

from __future__ import annotations

import shlex
import subprocess

from ..safety import MUTATING
from .base import Tool, ToolCall, ToolContext, ToolResult

SHELL_TIMEOUT = 60


class ShellTool(Tool):
    name = "shell"
    description = (
        "Ejecuta un comando del sistema operativo (sin pipes ni redirecciones). "
        "Úsalo solo si no hay una herramienta específica. Siempre requiere confirmación."
    )
    enabled_by_default = False  # peligrosa: off por defecto
    dangerous = True

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Comando a ejecutar (un solo programa + args)."},
                "reason": {"type": "string", "description": "Por qué lo necesitas."},
            },
            "required": ["command", "reason"],
        }

    def classify(self, call: ToolCall) -> str:
        # TODO en shell es mutating: confirmación siempre.
        return MUTATING

    def display(self, call: ToolCall) -> str:
        return f"$ {call.arguments.get('command', '')}"

    def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        command = str(call.arguments.get("command", "")).strip()
        if not command:
            return ToolResult(output="Comando vacío.", ok=False)
        try:
            argv = shlex.split(command)
        except ValueError as e:
            return ToolResult(output=f"No se pudo parsear el comando: {e}", ok=False)
        if not argv:
            return ToolResult(output="Comando vacío tras el parseo.", ok=False)

        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=SHELL_TIMEOUT, shell=False
            )
        except FileNotFoundError:
            return ToolResult(output=f"Programa no encontrado: {argv[0]}", ok=False)
        except subprocess.TimeoutExpired:
            return ToolResult(output=f"Timeout ({SHELL_TIMEOUT}s): {command}", ok=False)

        out = (proc.stdout or "").strip()
        errout = (proc.stderr or "").strip()
        body = out + (f"\n[stderr] {errout}" if errout else "")
        return ToolResult(output=body or f"(exit {proc.returncode})", ok=proc.returncode == 0, display=self.display(call))


def register() -> Tool:
    return ShellTool()
