"""Command-line entry point.

Examples:
    analyzer initdb
    analyzer sync-symbols
    analyzer ingest --date 2026-06-30
    analyzer backfill --symbols RELIANCE TCS INFY --years 5
    analyzer status
"""

from __future__ import annotations

import argparse
from datetime import date, datetime

from analyzer.config import get_config
from analyzer.jobs.ingest import open_repo, run_backfill, run_daily_ingest, run_symbol_sync
from analyzer.jobs.backtest import run_full_backtest
from analyzer.jobs.signals import run_signals
from analyzer.jobs.tune import run_tuning
from analyzer.jobs.technicals import run_technicals
from analyzer.jobs.universe import run_universe
from analyzer.logging_setup import configure_logging, get_logger

log = get_logger(__name__)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def cmd_initdb(args) -> int:
    repo = open_repo()
    tables = repo.query_df(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY 1"
    )
    print(f"DB ready at {get_config().db_path}")
    print(f"Tables ({len(tables)}): {', '.join(tables['table_name'])}")
    repo.close()
    return 0


def cmd_sync_symbols(args) -> int:
    repo = open_repo()
    n = run_symbol_sync(repo)
    print(f"Synced {n} symbols.")
    repo.close()
    return 0


def cmd_ingest(args) -> int:
    repo = open_repo()
    result = run_daily_ingest(repo, target_date=_parse_date(args.date))
    print(result)
    repo.close()
    return 0


def cmd_backfill(args) -> int:
    repo = open_repo()
    n = run_backfill(repo, symbols=args.symbols, years=args.years, bulk=args.bulk)
    print(f"Backfilled {n} price rows.")
    repo.close()
    return 0


def cmd_universe(args) -> int:
    repo = open_repo()
    df = run_universe(repo, limit=args.limit)
    if df.empty:
        print("No price data — run 'ingest'/'backfill' first.")
    else:
        approved = int(df["approved"].sum())
        print(f"Universe as of today: {len(df)} evaluated, {approved} approved.")
        if args.show:
            top = repo.query_df(
                "SELECT symbol, approved, ROUND(quality_score,1) AS score, reject_reasons "
                "FROM universe WHERE as_of = (SELECT MAX(as_of) FROM universe) "
                "ORDER BY approved DESC, quality_score DESC LIMIT ?",
                [args.show],
            )
            print(top.to_string(index=False))
    repo.close()
    return 0


def cmd_technicals(args) -> int:
    repo = open_repo()
    summary = run_technicals(repo, refresh_indices=not args.no_indices,
                             incremental=args.incremental)
    print(f"Technicals: {summary}")
    if args.regime:
        rg = repo.query_df(
            "SELECT date, regime, ROUND(nifty_close,0) AS nifty, "
            "ROUND(breadth_above_200dma,0) AS breadth, ROUND(india_vix,1) AS vix "
            "FROM regime_daily ORDER BY date DESC LIMIT ?",
            [args.regime],
        )
        print(rg.to_string(index=False))
    repo.close()
    return 0


def cmd_scan(args) -> int:
    repo = open_repo()
    df = run_signals(repo, as_of=_parse_date(args.date))
    if df.empty:
        print("No signals generated (check regime, universe, and indicator data).")
    else:
        cols = ["symbol", "setup", "grade", "composite_score", "entry_aggressive",
                "stop_loss", "t1", "t2", "rr", "suggested_risk_pct"]
        print(f"{len(df)} signal(s):")
        print(df[cols].to_string(index=False))
        if args.reasons:
            for _, r in df.iterrows():
                print(f"\n{r['symbol']} [{r['setup']}] grade {r['grade']}:")
                for reason in r["reasons"]:
                    print(f"  - {reason}")
    repo.close()
    return 0


def cmd_tune(args) -> int:
    repo = open_repo()
    result = run_tuning(
        repo, args.setup, limit_symbols=args.limit_symbols,
        include_exit_grid=not args.no_exit_grid, apply_weekly_gate=args.weekly_gate,
    )
    best = result["best"]
    m = best["metrics"]
    print(f"\nBEST for {args.setup} (in-sample only):")
    print(f"  overrides: {best['overrides']}")
    print(f"  n={m.get('n_trades')} win%={m.get('win_rate')} pf={m.get('profit_factor')} "
          f"exp={m.get('expectancy_r')}R dd={m.get('max_dd_pct')}%")
    print("\nTop stage-1 combos:")
    for r in result["stage1"]:
        mm = r["metrics"]
        print(f"  n={mm.get('n_trades', 0):4} pf={mm.get('profit_factor', 0)!s:6} "
              f"exp={mm.get('expectancy_r', 0)!s:7} :: {r['overrides']}")
    repo.close()
    return 0


