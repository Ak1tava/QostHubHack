"""Pure C2 role/status rules; persistence and object access belong to service."""

from dataclasses import dataclass

from app.core.security import AuthError


PUBLIC_ACTIONS: tuple[str, ...] = (
    "accept", "queue", "reject", "reassign", "start", "pause", "resume",
    "restart", "cancel", "reprioritize",
)

_OPEN_STATUSES = frozenset({
    "ISSUED", "ACCEPTED", "QUEUED", "REJECTED", "IN_PROGRESS", "PAUSED",
    "SUBMITTED", "AI_REVIEW", "REWORK",
})
_WORKER = frozenset({"worker"})
_MASTER = frozenset({"master"})
_SYSTEM = frozenset({"system"})
_START_ACTIONS = frozenset({"start", "resume", "restart"})


@dataclass(frozen=True)
class _Rule:
    sources: frozenset[str]
    roles: frozenset[str]
    target: str | None
    requires_reason: bool = False


_RULES = {
    "accept": _Rule(frozenset({"ISSUED", "QUEUED"}), _WORKER, "ACCEPTED"),
    "queue": _Rule(frozenset({"ISSUED", "ACCEPTED"}), _WORKER, "QUEUED"),
    "reject": _Rule(frozenset({"ISSUED", "ACCEPTED", "QUEUED"}), _WORKER, "REJECTED", True),
    "reassign": _Rule(
        frozenset({"ISSUED", "ACCEPTED", "QUEUED", "REJECTED", "PAUSED"}),
        _MASTER, "ISSUED", True,
    ),
    "start": _Rule(frozenset({"ACCEPTED"}), _WORKER, "IN_PROGRESS"),
    "pause": _Rule(frozenset({"IN_PROGRESS"}), _WORKER, "PAUSED", True),
    "resume": _Rule(frozenset({"PAUSED"}), _WORKER, "IN_PROGRESS"),
    "submit": _Rule(frozenset({"IN_PROGRESS"}), _WORKER, "SUBMITTED"),
    "begin_review": _Rule(frozenset({"SUBMITTED"}), _SYSTEM, "AI_REVIEW"),
    "request_rework": _Rule(
        frozenset({"AI_REVIEW"}), _MASTER | _SYSTEM, "REWORK", True,
    ),
    "restart": _Rule(frozenset({"REWORK"}), _WORKER, "IN_PROGRESS"),
    "close": _Rule(frozenset({"AI_REVIEW"}), _MASTER, "CLOSED"),
    "override_close": _Rule(frozenset({"REWORK"}), _MASTER, "CLOSED", True),
    "cancel": _Rule(_OPEN_STATUSES, _MASTER, "CANCELLED", True),
    "reprioritize": _Rule(_OPEN_STATUSES, _MASTER, None),
}


def _rule(action: str) -> _Rule:
    rule = _RULES.get(action)
    if rule is None:
        raise AuthError(422, "validation_error", "Неизвестное действие с нарядом")
    return rule


def require_action_role(action: str, role: str) -> None:
    """Authorize a command independently of mutable state, including on replay."""
    if role not in _rule(action).roles:
        raise AuthError(403, "forbidden", "Действие недоступно для этой роли")


def transition(status: str, action: str, role: str, reason: str | None = None) -> str:
    rule = _rule(action)
    require_action_role(action, role)
    if status not in rule.sources:
        raise AuthError(409, "invalid_transition", "Действие недоступно в текущем статусе")
    if rule.requires_reason and (reason is None or not reason.strip()):
        raise AuthError(422, "validation_error", "Для действия требуется причина")
    return rule.target or status


def allowed_actions(
    status: str, role: str, *, is_responsible: bool, has_active_order: bool,
) -> list[str]:
    """Return public commands after object access has been checked by service."""
    if role == "worker" and not is_responsible:
        return []
    return [
        action for action in PUBLIC_ACTIONS
        if role in _RULES[action].roles
        and status in _RULES[action].sources
        and not (role == "worker" and has_active_order and action in _START_ACTIONS)
    ]
