"""Command line for doctor, discover, seed, teardown, tick, run, and scenarios."""

from __future__ import annotations

import argparse
import logging
import sys

from cm_agents.settings import SettingsError, redact_text

from e2e.doctor import run_doctor
from e2e.errors import WorldError
from e2e.settings import load_settings


class _RedactFilter(logging.Filter):
    def __init__(self, secrets: list[str]) -> None:
        super().__init__()
        self._secrets = [secret for secret in secrets if secret]

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage(), self._secrets)
        record.args = ()
        return True


def configure_logging(secrets: list[str]) -> None:
    logging.basicConfig(level=logging.INFO, force=True)
    redactor = _RedactFilter(secrets)
    for handler in logging.getLogger().handlers:
        handler.addFilter(redactor)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="e2e")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check the instance, email, logins, and the change seed")
    sub.add_parser("discover", help="Run the Phase 0 probes and write docs/DISCOVERY.md")
    sub.add_parser("seed", help="Load the e2e world, the endpoint, and the service users")
    sub.add_parser("teardown", help="Remove the e2e world and leave the change seed")
    sub.add_parser("tick", help="Handle incidents, run detection, and advance open cases")
    run = sub.add_parser("run", help="Repeat ticks until one changes nothing")
    run.add_argument("--until-idle", action="store_true", required=True)
    scenario = sub.add_parser("scenario", help="Run an end-to-end scenario")
    scenario_sub = scenario.add_subparsers(dest="scenario_command", required=True)
    scenario_run = scenario_sub.add_parser("run", help="Run E01 through E12, or all")
    scenario_run.add_argument("name", help="E01 through E12, or all")
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    configure_logging(settings.secret_values())
    try:
        if args.command == "doctor":
            report = run_doctor(settings)
            print(report.text())
            return 0 if report.ok else 1
        if args.command == "discover":
            from e2e.discover import run_discover

            return run_discover(settings)
        if args.command == "seed":
            from e2e.seed import run_seed

            return run_seed(settings)
        if args.command == "teardown":
            from e2e.teardown import run_teardown

            return run_teardown(settings)
        if args.command == "tick":
            from e2e.tick import run_tick

            run_tick(settings)
            return 0
        if args.command == "run":
            from e2e.tick import run_until_idle

            run_until_idle(settings)
            return 0
        from e2e.scenarios import run_scenarios

        if args.scenario_command != "run":
            raise WorldError("scenario command must be run")
        return run_scenarios(settings, args.name)
    except WorldError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