def cmd_backtest(args) -> int:
    repo = open_repo()
    result = run_full_backtest(repo, apply_weekly_gate=args.weekly_gate)
    print(f"Report: {result['report_path']}\n")
    for setup, s in result["summary"].items():
        verdict = "PASS" if s["passed"] else "FAIL"
        extra = f"n_oos={s['n_oos']} pf={s.get('oos_pf')} dd={s.get('oos_dd')}"
        print(f"  {setup:24s} {verdict:5s}  {extra}")
    repo.close()
    return 0


def cmd_daily(args) -> int:
    from analyzer.jobs.daily import run_daily

    repo = open_repo()
    summary = run_daily(repo, target_date=_parse_date(args.date))
    for k, v in summary.items():
        print(f"{k:12s}: {v}")
    repo.close()
    return 0


def cmd_track(args) -> int:
    from analyzer.risk.tracker import outcome_stats, update_signal_outcomes

    repo = open_repo()
    print(update_signal_outcomes(repo))
    stats = outcome_stats(repo)
    if not stats.empty:
        print(stats.to_string(index=False))
    repo.close()
    return 0


def cmd_report(args) -> int:
    from analyzer.notify.report import write_daily_report

    repo = open_repo()
    as_of = _parse_date(args.date) or repo.scalar("SELECT MAX(date) FROM prices_raw")
    if hasattr(as_of, "date"):
        as_of = as_of.date()
    path = write_daily_report(repo, as_of)
    print(f"Report: {path}")
    repo.close()
    return 0


def cmd_position(args) -> int:
    from analyzer.risk.positions import add_position, list_positions, sell_position, set_stop

    repo = open_repo()
    try:
        if args.action == "add":
            pid = add_position(repo, args.symbol, args.qty, args.price, args.sl,
                               note=args.note or "")
            print(f"Added {args.symbol}: {args.qty} @ {args.price}, stop {args.sl} ({pid})")
        elif args.action == "list":
            df = list_positions(repo, include_closed=args.all)
            print(df.to_string(index=False) if not df.empty else "No positions.")
        elif args.action == "set-sl":
            n = set_stop(repo, args.symbol, args.sl)
            print(f"Stop moved to {args.sl} on {n} position(s) in {args.symbol}.")
        elif args.action == "sell":
            res = sell_position(repo, args.symbol, qty=args.qty, price=args.price,
                                note=args.note or "")
            if res["closed"]:
                print(f"Closed {args.symbol} fully ({res['sold']} shares).")
            else:
                print(f"Sold {res['sold']} {args.symbol}; {res['remaining']} still held.")
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        repo.close()
    return 0


def cmd_watch(args) -> int:
    from analyzer.risk.intraday_watch import run_watch

    repo = open_repo()
    result = run_watch(repo, force=args.force)
    print(result)
    repo.close()
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run("analyzer.api.app:app", host=args.host, port=args.port, reload=False)
    return 0


def cmd_bot(args) -> int:
    from analyzer.notify.telegram_bot import run_bot

    repo = open_repo()
    try:
        run_bot(repo)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1
    except KeyboardInterrupt:
        print("\nbot stopped.")
    finally:
        repo.close()
    return 0


def cmd_backup(args) -> int:
    from analyzer.jobs.backup import run_backup

    manifest = run_backup(dest_dir=args.dir, keep=args.keep)
    print(f"Backup: {manifest['snapshot']}  ({manifest['db_size_mb']} MB)")
    print(f"Verified rows: {manifest['verified_counts']}")
    if manifest["pruned_old"]:
        print(f"Pruned {manifest['pruned_old']} old snapshot(s).")
    return 0


