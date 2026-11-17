"""Errors whose text is safe to print. No host, no password, no user name."""


class WorldError(RuntimeError):
    """Seed, teardown, or a gate probe failed."""
