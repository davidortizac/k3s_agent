"""Herramienta remember: añade una nota al conocimiento estable del cluster."""

from __future__ import annotations

from ..safety import READ
from .base import Tool, ToolCall, ToolContext, ToolResult


class RememberTool(Tool):
    name = "remember"
    description = (
        "Guarda una nota estable sobre el cluster (topología, taints por ambiente, "
        "decisiones, hechos que conviene recordar entre sesiones). NO uses esto para "
        "estado transitorio (pods caídos ahora). La nota se reinyecta en el system "
        "prompt en futuras sesiones."
    )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "Hecho estable a recordar."}
            },
            "required": ["note"],
        }

    def classify(self, call: ToolCall) -> str:
        # Escribe en disco local, pero no toca el cluster: no requiere confirmación.
        return READ

    def display(self, call: ToolCall) -> str:
        note = str(call.arguments.get("note", "")).strip()
        return f"remember: {note[:80]}"

    def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        note = str(call.arguments.get("note", "")).strip()
        if not note:
            return ToolResult(output="Nota vacía; nada que recordar.", ok=False)
        ctx.memory.add(note)
        return ToolResult(output=f"Anotado: {note}", ok=True, display=self.display(call))


def register() -> Tool:
    return RememberTool()
