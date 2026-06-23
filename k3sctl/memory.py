"""Memoria persistente: notas estables del cluster en ~/.k3sctl/memory.json.

Formato: {"notes": [{"t": iso8601, "note": str}, ...]}, tope MAX_NOTES.
Escrituras atómicas (write temp + os.replace) con lock de fichero cross-platform
para no pisar escrituras concurrentes del agente y del visor de memoria.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MAX_NOTES = 60


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _file_lock(path: Path):
    """Lock cooperativo simple basado en un fichero .lock (cross-platform).

    No bloqueante "de verdad": reintenta crear el lock con O_EXCL. Suficiente para
    el caso de uso (agente + visor en la misma máquina). Si fcntl/msvcrt están
    disponibles se podría endurecer, pero esto evita dependencias.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = None
    import time

    for _ in range(50):  # ~5s máx
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            time.sleep(0.1)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


class Memory:
    def __init__(self, path: Path):
        self.path = Path(path)

    # -- lectura ------------------------------------------------------------
    def load(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            notes = data.get("notes", [])
            return notes if isinstance(notes, list) else []
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def notes(self) -> list[dict]:
        return self.load()

    def count(self) -> int:
        return len(self.load())

    # -- escritura ----------------------------------------------------------
    def _save(self, notes: list[dict]) -> None:
        notes = notes[-MAX_NOTES:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"notes": notes}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def add(self, note: str) -> dict:
        note = note.strip()
        entry = {"t": _now_iso(), "note": note}
        with _file_lock(self.path):
            notes = self.load()
            notes.append(entry)
            self._save(notes)
        return entry

    def edit(self, index: int, new_note: str) -> bool:
        with _file_lock(self.path):
            notes = self.load()
            if not (0 <= index < len(notes)):
                return False
            notes[index]["note"] = new_note.strip()
            notes[index]["t"] = _now_iso()
            self._save(notes)
        return True

    def delete(self, index: int) -> bool:
        with _file_lock(self.path):
            notes = self.load()
            if not (0 <= index < len(notes)):
                return False
            notes.pop(index)
            self._save(notes)
        return True

    def search(self, query: str) -> list[tuple[int, dict]]:
        q = query.lower().strip()
        return [(i, n) for i, n in enumerate(self.load()) if q in n.get("note", "").lower()]

    # -- para el system prompt ---------------------------------------------
    def as_prompt_block(self) -> str:
        notes = self.load()
        if not notes:
            return ""
        lines = [f"- {n.get('note', '')}" for n in notes]
        return "Conocimiento estable recordado de este cluster:\n" + "\n".join(lines)
