"""Tests de compactación de contexto."""

from k3sctl.context import compact, estimate_tokens, _split_into_blocks


def _msgs():
    sys = {"role": "system", "content": "S" * 40}
    out = [sys]
    for i in range(6):
        out.append({"role": "user", "content": f"pregunta {i} " + "x" * 200})
        out.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": f"c{i}", "type": "function", "function": {"name": "run_kubectl", "arguments": '{"args":["get","pods"]}'}}
                ],
            }
        )
        out.append({"role": "tool", "tool_call_id": f"c{i}", "name": "run_kubectl", "content": "salida " + "y" * 200})
        out.append({"role": "assistant", "content": "resumen " + "z" * 100})
    return out


def test_no_compaction_under_budget():
    msgs = _msgs()
    big = estimate_tokens(msgs) + 1000
    assert compact(msgs, big, keep_turns=2) == msgs


def test_compaction_preserves_system_and_keep_turns():
    msgs = _msgs()
    small = 200
    result = compact(msgs, budget=small, keep_turns=2)
    # System preservado.
    assert result[0]["role"] == "system"
    # No supera (mucho) el número de turnos que se quería conservar.
    blocks = _split_into_blocks(result[1:])
    assert len(blocks) <= 2
    # Es estrictamente más corto que el original.
    assert len(result) < len(msgs)


def test_tool_call_pairs_not_split():
    """Cada bloque conservado mantiene la estructura assistant(tool_calls)+tool."""
    msgs = _msgs()
    result = compact(msgs, budget=200, keep_turns=2)
    # Todo tool_call_id en mensajes 'tool' debe tener su assistant con ese id antes.
    seen_ids = set()
    for m in result:
        for tc in m.get("tool_calls", []) or []:
            seen_ids.add(tc["id"])
        if m.get("role") == "tool":
            assert m["tool_call_id"] in seen_ids
