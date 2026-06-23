"""Histórico de sesiones: JSONL append-only en ~/.k3sctl/sessions/.

Una línea por evento. Tipos: user, assistant, command, blocked, cancelled,
remember, diagnose, error, meta. Solo auditoría: NO se reinyecta al modelo.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class History:
    def __init__(self, sessions_dir: Path, session_id: str | None = None):
        self.dir = Path(sessions_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        if session_id is None:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            session_id = f"session-{ts}"
        self.session_id = session_id
        self.path = self.dir / f"{session_id}.jsonl"

    def log(self, event_type: str, **fields) -> None:
        record = {"t": _now_iso(), "type": event_type, **fields}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # -- helpers semánticos -------------------------------------------------
    def user(self, text: str) -> None:
        self.log("user", text=text)

    def assistant(self, text: str) -> None:
        self.log("assistant", text=text)

    def command(self, tool: str, display: str, classification: str, ok: bool) -> None:
        self.log("command", tool=tool, command=display, classification=classification, ok=ok)

    def blocked(self, display: str, reason: str) -> None:
        self.log("blocked", command=display, reason=reason)

    def cancelled(self, display: str) -> None:
        self.log("cancelled", command=display)

    def meta(self, **fields) -> None:
        self.log("meta", **fields)


# ---------------------------------------------------------------------------
# Lectura para el visor de histórico
# ---------------------------------------------------------------------------


def list_sessions(sessions_dir: Path) -> list[dict]:
    """Lista sesiones con un resumen (sin cargar todo en memoria de golpe)."""
    d = Path(sessions_dir)
    if not d.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(d.glob("session-*.jsonl"), reverse=True):
        commands = mutations = 0
        model = None
        first_ts = None
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    first_ts = first_ts or rec.get("t")
                    if rec.get("type") == "command":
                        commands += 1
                        if rec.get("classification") == "mutating":
                            mutations += 1
                    elif rec.get("type") == "meta" and rec.get("model"):
                        model = rec.get("model")
        except OSError:
            continue
        out.append(
            {
                "id": path.stem,
                "path": str(path),
                "started": first_ts,
                "commands": commands,
                "mutations": mutations,
                "model": model,
            }
        )
    return out


def read_session(path: Path) -> list[dict]:
    """Devuelve todos los eventos de una sesión."""
    events: list[dict] = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events
