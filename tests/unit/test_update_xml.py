"""Customer-update classification order."""

from e2e.data.history import Ledger
from e2e.update_xml import classify_text

APPROVED_ID = "638460b6b70023008ef6eac7ee11a9f2"
KNOWN = "a" * 32
ENDPOINT = "b" * 32


def test_approved_wins_over_the_endpoint_name() -> None:
    kind, detail = classify_text(
        f"{APPROVED_ID} syne2e_problem_state",
        {KNOWN},
        {ENDPOINT},
    )
    assert kind == "approved"
    assert "change.conflict.ci_maint_sched" in detail


def test_endpoint_wins_over_a_known_sys_id() -> None:
    kind, _detail = classify_text(f"row {ENDPOINT} {KNOWN}", {KNOWN, ENDPOINT}, {ENDPOINT})
    assert kind == "endpoint"


def test_manifest_and_hand_made() -> None:
    assert classify_text(f"row {KNOWN}", {KNOWN})[0] == "manifest"
    kind, detail = classify_text("snc_basic_auth_api_access role", set())
    assert kind == "hand_made"
    assert "Part B5" in detail
    assert classify_text("u_syn_e2e_inc_import u_caused_by", set()) == ("manifest", "change seed")
    assert classify_text("SYN-PROBE rotate tls", set()) == ("manifest", "change seed")
    assert classify_text("glide.db.instant_alter.enabled", set())[0] == "platform"
    assert classify_text("sys_script_include unexpected", set()) is None


def test_ledger_writes_create_once(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config_history.jsonl"
    monkeypatch.setattr("e2e.data.history.history_path", lambda: path)
    ledger = Ledger()
    ledger.create("incident", KNOWN, "one")
    ledger.create("incident", KNOWN, "one")
    ledger.delete("incident", KNOWN, "one")
    text = path.read_text(encoding="utf-8")
    assert text.count('"action": "create"') == 1
    assert text.count('"action": "delete"') == 1
