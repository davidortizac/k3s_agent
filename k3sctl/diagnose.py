"""Diagnóstico rápido LOCAL (sin LLM): nodos NotReady y pods con problemas.

Usa kubectl directamente (vía la tool kubectl para reusar inyección de context/
kubeconfig). Pensado para el slash command /diag.
"""

from __future__ import annotations

import json

from .config import Config
from .memory import Memory
from .tools.base import ToolCall, ToolContext
from .tools.kubectl_tool import KubectlTool

PROBLEM_RESTART_THRESHOLD = 5
HEALTHY_PHASES = {"Running", "Completed", "Succeeded"}


def _kubectl_json(kt: KubectlTool, ctx: ToolContext, args: list[str]) -> dict | None:
    call = ToolCall(name="run_kubectl", arguments={"args": args, "reason": "diagnóstico local"})
    res = kt.run(call, ctx)
    if not res.ok:
        return None
    try:
        return json.loads(res.output)
    except json.JSONDecodeError:
        return None


def run_local_diagnose(config: Config, memory: Memory) -> str:
    kt = KubectlTool()
    ctx = ToolContext(config=config, memory=memory)
    lines: list[str] = []

    # Nodos
    nodes = _kubectl_json(kt, ctx, ["get", "nodes", "-o", "json"])
    not_ready: list[str] = []
    if nodes:
        for item in nodes.get("items", []):
            name = item.get("metadata", {}).get("name", "?")
            conds = {c["type"]: c["status"] for c in item.get("status", {}).get("conditions", [])}
            if conds.get("Ready") != "True":
                not_ready.append(name)
    if not_ready:
        lines.append(f"⚠ Nodos NotReady: {', '.join(not_ready)}")
    else:
        lines.append("✓ Todos los nodos Ready (o no se pudo leer).")

    # Pods (todos los namespaces)
    pods = _kubectl_json(kt, ctx, ["get", "pods", "-A", "-o", "json"])
    problems: list[str] = []
    if pods:
        for item in pods.get("items", []):
            meta = item.get("metadata", {})
            ns = meta.get("namespace", "?")
            name = meta.get("name", "?")
            status = item.get("status", {})
            phase = status.get("phase", "")
            cs = status.get("containerStatuses", []) or []
            restarts = sum(c.get("restartCount", 0) for c in cs)
            ready = sum(1 for c in cs if c.get("ready"))
            total = len(cs)
            reasons = []
            if phase not in HEALTHY_PHASES:
                reasons.append(f"phase={phase}")
            if total and ready < total:
                reasons.append(f"ready={ready}/{total}")
            if restarts >= PROBLEM_RESTART_THRESHOLD:
                reasons.append(f"restarts={restarts}")
            # waiting reasons (CrashLoopBackOff, ImagePullBackOff, ...)
            for c in cs:
                w = (c.get("state", {}) or {}).get("waiting")
                if w and w.get("reason"):
                    reasons.append(w["reason"])
            if reasons:
                problems.append(f"  {ns}/{name}: {', '.join(sorted(set(reasons)))}")

    if problems:
        lines.append(f"⚠ Pods con problemas ({len(problems)}):")
        lines.extend(problems[:40])
        if len(problems) > 40:
            lines.append(f"  ... y {len(problems) - 40} más")
    else:
        lines.append("✓ Sin pods con problemas evidentes (o no se pudo leer).")

    lines.append(
        "\nNota: un fallo de lectura puede deberse a conectividad con el API server "
        f"({config.resolved_context() or 'contexto por defecto'}), no a permisos."
    )
    return "\n".join(lines)
