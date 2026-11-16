"""Command line. Phase 0 ships doctor and discover."""

from __future__ import annotations

import argparse
import logging
import sys

from cm_agents.settings import SettingsError, redact_text

from e2e.doctor import run_doctor
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
    args = parser.parse_args(argv)
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    configure_logging(settings.secret_values())
    if args.command == "doctor":
        report = run_doctor(settings)
        print(report.text())
        return 0 if report.ok else 1
    from e2e.discover import run_discover

    return run_discover(settings)


if __name__ == "__main__":
    raise SystemExit(main())
