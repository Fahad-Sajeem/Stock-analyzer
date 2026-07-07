"""Central configuration loader.

Loads ``config.yaml`` into typed, validated pydantic models. Every threshold in
the system is sourced from here — nothing is hardcoded in the logic modules.

Usage:
    from analyzer.config import get_config
    cfg = get_config()          # loads ./config.yaml (or $ANALYZER_CONFIG)
    cfg.risk.capital
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


def _repo_root() -> Path:
    # src/analyzer/config.py -> repo root is three parents up.
    return Path(__file__).resolve().parents[2]


class Paths(BaseModel):
    db: str = "data/analyzer.duckdb"
    charts_dir: str = "charts"
    reports_dir: str = "reports"
    cache_dir: str = "data/cache"


class Market(BaseModel):
    timezone: str = "Asia/Kolkata"
    exchanges: list[str] = ["NSE", "BSE"]
    benchmark_broad: str = "NIFTY 500"
    benchmark_regime: str = "NIFTY 50"


class Ingestion(BaseModel):
    nse_base_url: str
    nse_archives_url: str
    request_timeout_sec: int = 30
    rate_limit_sec: float = 1.5
    max_retries: int = 4
    backoff_base_sec: float = 2.0
    user_agent: str
    backfill_years: int = 10
    yfinance_suffix_nse: str = ".NS"
    yfinance_suffix_bse: str = ".BO"
    reconcile_divergence_pct: float = 0.5


class Tradability(BaseModel):
    min_median_traded_value_cr: float = 3.0
    min_price: float = 20.0
    min_listing_days: int = 200
    min_mcap_cr: float = 500.0
    excluded_bands_pct: list[int] = [5]
    exclude_surveillance: list[str] = ["GSM", "ESM"]
    asm_max_stage: int = 1


class Validation(BaseModel):
    max_daily_move_pct: float = 30.0
    min_volume: int = 0


class Config(BaseModel):
    """Root config. Sub-sections use permissive models where the schema is large
    (technicals/setups/etc.) so the plan can evolve without breaking the loader,
    but the core operational sections are strictly typed."""

    paths: Paths
    market: Market
    ingestion: Ingestion
    tradability: Tradability
    validation: Validation
    # Larger evolving sections kept as dicts for now; typed as they are built out.
    fundamentals: dict = Field(default_factory=dict)
    technicals: dict = Field(default_factory=dict)
    regime: dict = Field(default_factory=dict)
    setups: dict = Field(default_factory=dict)
    signals: dict = Field(default_factory=dict)
    risk: dict = Field(default_factory=dict)
    backtest: dict = Field(default_factory=dict)
    news: dict = Field(default_factory=dict)
    notify: dict = Field(default_factory=dict)
    logging: dict = Field(default_factory=dict)

    # Absolute repo root, injected at load time (not from YAML).
    root: Path = Field(default_factory=_repo_root, exclude=True)

    @model_validator(mode="after")
    def _check_weights(self) -> Config:
        qw = self.fundamentals.get("quality_weights")
        if qw and abs(sum(qw.values()) - 100) > 1e-6:
            raise ValueError(f"fundamentals.quality_weights must sum to 100, got {sum(qw.values())}")
        cw = self.signals.get("composite_weights")
        if cw and abs(sum(cw.values()) - 1.0) > 1e-6:
            raise ValueError(f"signals.composite_weights must sum to 1.0, got {sum(cw.values())}")
        return self

    # --- path helpers: resolve config-relative paths against repo root --------
    def path(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else (self.root / p)

    @property
    def db_path(self) -> Path:
        return self.path(self.paths.db)

    @property
    def cache_path(self) -> Path:
        return self.path(self.paths.cache_dir)

    @property
    def charts_path(self) -> Path:
        return self.path(self.paths.charts_dir)

    @property
    def reports_path(self) -> Path:
        return self.path(self.paths.reports_dir)


def load_config(path: str | Path | None = None) -> Config:
    """Load and validate config from a YAML file.

    Resolution order: explicit ``path`` arg > ``$ANALYZER_CONFIG`` > repo-root
    ``config.yaml``.
    """
    if path is None:
        path = os.environ.get("ANALYZER_CONFIG") or (_repo_root() / "config.yaml")
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return Config(**data)


@lru_cache(maxsize=1)
def get_config() -> Config:
    """Cached singleton accessor used throughout the app."""
    return load_config()
