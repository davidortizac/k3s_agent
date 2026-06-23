"""Estimación de tokens y compactación de la conversación.

Crítico para el `num_ctx` pequeño de Ollama. La compactación recorta los
intercambios más antiguos por BLOQUES COMPLETOS (un turno de usuario con toda su
cadena de tool calls), preservando:
  - el mensaje system (índice 0),
  - los últimos `keep_turns` bloques.

Nunca parte la estructura assistant(tool_calls) + tool(result), porque dejar un
tool_call sin su respuesta rompe la API.
"""

from __future__ import annotations

import json

CHARS_PER_TOKEN = 4  # heurística ~4 chars/token


def estimate_tokens_text(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_message_tokens(msg: dict) -> int:
    """Estima tokens de un mensaje chat (contenido + tool_calls serializados)."""
    total = 4  # overhead por mensaje (rol, separadores)
    content = msg.get("content")
    if isinstance(content, str):
        total += estimate_tokens_text(content)
    elif isinstance(content, list):  # contenido multimodal -> serializar
        total += estimate_tokens_text(json.dumps(content, ensure_ascii=False))
    for tc in msg.get("tool_calls", []) or []:
        fn = tc.get("function", {})
        total += estimate_tokens_text(fn.get("name", "") + (fn.get("arguments", "") or ""))
    return total


def estimate_tokens(messages: list[dict]) -> int:
    return sum(estimate_message_tokens(m) for m in messages)


def _split_into_blocks(body: list[dict]) -> list[list[dict]]:
    """Agrupa mensajes (sin el system) en bloques que empiezan en cada 'user'.

    Todo lo anterior al primer 'user' (raro) queda en un bloque inicial propio.
    """
    blocks: list[list[dict]] = []
    current: list[dict] = []
    for msg in body:
        if msg.get("role") == "user" and current:
            blocks.append(current)
            current = [msg]
        else:
            current.append(msg)
    if current:
        blocks.append(current)
    return blocks


def compact(messages: list[dict], budget: int, keep_turns: int) -> list[dict]:
    """Devuelve una versión compactada si se supera el budget; si no, la misma.

    Asume messages[0] = system (se preserva siempre). Si la memoria va embebida en
    el system, también se preserva por estar ahí.
    """
    if not messages:
        return messages
    if estimate_tokens(messages) <= budget:
        return messages

    system = messages[0:1] if messages[0].get("role") == "system" else []
    body = messages[len(system):]
    blocks = _split_into_blocks(body)

    # Recorta bloques antiguos hasta entrar en budget, sin bajar de keep_turns.
    while len(blocks) > keep_turns and estimate_tokens(system + _flatten(blocks)) > budget:
        blocks.pop(0)

    return system + _flatten(blocks)


def _flatten(blocks: list[list[dict]]) -> list[dict]:
    out: list[dict] = []
    for b in blocks:
        out.extend(b)
    return out
