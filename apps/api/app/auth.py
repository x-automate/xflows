"""AuthN/AuthZ for the XFlows API (docs 06 XU-7, fix XF-04).

v1 interim until console-bff session forwarding lands: static caller registry
from settings — ``name|token|role|projects`` entries. Roles map from the XWS
project membership model: operator < reviewer < owner; a caller's project
scope is ``*`` (all projects) or a comma-separated id list.

``auth_mode="off"`` (dev) authenticates every request as an owner.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

from .config import settings

ROLE_RANK = {"operator": 1, "reviewer": 2, "owner": 3}
ADMIN_ROLE = "owner"


@dataclass(frozen=True)
class Caller:
    name: str
    role: str
    projects: frozenset[str] | None  # None = all projects

    @property
    def rank(self) -> int:
        return ROLE_RANK.get(self.role, 0)

    def can_access_project(self, project_id: str | None) -> bool:
        if self.projects is None or project_id is None:
            return True
        return project_id in self.projects


def parse_callers(raw: str) -> dict[str, Caller]:
    """Parse the ``name|token|role|projects`` registry into token -> Caller."""
    callers: dict[str, Caller] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = [part.strip() for part in entry.split("|")]
        if len(parts) < 3 or not parts[1]:
            continue
        name, token, role = parts[0], parts[1], parts[2].lower()
        if role not in ROLE_RANK:
            continue
        projects_raw = parts[3] if len(parts) > 3 else "*"
        if projects_raw.strip() == "*":
            projects: frozenset[str] | None = None
        else:
            projects = frozenset(
                pid.strip() for pid in projects_raw.split(",") if pid.strip()
            )
        callers[token] = Caller(name=name, role=role, projects=projects)
    return callers


ANONYMOUS = Caller(name="anonymous", role=ADMIN_ROLE, projects=None)


def resolve_caller(authorization: str | None, auth_mode: str, api_callers: str) -> Caller:
    """Resolve a Caller from the Authorization header; raises HTTPException."""
    if auth_mode != "token":
        return ANONYMOUS
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    caller = parse_callers(api_callers).get(token)
    if caller is None:
        raise HTTPException(status_code=401, detail="Unknown caller token")
    return caller


def require_project_access(caller: Caller, project_id: str | None = None) -> None:
    if caller.projects is None or project_id is None:
        return
    if project_id not in caller.projects:
        raise HTTPException(status_code=403, detail="Caller has no access to this project")


def require_role(caller: Caller, min_role: str) -> None:
    if caller.rank < ROLE_RANK.get(min_role, 99):
        raise HTTPException(
            status_code=403,
            detail=f"Requires role {min_role} or higher (caller role: {caller.role})",
        )


async def caller_dependency(
    authorization: str | None = Header(default=None),
) -> Caller:
    """FastAPI dependency; reads settings lazily so tests can monkeypatch."""

    return resolve_caller(authorization, settings.auth_mode, settings.api_callers)
