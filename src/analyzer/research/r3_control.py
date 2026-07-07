"""EXP-003 control — isolate quality effect from scraped-universe membership bias.

The fundamentals_history universe = top 800 by CURRENT liquidity, which is future
information at historical rebalances. This control runs the same strategies
restricted to that membership WITHOUT the quality gate. The honest quality effect
is (quality-gated) minus (membership-only), not (quality-gated) minus (plain).

Run:  .venv/Scripts/python.exe -m analyzer.research.r3_control
"""

from __future__ import annotations

from datetime import date, datetime

from analyzer.backtest.metrics import compute_metrics
from analyzer.backtest.runner import run_backtest
from analyzer.config import get_config
from analyzer.logging_setup import configure_logging, get_logger
from analyzer.research.momentum import MomentumConfig, load_panels, run_momentum
from analyzer.setups.base import SETUP_A, SETUP_B, SETUP_D

log = get_logger(__name__)


def main() -> None:
    from analyzer.jobs.ingest import open_repo

    configure_logging()
    repo = open_repo()
    try:
        member = set(
            repo.query_df("SELECT DISTINCT symbol FROM fundamentals_history")["symbol"]
        )
        print(f"scraped membership: {len(member)} symbols")

        # --- momentum restricted to membership (no quality gate) -------------
        cfg = MomentumConfig()
        close, tv, nifty, nifty_dma = load_panels(repo)
        keep = [c for c in close.columns if c in member]
        res = run_momentum(close[keep], tv[keep], nifty, nifty_dma, cfg)
        print("\nmomentum_member_only  ", res["stats"]["momentum_plain"])

        # --- setups restricted to membership (no quality gate) ---------------
        app_cfg = get_config()
        dev_start = datetime.strptime(app_cfg.backtest["in_sample"][0], "%Y-%m-%d").date()
        dev_end = date(2023, 12, 31)

        trades = run_backtest(
            repo, app_cfg, setups=[SETUP_A, SETUP_B, SETUP_D],
            start=dev_start, end=dev_end,
            signal_filter=lambda sym, d: sym in member,
        )
        print("\nsetups member-only (no quality gate), DEV:")
        for s, t in trades.items():
            m = compute_metrics(t, dev_start, dev_end) if not t.empty else {"n_trades": 0}
            print(f"  {s:24s} n={m.get('n_trades',0):4} pf={m.get('profit_factor')} "
                  f"exp={m.get('expectancy_r')}")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
