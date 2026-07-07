"""Technical-analysis job (Phase 3): indices -> indicators -> regime.

Ordering matters: indices must exist before relative strength/regime, and
indicators (sma200 per stock) must exist before breadth/regime.
"""

from __future__ import annotations

from analyzer.config import Config, get_config
from analyzer.data.indices import ingest_indices
from analyzer.logging_setup import get_logger
from analyzer.technicals.compute import run_compute_indicators
from analyzer.technicals.regime import run_compute_regime

log = get_logger(__name__)


def run_technicals(
    repo, cfg: Config | None = None, refresh_indices: bool = True,
    incremental: bool = False,
) -> dict:
    cfg = cfg or get_config()
    idx_rows = 0
    if refresh_indices:
        idx_rows = ingest_indices(repo)
    ind_rows = run_compute_indicators(repo, cfg, incremental=incremental)
    regime_rows = run_compute_regime(repo, cfg)
    summary = {"indices": idx_rows, "indicators": ind_rows, "regime": regime_rows,
               "mode": "incremental" if incremental else "full"}
    log.info("technicals_done", **summary)
    return summary
