import json
import unittest

from dashboard.quotas import build_quotas_response


NOW = 1_700_000_000
CANARY = "canary-value-must-not-appear"


def _claude_snapshot():
    return {
        "windows": [
            {"label": "five_hour", "used_percent": 12.5, "reset_at": NOW + 10},
            {"label": "seven_day", "used_percent": 33, "reset_at": None},
        ]
    }


def _codex_snapshot():
    return {"windows": [{"label": "5 hour", "used_percent": 40, "reset_at": NOW + 20}]}


def _deepseek_snapshot():
    return {
        "is_available": True,
        "balance_infos": [{"currency": "USD", "total_balance": "7.25"}],
    }


def _provider(sources, provider_id):
    result = build_quotas_response(sources, now=NOW)
    provider = next(provider for provider in result["providers"] if provider["id"] == provider_id)
    keys = {"id", "label", "status", "windows"}
    if provider_id == "deepseek":
        keys.add("balance")
    return {key: provider[key] for key in keys}


def test_quota_response_has_exact_provider_order_and_shape():
    sources = {
        "anthropic": _claude_snapshot(),
        "openai-codex": _codex_snapshot(),
        "deepseek": {**_deepseek_snapshot(), "request_key": CANARY},
    }

    result = build_quotas_response(sources, now=NOW)

    assert result["generated_at"] == NOW
    assert [provider["id"] for provider in result["providers"]] == ["claude", "codex", "deepseek"]
    assert [provider["status"] for provider in result["providers"]] == ["ok", "ok", "ok"]
    assert all(set(provider) >= {"account_label", "plan", "pool_size", "accounts"} for provider in result["providers"])
    assert all(set(provider["accounts"][0]) == {
        "account_label", "plan", "active", "status", "windows", "balance"
    } for provider in result["providers"])
    assert result["providers"][2]["key_source"] is None
    assert CANARY not in json.dumps(result)


def test_claude_ok_maps_five_hour_and_seven_day_windows():
    assert _provider({"anthropic": _claude_snapshot()}, "claude") == {
        "id": "claude",
        "label": "Claude",
        "status": "ok",
        "windows": [
            {
                "label": "5h",
                "used_percent": 12.5,
                "reset_at": NOW + 10,
                "window_seconds": 18_000,
                "pace": {"expected_percent": 99.9, "exhausts_at": None},
            },
            {"label": "week", "used_percent": 33.0, "reset_at": None, "window_seconds": 604_800},
        ],
    }


def test_claude_absent_error_and_timeout_are_unavailable():
    expected = {"id": "claude", "label": "Claude", "status": "n/a", "windows": []}
    for source in (None, RuntimeError(CANARY), TimeoutError(CANARY)):
        assert _provider({"anthropic": source}, "claude") == expected


def test_codex_ok_maps_all_plan_windows():
    source = {
        "windows": [
            {"label": "primary", "used_percent": 40, "reset_at": NOW + 20},
            {"label": "secondary", "used_percent": 70.5, "reset_at": NOW + 30},
        ]
    }
    assert _provider({"openai-codex": source}, "codex") == {
        "id": "codex",
        "label": "Codex",
        "status": "ok",
        "windows": [
            {"label": "primary", "used_percent": 40.0, "reset_at": NOW + 20},
            {"label": "secondary", "used_percent": 70.5, "reset_at": NOW + 30},
        ],
    }


def test_codex_absent_error_and_timeout_are_unavailable():
    expected = {"id": "codex", "label": "Codex", "status": "n/a", "windows": []}
    for source in (None, RuntimeError(CANARY), TimeoutError(CANARY)):
        assert _provider({"openai-codex": source}, "codex") == expected


def test_deepseek_ok_maps_only_currency_and_amount():
    assert _provider({"deepseek": {**_deepseek_snapshot(), "secret": CANARY}}, "deepseek") == {
        "id": "deepseek",
        "label": "DeepSeek",
        "status": "ok",
        "balance": {"currency": "USD", "amount": 7.25},
        "windows": [],
    }