def cmd_status(args) -> int:
    repo = open_repo()
    for t in ["symbols", "prices_raw", "prices_adj", "index_prices", "holidays_nse",
              "fundamentals", "universe", "indicators_daily", "regime_daily", "signals",
              "job_runs"]:
        try:
            print(f"{t:16s}: {repo.count(t):>10,} rows")
        except Exception as exc:  # noqa: BLE001
            print(f"{t:16s}: ERROR {exc}")
    recent = repo.query_df(
        "SELECT job, status, rows_written, started FROM job_runs ORDER BY started DESC LIMIT 5"
    )
    if not recent.empty:
        print("\nRecent jobs:")
        print(recent.to_string(index=False))
    repo.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="analyzer", description="Indian stock swing-trade analyzer")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("initdb", help="create/verify the database schema").set_defaults(func=cmd_initdb)
    sub.add_parser("sync-symbols", help="refresh the symbol master from NSE").set_defaults(
        func=cmd_sync_symbols
    )

    pi = sub.add_parser("ingest", help="ingest one day's EOD bhavcopy")
    pi.add_argument("--date", help="YYYY-MM-DD (default: today)")
    pi.set_defaults(func=cmd_ingest)

    pb = sub.add_parser("backfill", help="backfill history via yfinance")
    pb.add_argument("--symbols", nargs="*", help="symbols (default: all in master)")
    pb.add_argument("--years", type=int, help="years of history")
    pb.add_argument("--bulk", action="store_true", help="chunked multi-ticker download (fast)")
    pb.set_defaults(func=cmd_backfill)

    pu = sub.add_parser("universe", help="build the approved universe (Layer 0 + fundamentals)")
    pu.add_argument("--limit", type=int, help="cap tradeable symbols evaluated (spot-check)")
    pu.add_argument("--show", type=int, default=20, help="print top N rows of the result")
    pu.set_defaults(func=cmd_universe)

    pt = sub.add_parser("technicals", help="compute indicators + regime for the universe")
    pt.add_argument("--no-indices", action="store_true", help="skip index refresh")
    pt.add_argument("--regime", type=int, default=10, help="print latest N regime rows")
    pt.add_argument("--incremental", action="store_true",
                    help="recompute only new dates (fast, low-RAM; nightly mode)")
    pt.set_defaults(func=cmd_technicals)

    ps = sub.add_parser("scan", help="generate swing-trade signals for a date")
    ps.add_argument("--date", help="YYYY-MM-DD (default: latest indicator date)")
    ps.add_argument("--reasons", action="store_true", help="print per-signal reasons")
    ps.set_defaults(func=cmd_scan)

    ptu = sub.add_parser("tune", help="grid-search a setup's params (in-sample only)")
    ptu.add_argument("--setup", required=True, help="e.g. B_pullback_trend")
    ptu.add_argument("--limit-symbols", type=int, help="tune on top-N most liquid symbols")
    ptu.add_argument("--no-exit-grid", action="store_true", help="skip stage-2 exit tuning")
    ptu.add_argument("--weekly-gate", action="store_true")
    ptu.set_defaults(func=cmd_tune)

    pbt = sub.add_parser("backtest", help="run in-sample/out-of-sample backtest + gates")
    pbt.add_argument("--weekly-gate", action="store_true", help="apply weekly gate (ablation)")
    pbt.set_defaults(func=cmd_backtest)

    pd_ = sub.add_parser("daily", help="run the full daily EOD pipeline")
    pd_.add_argument("--date", help="YYYY-MM-DD (default: today)")
    pd_.set_defaults(func=cmd_daily)

    sub.add_parser("track", help="update signal outcomes + show live stats").set_defaults(
        func=cmd_track
    )

    pr = sub.add_parser("report", help="(re)build the daily markdown report")
    pr.add_argument("--date", help="YYYY-MM-DD (default: latest price date)")
    pr.set_defaults(func=cmd_report)

    pp = sub.add_parser("position", help="record & manage your actual holdings")
    pp_sub = pp.add_subparsers(dest="action", required=True)
    pa = pp_sub.add_parser("add", help="log a buy: position add SYMBOL QTY PRICE [--sl SL]")
    pa.add_argument("symbol"); pa.add_argument("qty", type=int)
    pa.add_argument("price", type=float)
    pa.add_argument("--sl", type=float,
                    help="stop-loss; OPTIONAL when buying a system signal (stop is "
                         "taken from the signal), REQUIRED for discretionary buys")
    pa.add_argument("--note", help="optional note")
    pl = pp_sub.add_parser("list", help="show holdings with P&L")
    pl.add_argument("--all", action="store_true", help="include closed")
    ps_ = pp_sub.add_parser("set-sl", help="tighten a stop (never widens)")
    ps_.add_argument("symbol"); ps_.add_argument("sl", type=float)
    pc = pp_sub.add_parser("sell", help="sell all, or PART with --qty (rest stays tracked)")
    pc.add_argument("symbol")
    pc.add_argument("--qty", type=int, help="partial quantity (omit = sell all)")
    pc.add_argument("--price", type=float)
    pc.add_argument("--note", help="optional note")
    pp.set_defaults(func=cmd_position)

    pw = sub.add_parser("watch", help="intraday check of holdings (stop breach / sharp drop)")
    pw.add_argument("--force", action="store_true", help="run even outside market hours")
    pw.set_defaults(func=cmd_watch)

    psv = sub.add_parser("serve", help="run the dashboard API")
    psv.add_argument("--host", default="127.0.0.1")
    psv.add_argument("--port", type=int, default=8000)
    psv.set_defaults(func=cmd_serve)

    sub.add_parser("bot", help="run the two-way Telegram bot (log trades by chat)").set_defaults(
        func=cmd_bot
    )

    pbk = sub.add_parser("backup", help="verified local backup of the DB + config + research log")
    pbk.add_argument("--dir", help="backup destination (default: ./backups)")
    pbk.add_argument("--keep", type=int, default=4, help="snapshots to retain")
    pbk.set_defaults(func=cmd_backup)

    sub.add_parser("status", help="show row counts and recent jobs").set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    cfg = get_config()
    configure_logging(cfg.logging.get("level", "INFO"), cfg.logging.get("json", False))
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
