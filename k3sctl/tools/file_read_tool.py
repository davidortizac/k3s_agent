"""Herramienta file_read: lectura de manifiestos/YAML locales (solo lectura)."""

from __future__ import annotations

from pathlib import Path

from ..safety import READ
from .base import Tool, ToolCall, ToolContext, ToolResult

MAX_BYTES = 64 * 1024  # tope para no inundar el contexto del modelo


class FileReadTool(Tool):
    name = "file_read"
    description = (
        "Lee un fichero de texto local (manifiestos YAML, configs). Solo lectura. "
        "Devuelve hasta 64KB. Ruta absoluta o relativa al working dir."
    )

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Ruta del fichero a leer."}
            },
            "required": ["path"],
        }

    def classify(self, call: ToolCall) -> str:
        return READ

    def display(self, call: ToolCall) -> str:
        return f"file_read {call.arguments.get('path', '')}"

    def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        raw = str(call.arguments.get("path", "")).strip()
        if not raw:
            return ToolResult(output="Ruta vacía.", ok=False)
        p = Path(raw).expanduser()
        try:
            if not p.is_file():
                return ToolResult(output=f"No existe o no es un fichero: {p}", ok=False)
            data = p.read_bytes()[:MAX_BYTES]
            text = data.decode("utf-8", errors="replace")
            truncated = "\n[...truncado a 64KB...]" if p.stat().st_size > MAX_BYTES else ""
            return ToolResult(output=text + truncated, ok=True, display=self.display(call))
        except Exception as e:
            return ToolResult(output=f"Error leyendo {p}: {e}", ok=False)


def register() -> Tool:
    return FileReadTool()