def test_deepseek_absent_error_timeout_and_malformed_payload_are_unavailable():
    expected = {
        "id": "deepseek",
        "label": "DeepSeek",
        "status": "n/a",
        "balance": None,
        "windows": [],
    }
    malformed = ({}, {"balance_infos": []}, {"balance_infos": [{}]}, {"balance_infos": "invalid"})
    for source in (None, RuntimeError(CANARY), TimeoutError(CANARY), *malformed):
        assert _provider({"deepseek": source}, "deepseek") == expected


def test_one_failed_provider_does_not_hide_two_healthy_providers():
    result = build_quotas_response(
        {
            "anthropic": RuntimeError(CANARY),
            "openai-codex": _codex_snapshot(),
            "deepseek": _deepseek_snapshot(),
        },
        now=NOW,
    )

    assert [provider["id"] for provider in result["providers"]] == ["claude", "codex", "deepseek"]
    assert [provider["status"] for provider in result["providers"]] == ["n/a", "ok", "ok"]
    assert CANARY not in json.dumps(result)


def test_each_failed_or_malformed_source_degrades_independently():
    result = build_quotas_response(
        {"anthropic": RuntimeError(CANARY), "openai-codex": None, "deepseek": {"error": CANARY}},
        now=NOW,
    )
    assert result["generated_at"] == NOW
    assert [provider["id"] for provider in result["providers"]] == ["claude", "codex", "deepseek"]
    assert [provider["status"] for provider in result["providers"]] == ["n/a", "n/a", "n/a"]
    assert all(provider["accounts"][0]["status"] == "n/a" for provider in result["providers"])
    assert CANARY not in json.dumps(result)


def test_single_active_provider_yields_exactly_one_provider():
    result = build_quotas_response({"openai-codex": _codex_snapshot()}, now=NOW)

    assert [provider["id"] for provider in result["providers"]] == ["codex"]


def test_account_profile_surfaces_from_envelope_and_is_absent_for_plain_snapshot():
    envelope = {
        "accounts": [
            {"account_label": "primary", "active": True, "profile": "profile-alpha", "source": _codex_snapshot()},
        ]
    }
    codex = next(p for p in build_quotas_response({"openai-codex": envelope}, now=NOW)["providers"] if p["id"] == "codex")
    assert codex["accounts"][0]["profile"] == "profile-alpha"

    plain = next(p for p in build_quotas_response({"openai-codex": _codex_snapshot()}, now=NOW)["providers"] if p["id"] == "codex")
    assert "profile" not in plain["accounts"][0]


def test_provider_failures_are_sanitized_to_class_names_and_bounded():
    envelope = {
        "provider_label": "Anthropic",
        "pool_size": 0,
        "accounts": [{"account_label": "default", "active": True, "source": None}],
        "failures": [
            "RuntimeError",
            "../../etc/passwd",
            "sk-live-token",
            "TimeoutError",
            "ClientError",
            "ValueError",
            CANARY,
        ],
    }
    claude = next(p for p in build_quotas_response({"anthropic": envelope}, now=NOW)["providers"] if p["id"] == "claude")

    assert claude["status"] == "n/a"
    assert claude["failures"] == ["ClientError", "RuntimeError", "TimeoutError", "ValueError"]
    assert CANARY not in json.dumps(claude)


def test_provider_without_failures_has_no_failures_key():
    claude = next(
        p for p in build_quotas_response({"anthropic": {"accounts": [{"account_label": "a", "active": True, "source": _claude_snapshot()}]}}, now=NOW)["providers"]
        if p["id"] == "claude"
    )

    assert "failures" not in claude


class _Window:
    """Shape of agent.account_usage.AccountUsageWindow (attributes, not a mapping)."""

    def __init__(self, label, used_percent, reset_at):
        self.label, self.used_percent, self.reset_at = label, used_percent, reset_at


class _Snapshot:
    def __init__(self, windows):
        self.windows, self.plan = tuple(windows), None


def _hermes_claude():
    return _Snapshot([_Window("Current session", 20.0, NOW + 3600), _Window("Current week", 30.0, NOW + 86_400)])


def _account(source, provider="anthropic", **metadata):
    envelope = {"accounts": [{"account_label": "a", "active": True, "source": source, **metadata}]}
    result = build_quotas_response({provider: envelope}, now=NOW)
    return result["providers"][0]["accounts"][0]


