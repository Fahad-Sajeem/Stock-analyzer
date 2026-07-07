"""Signal-generation job (Phase 4). Thin wrapper over the publisher."""

from __future__ import annotations

from datetime import date

from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger
from analyzer.signals.publisher import run_publish_signals

log = get_logger(__name__)


def run_signals(repo, cfg: Config | None = None, as_of: date | None = None):
    cfg = cfg or get_config()
    return run_publish_signals(repo, cfg, as_of)
