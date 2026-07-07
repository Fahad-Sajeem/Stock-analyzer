"""Manual position ledger — record your actual buys/sells (PLAN 6.2).

This is what makes the CG Power scenario coverable: once a holding is logged
here, BOTH the evening report (stop/target actions) and the intraday watcher
(Telegram alerts) monitor it.

CLI:
    analyzer position add CGPOWER 100 900 --sl 880
    analyzer position list
    analyzer position set-sl CGPOWER 910
    analyzer position close CGPOWER --price 897
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from analyzer.db.repository import new_id
from analyzer.logging_setup import get_logger

log = get_logger(__name__)


def _lookup_signal(repo, symbol: str, entry_date: date) -> dict | None:
    """Most recent signal for the symbol whose entry window covers entry_date."""
    sig = repo.query_df(
        "SELECT signal_id, entry_aggressive, stop_loss, t1, t2, entry_valid_till "
        "FROM signals WHERE symbol = ? ORDER BY date DESC LIMIT 1",
        [symbol],
    )
    if sig.empty:
        return None
    s = sig.iloc[0].to_dict()
    valid_till = pd.Timestamp(s["entry_valid_till"]).date()
    if valid_till < entry_date:
        return {**s, "_expired": True}
    return {**s, "_expired": False}


def add_position(
    repo, symbol: str, qty: int, entry_price: float, stop_loss: float | None = None,
    entry_date: date | None = None, note: str = "",
) -> str:
    """Record a buy.

    ``stop_loss`` may be omitted when the buy follows a SYSTEM SIGNAL: the
    position is linked to the latest valid signal for the symbol and inherits
    its stop (structure-based, so it does not shift with your fill price), and
    your fill-vs-signal slippage is recorded to ``fills`` for the cost model.
    Discretionary buys (no signal) must state a stop explicitly.
    """
    symbol = symbol.upper().strip()
    if qty <= 0 or entry_price <= 0:
        raise ValueError("qty and entry_price must be positive")
    entry_date = entry_date or date.today()

    signal_id = None
    extra_note = ""
    if stop_loss is None:
        sig = _lookup_signal(repo, symbol, entry_date)
        if sig is None:
            raise ValueError(
                f"no system signal found for {symbol} — for a discretionary buy, "
                f"state your stop explicitly with --sl"
            )
        if sig["_expired"]:
            raise ValueError(
                f"latest {symbol} signal expired on {pd.Timestamp(sig['entry_valid_till']).date()} "
                f"— stale setups are void (PLAN 8.1); provide --sl if you bought anyway"
            )
        signal_id = sig["signal_id"]
        stop_loss = float(sig["stop_loss"])
        ref = float(sig["entry_aggressive"])
        slippage_bps = (entry_price - ref) / ref * 1e4
        repo.insert_df("fills", pd.DataFrame([{
            "position_id": "",  # filled below once id exists
            "side": "BUY", "fill_date": entry_date,
            "signal_price": ref, "actual_price": float(entry_price),
            "slippage_bps": round(slippage_bps, 1),
        }]))
        extra_note = f" | signal {signal_id} (T1 {sig['t1']}, T2 {sig['t2']})"
        if entry_price > ref * 1.02:
            log.warning("chase_warning", symbol=symbol, paid=entry_price, ref=ref,
                        hint="paid >2% above the signal entry — outside the plan's no-chase cap")
            extra_note += " | CHASED >2% above signal entry"

    if stop_loss >= entry_price:
        raise ValueError(
            f"stop {stop_loss} must be BELOW entry {entry_price} for a long position"
        )
    known = repo.scalar("SELECT COUNT(*) FROM prices_raw WHERE symbol = ?", [symbol])
    if not known:
        log.warning("position_symbol_unknown", symbol=symbol,
                    hint="no price history; watcher will still try yfinance")
    position_id = new_id("pos_")
    repo.upsert_df("positions", pd.DataFrame([{
        "position_id": position_id, "signal_id": signal_id, "symbol": symbol,
        "qty": int(qty), "entry_price": float(entry_price),
        "entry_date": entry_date, "current_sl": float(stop_loss),
        "status": "OPEN", "booked_pct": 0.0,
        "notes": (note or f"manual entry {datetime.now():%Y-%m-%d %H:%M}") + extra_note,
    }]))
    if signal_id:
        repo.execute(
            "UPDATE fills SET position_id = ? WHERE position_id = '' AND fill_date = ? "
            "AND actual_price = ?",
            [position_id, entry_date, float(entry_price)],
        )
    log.info("position_added", symbol=symbol, qty=qty, entry=entry_price,
             sl=stop_loss, signal=signal_id or "none")
    return position_id


def list_positions(repo, include_closed: bool = False) -> pd.DataFrame:
    where = "" if include_closed else "WHERE p.status IN ('OPEN','PARTIAL')"
    return repo.query_df(
        f"""
        SELECT p.symbol, p.qty, p.entry_price, p.current_sl, p.status,
               p.entry_date, l.close AS last_close,
               ROUND((l.close - p.entry_price) * p.qty, 0) AS pnl,
               ROUND((l.close / p.entry_price - 1) * 100, 2) AS pnl_pct
        FROM positions p
        LEFT JOIN (
            SELECT symbol, close FROM prices_adj
            WHERE (symbol, date) IN (SELECT symbol, MAX(date) FROM prices_adj GROUP BY symbol)
        ) l ON l.symbol = p.symbol
        {where}
        ORDER BY p.entry_date
        """
    )


def set_stop(repo, symbol: str, new_sl: float) -> int:
    """Move a stop. Tightening only — never widen a stop (PLAN 8.2)."""
    symbol = symbol.upper().strip()
    cur = repo.query_df(
        "SELECT position_id, current_sl FROM positions "
        "WHERE symbol = ? AND status IN ('OPEN','PARTIAL')", [symbol],
    )
    if cur.empty:
        raise ValueError(f"no open position in {symbol}")
    n = 0
    for _, row in cur.iterrows():
        if new_sl < float(row["current_sl"]):
            raise ValueError(
                f"refusing to WIDEN stop {row['current_sl']} -> {new_sl} "
                f"(never widen a stop; close the position instead)"
            )
        repo.execute("UPDATE positions SET current_sl = ? WHERE position_id = ?",
                     [new_sl, row["position_id"]])
        n += 1
    log.info("stop_updated", symbol=symbol, new_sl=new_sl, positions=n)
    return n


def _record_sell_fill(repo, position_id: str, qty: int, price: float | None) -> None:
    if price is None:
        return
    repo.insert_df("fills", pd.DataFrame([{
        "position_id": position_id, "side": "SELL", "fill_date": date.today(),
        "signal_price": None, "actual_price": float(price), "slippage_bps": None,
    }]))


def sell_position(
    repo, symbol: str, qty: int | None = None, price: float | None = None, note: str = "",
) -> dict:
    """Sell all or PART of a holding.

    ``qty`` omitted (or >= holding) -> full exit. ``qty`` less than the holding
    -> partial: the remaining shares stay OPEN (status PARTIAL) and the intraday
    watcher keeps tracking them. Lots are reduced FIFO. This is also the
    mechanism for 'book 50% at T1'.
    """
    symbol = symbol.upper().strip()
    lots = repo.query_df(
        "SELECT position_id, qty, entry_price, booked_pct, notes FROM positions "
        "WHERE symbol = ? AND status IN ('OPEN','PARTIAL') ORDER BY entry_date, position_id",
        [symbol],
    )
    if lots.empty:
        raise ValueError(f"no open position in {symbol}")
    total_qty = int(lots["qty"].sum())
    if qty is not None and qty <= 0:
        raise ValueError("sell quantity must be positive")

    stamp = f" | {datetime.now():%Y-%m-%d} @ {price if price else 'mkt'} {note}".rstrip()

    # Full exit.
    if qty is None or qty >= total_qty:
        for _, lot in lots.iterrows():
            repo.execute(
                "UPDATE positions SET status = 'CLOSED', booked_pct = 100.0, notes = ? "
                "WHERE position_id = ?",
                [((lot["notes"] or "") + " | SOLD ALL" + stamp)[:500], lot["position_id"]],
            )
            _record_sell_fill(repo, lot["position_id"], int(lot["qty"]), price)
        log.info("position_closed", symbol=symbol, qty=total_qty, lots=len(lots))
        return {"closed": True, "sold": total_qty, "remaining": 0}

    # Partial exit — reduce lots FIFO.
    remaining_to_sell = int(qty)
    for _, lot in lots.iterrows():
        if remaining_to_sell <= 0:
            break
        lot_qty = int(lot["qty"])
        take = min(lot_qty, remaining_to_sell)
        _record_sell_fill(repo, lot["position_id"], take, price)
        new_qty = lot_qty - take
        if new_qty == 0:
            repo.execute(
                "UPDATE positions SET status='CLOSED', booked_pct=100.0, notes=? "
                "WHERE position_id=?",
                [((lot["notes"] or "") + f" | SOLD {take}" + stamp)[:500], lot["position_id"]],
            )
        else:
            booked = round((1 - new_qty / lot_qty) * 100 + (lot["booked_pct"] or 0), 1)
            repo.execute(
                "UPDATE positions SET qty=?, status='PARTIAL', booked_pct=?, notes=? "
                "WHERE position_id=?",
                [new_qty, min(booked, 99.9),
                 ((lot["notes"] or "") + f" | SOLD {take}" + stamp)[:500], lot["position_id"]],
            )
        remaining_to_sell -= take

    remaining = total_qty - int(qty)
    log.info("position_reduced", symbol=symbol, sold=int(qty), remaining=remaining)
    return {"closed": False, "sold": int(qty), "remaining": remaining}


def close_position(repo, symbol: str, price: float | None = None, note: str = "") -> int:
    """Full exit (back-compat wrapper over ``sell_position``)."""
    result = sell_position(repo, symbol, qty=None, price=price, note=note)
    return 1 if result["closed"] else 0