def test_hermes_claude_labels_carry_window_lengths_and_pace():
    windows = _account(_hermes_claude())["windows"]

    assert [(w["label"], w["window_seconds"]) for w in windows] == [("5h", 18_000), ("week", 604_800)]
    # 4 h into the session at 20%: 5%/h reaches 100% after the reset in 1 h.
    assert windows[0]["pace"] == {"expected_percent": 80.0, "exhausts_at": None}


def test_pace_projects_exhaustion_before_reset():
    # 2 h into a 5 h window at 60%: 30%/h leaves 40% for 80 min, well before the reset in 3 h.
    snapshot = _Snapshot([_Window("Session", 60.0, NOW + 3 * 3600)])

    window = _account(snapshot, "openai-codex")["windows"][0]

    assert window["pace"] == {"expected_percent": 40.0, "exhausts_at": NOW + 4800}


def test_pace_without_exhaustion_before_reset():
    # 1 day into a week at 10%: the rate so far reaches 100% after the reset.
    snapshot = _Snapshot([_Window("Weekly", 10.0, NOW + 6 * 86_400)])

    window = _account(snapshot, "openai-codex")["windows"][0]

    assert window["pace"] == {"expected_percent": 14.3, "exhausts_at": None}


def test_pace_is_omitted_early_in_a_window_and_for_unknown_lengths():
    snapshot = _Snapshot([
        _Window("Session", 3.0, NOW + 18_000 - 600),  # 10 min into 5 h: under 5% elapsed
        _Window("primary", 40.0, NOW + 3600),  # no published length
        _Window("Weekly", 30.0, None),  # no reset time
        _Window("Weekly", 30.0, NOW + 700_000),  # reset beyond the window length
    ])

    assert all("pace" not in window for window in _account(snapshot, "openai-codex")["windows"])


def test_pace_at_zero_usage_never_projects_exhaustion():
    snapshot = _Snapshot([_Window("Session", 0.0, NOW + 3600)])

    assert _account(snapshot, "openai-codex")["windows"][0]["pace"] == {"expected_percent": 80.0, "exhausts_at": None}


def test_pace_at_a_near_zero_percentage_does_not_overflow():
    snapshot = _Snapshot([_Window("Session", 5e-324, NOW + 3600)])

    assert _account(snapshot, "openai-codex")["windows"][0]["pace"] == {"expected_percent": 80.0, "exhausts_at": None}


def test_pace_is_omitted_for_providers_without_published_window_lengths():
    # A plugin provider may call a window "Weekly" with no guarantee it spans seven days.
    snapshot = _Snapshot([_Window("Weekly", 60.0, NOW + 3 * 3600), _Window("Session", 60.0, NOW + 3600)])

    windows = _account(snapshot, "opencode-zen")["windows"]

    assert all("window_seconds" not in window and "pace" not in window for window in windows)


def test_pace_is_taken_at_the_read_time_of_a_reused_reading():
    # Read 2 h into a 5 h window at 60%, reused 100 s later: projected from the read, not from now.
    read_at = NOW - 100
    snapshot = _Snapshot([_Window("Session", 60.0, read_at + 3 * 3600)])

    window = _account(snapshot, "openai-codex", read_at=read_at)["windows"][0]

    assert window["pace"] == {"expected_percent": 40.0, "exhausts_at": read_at + 4800}


def test_a_window_read_at_full_marks_the_account_exhausted_and_keeps_the_figures():
    # Hermes has not benched this account, but the reading itself shows the weekly limit hit.
    snapshot = _Snapshot([_Window("Current session", 0.0, NOW + 3600), _Window("Current week", 100.0, NOW + 86_400)])

    account = _account(snapshot)

    assert account["status"] == "exhausted"
    assert [(w["label"], w["used_percent"]) for w in account["windows"]] == [("5h", 0.0), ("week", 100.0)]
    assert all("pace" not in window for window in account["windows"])


def test_held_figures_at_full_read_exhausted_not_cached():
    snapshot = _Snapshot([_Window("Current session", 100.0, NOW + 600), _Window("Current week", 40.0, NOW + 86_400)])

    account = _account(snapshot, stale_since=NOW - 300)

    assert account["status"] == "exhausted" and "stale_since" not in account


