"""Paths inside this repository. No absolute path and no user name."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def synthetic_dir() -> Path:
    return repo_root() / "data" / "synthetic"


def manifest_path() -> Path:
    return synthetic_dir() / "manifest.json"


def history_path() -> Path:
    return synthetic_dir() / "config_history.jsonl"


def ground_truth_path() -> Path:
    return synthetic_dir() / "ground_truth.json"
