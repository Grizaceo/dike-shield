"""Fail-closed per-user filesystem roots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_USER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


@dataclass(frozen=True)
class UserWorkspace:
    users_root: Path
    user_id: str

    def __init__(self, users_root: str | Path, user_id: str):
        if not _USER_ID.fullmatch(user_id):
            raise ValueError("invalid user_id")
        object.__setattr__(self, "users_root", Path(users_root).expanduser().resolve())
        object.__setattr__(self, "user_id", user_id)

    @property
    def root(self) -> Path:
        return self.users_root / self.user_id

    def ensure(self) -> "UserWorkspace":
        for rel in ("vault", "umj", "candidates", "review", "graph", "starter"):
            self.resolve(rel).mkdir(parents=True, exist_ok=True)
        return self

    def resolve(self, relative: str | Path) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError as exc:
            raise ValueError("path escapes user workspace") from exc
        return candidate
