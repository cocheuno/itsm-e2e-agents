"""Doctor passes only when the checks that exist in Phase 0 pass."""

from e2e.doctor import doctor_ok


def test_absent_phase1_users_do_not_fail() -> None:
    assert doctor_ok(
        admin_ok=True,
        email_ok=True,
        agent_login="ok",
        seed_changes=10,
        pins_ok=True,
        present_users_ok=True,
    )


def test_existing_user_login_failure_fails() -> None:
    assert not doctor_ok(
        admin_ok=True,
        email_ok=True,
        agent_login="ok",
        seed_changes=10,
        pins_ok=True,
        present_users_ok=False,
    )


def test_close_script_targets_fail_the_doctor() -> None:
    assert not doctor_ok(
        admin_ok=True,
        email_ok=True,
        agent_login="ok",
        seed_changes=10,
        pins_ok=True,
        close_script_targets=1,
    )


def test_change_agent_and_seed_are_required() -> None:
    assert not doctor_ok(
        admin_ok=True,
        email_ok=True,
        agent_login="absent",
        seed_changes=10,
        pins_ok=True,
    )
    assert not doctor_ok(
        admin_ok=True,
        email_ok=True,
        agent_login="ok",
        seed_changes=0,
        pins_ok=True,
    )
    assert not doctor_ok(
        admin_ok=True,
        email_ok=False,
        agent_login="ok",
        seed_changes=3,
        pins_ok=True,
    )
