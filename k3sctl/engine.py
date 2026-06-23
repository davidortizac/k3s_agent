"""Bucle agéntico contra un endpoint OpenAI-compat. UI-agnóstico.

El motor es SÍNCRONO y se comunica con la interfaz mediante un objeto `EngineHooks`
(patrón observer). La TUI lo ejecuta en un worker-thread y reenvía los callbacks al
hilo de UI; un test puede subclasear EngineHooks con métodos mínimos.

Decisiones de seguridad:
  - tools `mutating` requieren confirmación (hooks.confirm) salvo --read-only,
    que las bloquea directamente.
  - tools `read` se ejecutan sin confirmación.
  - JSON de argumentos inválido NO crashea: se devuelve el error al modelo.
  - límite de pasos por turno (config.max_steps) como anti-bucle.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from openai import OpenAI

from .config import Config
from .context import compact, estimate_tokens
from .history import History
from .memory import Memory
from .prompts import build_system_prompt
from .safety import MUTATING, READ
from .tools.base import ToolCall, ToolContext, ToolRegistry, ToolResult


class EngineHooks:
    """Callbacks que la UI implementa. Por defecto, no-ops (excepto confirm)."""

    def on_assistant_delta(self, text: str) -> None: ...
    def on_assistant_message(self, text: str) -> None: ...
    def on_tool_start(self, call_id: str, tool: str, display: str, classification: str, reason: str) -> None: ...
    def on_tool_result(self, call_id: str, result: ToolResult) -> None: ...
    def on_tool_blocked(self, call_id: str, display: str, reason: str) -> None: ...
    def on_error(self, message: str) -> None: ...
    def on_status(self, info: dict) -> None: ...

    def confirm(self, tool: str, display: str, reason: str) -> bool:
        """Confirmación de una operación mutating. Por defecto, denegar (seguro)."""
        return False


@dataclass
class _AssistantTurn:
    content: str
    tool_calls: list[dict]


class Engine:
    def __init__(
        self,
        config: Config,
        registry: ToolRegistry,
        memory: Memory,
        history: History,
        hooks: EngineHooks | None = None,
    ):
        self.config = config
        self.registry = registry
        self.memory = memory
        self.history = history
        self.hooks = hooks or EngineHooks()
        self.client = OpenAI(base_url=config.base_url, api_key=config.api_key)
        self.messages: list[dict] = []
        self._reset_system()
        self.history.meta(model=config.model, base_url=config.base_url, read_only=config.read_only)

    # -- gestión de estado --------------------------------------------------
    def _reset_system(self) -> None:
        sys_prompt = build_system_prompt(self.config, self.memory.as_prompt_block())
        if self.messages and self.messages[0].get("role") == "system":
            self.messages[0] = {"role": "system", "content": sys_prompt}
        else:
            self.messages.insert(0, {"role": "system", "content": sys_prompt})

    def set_model(self, model: str) -> None:
        self.config = self.config.with_overrides(model=model)
        self._reset_system()
        self.history.meta(model=model)

    def set_read_only(self, value: bool) -> None:
        self.config = self.config.with_overrides(read_only=value)
        self._reset_system()
        self.history.meta(read_only=value)

    def clear(self) -> None:
        """Vacía la conversación (mantiene system actualizado)."""
        self.messages = []
        self._reset_system()

    def context_usage(self) -> tuple[int, int]:
        return estimate_tokens(self.messages), self.config.context_budget

    # -- turno --------------------------------------------------------------
    def run_turn(self, user_text: str) -> None:
        self.messages.append({"role": "user", "content": user_text})
        self.history.user(user_text)

        for _step in range(self.config.max_steps):
            self.messages = compact(self.messages, self.config.context_budget, self.config.keep_turns)
            self._emit_status()

            try:
                turn = self._call_llm()
            except Exception as e:
                self.hooks.on_error(f"Error llamando al modelo: {e}")
                self.history.log("error", message=str(e))
                return

            assistant_msg: dict = {"role": "assistant", "content": turn.content or ""}
            if turn.tool_calls:
                assistant_msg["tool_calls"] = turn.tool_calls
            self.messages.append(assistant_msg)

            if turn.content:
                self.hooks.on_assistant_message(turn.content)
                self.history.assistant(turn.content)

            if not turn.tool_calls:
                return  # turno completado

            for tc in turn.tool_calls:
                self._handle_tool_call(tc)

        self.hooks.on_error(f"Límite de {self.config.max_steps} pasos alcanzado en este turno.")

    # -- LLM (streaming) ----------------------------------------------------
    def _call_llm(self) -> _AssistantTurn:
        tools = self.registry.schemas()
        kwargs = dict(model=self.config.model, messages=self.messages, stream=True)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        content_parts: list[str] = []
        # Acumulador de tool_calls por índice del stream.
        tc_acc: dict[int, dict] = {}

        stream = self.client.chat.completions.create(**kwargs)
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                content_parts.append(delta.content)
                self.hooks.on_assistant_delta(delta.content)
            for tcd in (delta.tool_calls or []):
                idx = tcd.index
                slot = tc_acc.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                if tcd.id:
                    slot["id"] = tcd.id
                if tcd.function:
                    if tcd.function.name:
                        slot["name"] = tcd.function.name
                    if tcd.function.arguments:
                        slot["arguments"] += tcd.function.arguments

        tool_calls = []
        for idx in sorted(tc_acc):
            slot = tc_acc[idx]
            if not slot["name"]:
                continue
            tool_calls.append(
                {
                    "id": slot["id"] or f"call_{idx}",
                    "type": "function",
                    "function": {"name": slot["name"], "arguments": slot["arguments"] or "{}"},
                }
            )
        return _AssistantTurn(content="".join(content_parts), tool_calls=tool_calls)

    # -- ejecución de una tool_call ----------------------------------------
    def _handle_tool_call(self, tc: dict) -> None:
        call_id = tc.get("id", "")
        fn = tc.get("function", {})
        name = fn.get("name", "")
        raw_args = fn.get("arguments", "") or "{}"

        tool = self.registry.get(name)
        if tool is None or not self.registry.is_active(name):
            self._append_tool_message(call_id, name, f"Herramienta '{name}' no disponible o desactivada.")
            self.hooks.on_error(f"El modelo pidió una tool no disponible: {name}")
            return

        # Parseo tolerante de argumentos.
        try:
            args = json.loads(raw_args) if raw_args.strip() else {}
            if not isinstance(args, dict):
                raise ValueError("los argumentos no son un objeto JSON")
        except (json.JSONDecodeError, ValueError) as e:
            msg = f"Argumentos JSON inválidos para {name}: {e}. Corrígelos y reintenta."
            self._append_tool_message(call_id, name, msg)
            self.hooks.on_error(msg)
            return

        call = ToolCall(name=name, arguments=args, id=call_id)
        classification = tool.classify(call)
        display = tool.display(call)
        reason = str(args.get("reason", "")).strip()

        self.hooks.on_tool_start(call_id, name, display, classification, reason)

        # Política de seguridad.
        if classification == MUTATING:
            if self.config.read_only:
                reason_txt = "Modo solo-lectura: operación de modificación bloqueada."
                self.hooks.on_tool_blocked(call_id, display, reason_txt)
                self.history.blocked(display, reason_txt)
                self._append_tool_message(
                    call_id, name, f"BLOQUEADO ({reason_txt}). No se ejecutó: {display}"
                )
                return
            approved = self.hooks.confirm(name, display, reason)
            if not approved:
                self.hooks.on_tool_blocked(call_id, display, "Cancelado por el usuario.")
                self.history.cancelled(display)
                self._append_tool_message(
                    call_id, name, f"CANCELADO por el usuario. No se ejecutó: {display}"
                )
                return

        # Ejecutar.
        ctx = ToolContext(config=self.config, memory=self.memory)
        try:
            result = tool.run(call, ctx)
        except Exception as e:  # defensivo: una tool no debe tumbar el motor
            result = ToolResult(output=f"Error interno de la tool {name}: {e}", ok=False, display=display)

        self.hooks.on_tool_result(call_id, result)
        self.history.command(name, result.display or display, classification, result.ok)
        self._append_tool_message(call_id, name, result.as_message_content())

    def _append_tool_message(self, call_id: str, name: str, content: str) -> None:
        self.messages.append(
            {"role": "tool", "tool_call_id": call_id, "name": name, "content": content}
        )

    def _emit_status(self) -> None:
        used, budget = self.context_usage()
        self.hooks.on_status(
            {
                "model": self.config.model,
                "read_only": self.config.read_only,
                "context": self.config.resolved_context(),
                "namespace": self.config.namespace,
                "tokens_used": used,
                "tokens_budget": budget,
                "notes": self.memory.count(),
            }
        )
