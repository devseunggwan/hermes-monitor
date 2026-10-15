"""Pure account-usage transformations for Hermes Monitor."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any

# Exception class names only: a raw message could carry a token, an absolute home path or a URL.
_SAFE_FAILURE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,59}")

FIVE_HOURS_S = 5 * 3600
ONE_WEEK_S = 7 * 86400
# Published Codex window lengths, keyed by normalized label: agent.account_usage labels Codex
# windows "Session" / "Weekly" by their limit_window_seconds. Other providers carry no such contract.
_CODEX_WINDOW_SECONDS = {"session": FIVE_HOURS_S, "weekly": ONE_WEEK_S}
# The first slice of a window extrapolates from too little usage to mean anything.
PACE_MIN_ELAPSED_FRACTION = 0.05


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _epoch(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp())
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _label_key(value: Any) -> str:
    return str(value or "").lower().replace("-", "_").replace(" ", "_")


def _window(raw: Any, label: str | None = None, seconds: int | None = None) -> dict[str, Any] | None:
    source_label = _value(raw, "label")
    used = _value(raw, "used_percent")
    try:
        percent = float(used)
    except (TypeError, ValueError, OverflowError):
        return None
    window = {"label": label or str(source_label or ""), "used_percent": percent, "reset_at": _epoch(_value(raw, "reset_at"))}
    if seconds is not None:
        window["window_seconds"] = seconds
    return window


def _pace(window: Mapping[str, Any], now: int) -> dict[str, Any] | None:
    """Share of the window elapsed, and when usage at the rate so far runs out if before reset."""
    seconds, reset_at, used = window.get("window_seconds"), window.get("reset_at"), window.get("used_percent")
    if not isinstance(seconds, int) or not isinstance(reset_at, int) or not isinstance(used, float):
        return None
    elapsed = seconds - (reset_at - now)
    if elapsed < seconds * PACE_MIN_ELAPSED_FRACTION or elapsed > seconds:
        return None
    pace: dict[str, Any] = {"expected_percent": round(elapsed / seconds * 100, 1), "exhausts_at": None}
    remaining = reset_at - now
    # Compared without dividing: a near-zero percentage would overflow the projected time.
    if 0 < used < 100 and (100 - used) * elapsed < used * remaining:
        pace["exhausts_at"] = now + int((100 - used) * elapsed / used)
    return pace


def _with_pace(window: dict[str, Any], now: int) -> dict[str, Any]:
    pace = _pace(window, now)
    return {**window, "pace": pace} if pace is not None else window


def _windows(snapshot: Any) -> list[Any]:
    raw = _value(snapshot, "windows", [])
    if isinstance(raw, Mapping):
        return [dict(value, label=_value(value, "label", key)) if isinstance(value, Mapping) else value for key, value in raw.items()]
    return list(raw) if isinstance(raw, (list, tuple)) else []


def _claude(source: Any) -> dict[str, Any]:
    if source is None or isinstance(source, BaseException):
        return {"id": "claude", "label": "Claude", "status": "n/a", "windows": []}
    indexed = {_label_key(_value(item, "label", "")): item for item in _windows(source)}
    # agent.account_usage labels Claude windows "Current session" (five_hour) and "Current week" (seven_day)
    five = next((item for key, item in indexed.items() if key in {"five_hour", "5_hour", "5h", "current_session", "session"}), None)
    week = next((item for key, item in indexed.items() if key in {"seven_day", "7_day", "week", "weekly", "current_week"}), None)
    normalized = [_window(five, "5h", FIVE_HOURS_S), _window(week, "week", ONE_WEEK_S)]
    if any(item is None for item in normalized):
        return {"id": "claude", "label": "Claude", "status": "n/a", "windows": []}
    return {"id": "claude", "label": "Claude", "status": "ok", "windows": normalized}


def _codex(source: Any) -> dict[str, Any]:
    if source is None or isinstance(source, BaseException):
        return {"id": "codex", "label": "Codex", "status": "n/a", "windows": []}
    normalized = [_window(item, seconds=_CODEX_WINDOW_SECONDS.get(_label_key(_value(item, "label")))) for item in _windows(source)]
    if not normalized or any(item is None for item in normalized):
        return {"id": "codex", "label": "Codex", "status": "n/a", "windows": []}
    return {"id": "codex", "label": "Codex", "status": "ok", "windows": normalized}


def _deepseek(source: Any) -> dict[str, Any]:
    unavailable = {"id": "deepseek", "label": "DeepSeek", "status": "n/a", "balance": None, "windows": []}
    if source is None or isinstance(source, BaseException) or not isinstance(source, Mapping):
        return unavailable
    balances = source.get("balance_infos")
    if source.get("is_available") is False or not isinstance(balances, list) or not balances:
        return unavailable
    first = balances[0]
    if not isinstance(first, Mapping):
        return unavailable
    try:
        amount = float(first["total_balance"])
        currency = str(first["currency"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return unavailable
    return {"id": "deepseek", "label": "DeepSeek", "status": "ok", "balance": {"currency": currency, "amount": amount}, "windows": []}


def _generic(source: Any, provider_id: str, label: str) -> dict[str, Any]:
    unavailable = {"id": provider_id, "label": label, "status": "n/a", "windows": []}
    if source is None or isinstance(source, BaseException):
        return unavailable
    normalized = [_window(item) for item in _windows(source)]
    if not normalized or any(item is None for item in normalized):
        return unavailable
    return {"id": provider_id, "label": label, "status": "ok", "windows": normalized}


def _account(raw: Any, transform: Any, index: int, now: int | None = None) -> dict[str, Any]:
    metadata = raw if isinstance(raw, Mapping) and "source" in raw else {"source": raw, "account_label": "default", "active": True}
    source = metadata.get("source")
    normalized = transform(source)
    label = metadata.get("account_label")
    if not isinstance(label, str) or not label.strip() or "@" in label:
        label = f"account {index + 1}"
    plan = _value(source, "plan")
    if not isinstance(plan, str) or "@" in plan or len(plan) > 80:
        plan = None
    status, windows = normalized["status"], normalized.get("windows", [])
    exhausted_until = _epoch(metadata.get("exhausted_until"))
    stale_since = _epoch(metadata.get("stale_since"))
    read_at, benched_at = _value(metadata, "read_at"), _value(metadata, "benched_at")
    if isinstance(read_at, (int, float)) and isinstance(benched_at, (int, float)):
        # Both times known: the held reading is superseded only if it was taken before the bench.
        superseded = read_at < benched_at
    else:
        superseded = stale_since is not None
    if exhausted_until is not None and (status == "n/a" or superseded):
        # Hermes benched this account on a quota 429 until a known reset, and the held figures
        # predate that bench (or there are none). A reading taken after the bench wins, even cached.
        stale_since = None
        status, windows = "exhausted", [{"label": "limit", "used_percent": 100.0, "reset_at": exhausted_until}]
    result = {
        "account_label": label,
        "plan": plan,
        "active": bool(metadata.get("active")),
        "status": status,
        "windows": windows,
        "balance": normalized.get("balance"),
    }
    # Pace extrapolates the reading to now, so it is left out for figures held from an earlier read.
    if status == "ok" and stale_since is None and now is not None:
        result["windows"] = [_with_pace(window, now) for window in windows]
    if stale_since is not None and status == "ok":
        result["stale_since"] = stale_since
    profile = metadata.get("profile")
    if isinstance(profile, str) and profile.strip() and "@" not in profile and len(profile) <= 64:
        result["profile"] = profile.strip()
    return result


def _provider(source: Any, transform: Any, *, key_source: bool = False, now: int | None = None) -> dict[str, Any]:
    envelope = source if isinstance(source, Mapping) and isinstance(source.get("accounts"), list) else None
    raw_accounts = envelope["accounts"] if envelope is not None else [source]
    accounts = [_account(raw, transform, index, now) for index, raw in enumerate(raw_accounts)]
    active = next((account for account in accounts if account["active"]), None)
    identity = transform(None)
    result = {
        "id": identity["id"],
        "label": identity["label"],
        "status": active["status"] if active else "n/a",
        "account_label": active["account_label"] if active else None,
        "plan": active["plan"] if active else None,
        "pool_size": int(envelope.get("pool_size", 0)) if envelope is not None else 0,
        "windows": active["windows"] if active else [],
        "accounts": accounts,
    }
    if identity["id"] == "deepseek":
        result["balance"] = active["balance"] if active else None
    if key_source:
        source_name = envelope.get("key_source") if envelope is not None else None
        result["key_source"] = source_name if isinstance(source_name, str) and "@" not in source_name else None
    failures = envelope.get("failures") if envelope is not None else None
    if isinstance(failures, (list, tuple)):
        safe = sorted({str(item) for item in failures if isinstance(item, str) and _SAFE_FAILURE.fullmatch(item)})
        if safe:
            result["failures"] = safe[:4]
    return result


def build_quotas_response(sources: Mapping[str, Any], *, now: int) -> dict[str, Any]:
    """Build a secret-free payload for every active remote provider."""
    known = {
        "anthropic": (_claude, False),
        "openai-codex": (_codex, False),
        "deepseek": (_deepseek, True),
    }
    known_rank = {"anthropic": 0, "openai-codex": 1, "deepseek": 2}
    providers = []
    for provider_id in sorted(sources, key=lambda item: (known_rank.get(item, 3), item)):
        source = sources.get(provider_id)
        envelope = source if isinstance(source, Mapping) else {}
        if provider_id in known:
            transform, include_key_source = known[provider_id]
        else:
            raw_label = envelope.get("provider_label")
            label = (
                raw_label
                if isinstance(raw_label, str) and raw_label.strip() and "@" not in raw_label
                else provider_id.replace("-", " ").title()
            )
            transform = lambda value, item=provider_id, name=label[:80]: _generic(value, item, name)
            include_key_source = False
        providers.append(_provider(source, transform, key_source=include_key_source, now=int(now)))
    return {
        "generated_at": int(now),
        "providers": providers,
    }
