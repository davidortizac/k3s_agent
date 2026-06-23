"""Interfaz base de herramientas + registro con auto-descubrimiento."""

from __future__ import annotations

import importlib
import json
import pkgutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Iterable

from ..safety import READ, MUTATING

if TYPE_CHECKING:
    from ..config import Config
    from ..memory import Memory


@dataclass
class ToolCall:
    """Una llamada a herramienta tal como la propone el modelo."""

    name: str
    arguments: dict
    id: str = ""


@dataclass
class ToolResult:
    """Resultado de ejecutar una herramienta (lo que se devuelve al modelo)."""

    output: str
    ok: bool = True
    # Etiqueta legible para la tarjeta de la TUI (p.ej. el comando exacto).
    display: str = ""

    def as_message_content(self) -> str:
        return self.output if self.output else ("(sin salida)" if self.ok else "(error sin detalle)")


@dataclass
class ToolContext:
    """Dependencias que el motor inyecta al ejecutar una tool."""

    config: "Config"
    memory: "Memory"


class Tool:
    """Clase base. Las tools concretas la heredan."""

    name: str = "tool"
    description: str = ""
    # Si False, la tool no se carga salvo que se fuerce con --enable.
    enabled_by_default: bool = True
    # Marca de "categoría peligrosa" (para /tools). No sustituye a classify().
    dangerous: bool = False

    @property
    def parameters_schema(self) -> dict:
        """JSON Schema de los argumentos. Override en cada tool."""
        return {"type": "object", "properties": {}}

    def json_schema(self) -> dict:
        """Definición en el formato `tools` de la API OpenAI-compat."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def classify(self, call: ToolCall) -> str:
        """Devuelve READ o MUTATING. Por defecto, conservador: MUTATING."""
        return MUTATING

    def display(self, call: ToolCall) -> str:
        """Representación corta para tarjetas/confirmación."""
        return f"{self.name}({json.dumps(call.arguments, ensure_ascii=False)})"

    def run(self, call: ToolCall, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Registro / descubrimiento
# ---------------------------------------------------------------------------


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)
    # Estado de habilitación efectivo tras aplicar config.
    active: dict[str, bool] = field(default_factory=dict)

    def add(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def active_tools(self) -> list[Tool]:
        return [t for name, t in self.tools.items() if self.active.get(name)]

    def schemas(self) -> list[dict]:
        return [t.json_schema() for t in self.active_tools()]

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def is_active(self, name: str) -> bool:
        return self.active.get(name, False)


def discover_tools() -> list[Tool]:
    """Escanea el paquete `k3sctl.tools` e instancia todas las tools encontradas.

    Convención: cada módulo expone `register_all() -> list[Tool]` o `register() -> Tool`.
    """
    import k3sctl.tools as pkg

    found: list[Tool] = []
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        name = mod_info.name
        if name in ("base", "__init__"):
            continue
        module = importlib.import_module(f"k3sctl.tools.{name}")
        if hasattr(module, "register_all"):
            found.extend(module.register_all())
        elif hasattr(module, "register"):
            found.append(module.register())
    return found


def build_registry(config: "Config", tools: Iterable[Tool] | None = None) -> ToolRegistry:
    """Construye el registro aplicando enable/disable/read-only de la config."""
    reg = ToolRegistry()
    for tool in (tools if tools is not None else discover_tools()):
        reg.add(tool)

    enable = set(config.enable)
    disable = set(config.disable)
    for name, tool in reg.tools.items():
        active = tool.enabled_by_default
        if name in enable:
            active = True
        if name in disable:
            active = False
        reg.active[name] = active
    return reg