def test_held_figures_at_full_with_no_reset_time_stay_cached():
    # The window may have reset since the held read, and nothing says when it would.
    snapshot = _Snapshot([_Window("Current session", 100.0, None), _Window("Current week", 40.0, NOW + 86_400)])

    held = _account(snapshot, stale_since=NOW - 300)
    live = _account(snapshot)

    assert held["status"] == "ok" and held["stale_since"] == NOW - 300
    assert live["status"] == "exhausted"


def test_a_full_window_past_its_reset_does_not_mark_the_account_exhausted():
    # Held figures from before the reset: the window has since emptied, so they only read as cached.
    snapshot = _Snapshot([_Window("Current session", 100.0, NOW - 60), _Window("Current week", 40.0, NOW + 86_400)])

    account = _account(snapshot, stale_since=NOW - 7200)

    assert account["status"] == "ok" and account["stale_since"] == NOW - 7200


def test_weekly_exhausted_account_keeps_session_at_zero_and_week_full():
    until = NOW + 2 * 86_400

    for provider, labels in (("anthropic", ("5h", "week")), ("openai-codex", ("Session", "Weekly"))):
        account = _account(None, provider, exhausted_until=until, benched_at=NOW - 18_000)

        assert account["status"] == "exhausted"
        assert [(w["label"], w["used_percent"], w["reset_at"]) for w in account["windows"]] == [
            (labels[0], 0.0, None), (labels[1], 100.0, until),
        ]


def test_weekly_exhausted_session_reads_no_figure_until_a_full_session_has_passed():
    until = NOW + 2 * 86_400

    for metadata in ({"benched_at": NOW - 17_999}, {}):
        account = _account(None, exhausted_until=until, **metadata)

        assert [(w["label"], w["used_percent"]) for w in account["windows"]] == [("5h", None), ("week", 100.0)]


def _held(session_reset, week_reset):
    return _Snapshot([_Window("Current session", 80.0, session_reset), _Window("Current week", 90.0, week_reset)])


def test_bench_within_five_hours_matching_the_held_session_reset_is_session_limited():
    until = NOW + 3600
    account = _account(_held(until + 60, NOW + 3 * 86_400), exhausted_until=until, stale_since=NOW - 600)

    assert [(w["label"], w["used_percent"], w["reset_at"]) for w in account["windows"]] == [
        ("5h", 100.0, until), ("week", None, None),
    ]


def test_bench_within_five_hours_matching_the_held_week_reset_is_week_limited():
    # The weekly reset is 1 h away, so the reset alone cannot tell the two limits apart.
    until = NOW + 3600
    account = _account(_held(NOW + 7200, until), exhausted_until=until, read_at=NOW - 900, benched_at=NOW - 300)

    # Benched 5 min ago: pre-bench session usage may remain, so that row carries no figure.
    assert [(w["label"], w["used_percent"], w["reset_at"]) for w in account["windows"]] == [
        ("5h", None, None), ("week", 100.0, until),
    ]


def test_bench_within_five_hours_without_a_matching_reading_claims_no_figure():
    until = NOW + 18_000  # the boundary still counts as within five hours
    for account in (
        _account(None, exhausted_until=until),
        _account(_held(NOW + 600, NOW + 3 * 86_400), exhausted_until=until, stale_since=NOW - 600),
    ):
        assert [(w["label"], w["used_percent"], w["reset_at"]) for w in account["windows"]] == [
            ("5h", None, until), ("week", None, until),
        ]


def test_exhausted_generic_provider_keeps_a_single_limit_row():
    account = _account(None, "opencode-zen", exhausted_until=NOW + 86_400)

    assert account["windows"] == [{"label": "limit", "used_percent": 100.0, "reset_at": NOW + 86_400}]


def test_pace_is_omitted_for_cached_and_exhausted_accounts():
    cached = _account(_hermes_claude(), stale_since=NOW - 600)
    exhausted = _account(None, exhausted_until=NOW + 3600)

    assert cached["stale_since"] == NOW - 600
    assert all("pace" not in window for window in cached["windows"])
    assert exhausted["status"] == "exhausted"
    assert all("pace" not in window for window in exhausted["windows"])


def load_tests(loader, tests, pattern):
    suite = unittest.TestSuite()
    for name, value in globals().items():
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value, description=name))
    return suite
