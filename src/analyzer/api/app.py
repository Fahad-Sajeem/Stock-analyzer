"""Dashboard API (PLAN Section 14, v1: FastAPI + a single self-contained page).

Endpoints:
  GET /                    dashboard page (vanilla JS, no build step)
  GET /api/signals?date=   signals for a date (default: latest)
  GET /api/regime          last 60 regime rows
  GET /api/performance     live observational outcome stats per setup
  GET /api/universe        latest approved universe
  /charts/*                generated signal charts (static)

DuckDB is single-writer: endpoints open short-lived READ-ONLY connections, so
the dashboard can run alongside everything except an in-flight write job (a
request during the nightly pipeline may briefly 503 — acceptable for v1).

Run:  analyzer serve --port 8000
"""

from __future__ import annotations

from contextlib import contextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from analyzer.config import get_config
from analyzer.db.repository import Repository

app = FastAPI(title="Stock Analyzer", docs_url="/docs")

_cfg = get_config()
_cfg.charts_path.mkdir(parents=True, exist_ok=True)
app.mount("/charts", StaticFiles(directory=str(_cfg.charts_path)), name="charts")


@contextmanager
def _repo():
    try:
        repo = Repository.open(_cfg.db_path, read_only=True)
    except Exception as exc:  # noqa: BLE001 - writer holds the lock
        raise HTTPException(status_code=503, detail=f"DB busy: {exc}") from exc
    try:
        yield repo
    finally:
        repo.close()


@app.get("/api/signals")
def api_signals(date: str | None = None):
    with _repo() as repo:
        if date is None:
            date = repo.scalar("SELECT MAX(date) FROM signals")
            if date is None:
                return {"date": None, "signals": []}
        rows = repo.query_df(
            "SELECT signal_id, symbol, setup, grade, composite_score, entry_aggressive, "
            "entry_conservative, stop_loss, t1, t2, rr, suggested_risk_pct, reasons, "
            "warnings, chart_path FROM signals WHERE date = ? ORDER BY composite_score DESC",
            [date],
        )
        recs = rows.to_dict(orient="records")
        # DuckDB returns TEXT[] columns as numpy arrays -> coerce for JSON.
        for r in recs:
            for k in ("reasons", "warnings"):
                if r.get(k) is not None and not isinstance(r[k], list):
                    r[k] = [str(x) for x in r[k]]
        return {"date": str(date), "signals": recs}


@app.get("/api/regime")
def api_regime():
    with _repo() as repo:
        rows = repo.query_df(
            "SELECT date, regime, nifty_close, breadth_above_200dma, india_vix "
            "FROM regime_daily ORDER BY date DESC LIMIT 60"
        )
        return rows.to_dict(orient="records")


@app.get("/api/performance")
def api_performance():
    from analyzer.risk.tracker import outcome_stats

    with _repo() as repo:
        stats = outcome_stats(repo)
        open_n = repo.scalar("SELECT COUNT(*) FROM signal_outcomes WHERE outcome = 'OPEN'")
        return {"per_setup": stats.to_dict(orient="records"), "open_signals": int(open_n or 0)}


@app.get("/api/universe")
def api_universe():
    with _repo() as repo:
        rows = repo.query_df(
            "SELECT symbol, ROUND(quality_score, 1) AS quality_score FROM universe "
            "WHERE as_of = (SELECT MAX(as_of) FROM universe) AND approved "
            "ORDER BY quality_score DESC"
        )
        return rows.to_dict(orient="records")


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Stock Analyzer</title>
<style>
 body{font-family:system-ui,sans-serif;margin:24px;max-width:1100px}
 h1{font-size:20px} h2{font-size:16px;margin-top:28px}
 table{border-collapse:collapse;width:100%;font-size:13px}
 th,td{border:1px solid #ddd;padding:5px 8px;text-align:left}
 th{background:#f5f5f5} .warn{color:#b45309;font-size:12px}
 .banner{padding:10px 14px;border-radius:8px;background:#eef2ff;margin:12px 0;font-weight:600}
 .BEAR{background:#fee2e2}.BULL{background:#dcfce7}.RISK_OFF{background:#fecaca}
 .muted{color:#666;font-size:12px}
</style></head><body>
<h1>Stock Analyzer — observational dashboard</h1>
<div class="muted">Educational analytics, not investment advice. All setups UNVALIDATED —
this feed exists to collect live outcomes.</div>
<div id="regime" class="banner">loading regime…</div>
<h2>Latest signals</h2><div id="signals">loading…</div>
<h2>Live observational performance</h2><div id="perf">loading…</div>
<script>
async function j(u){const r=await fetch(u);if(!r.ok)throw new Error(r.status);return r.json()}
function table(rows, cols){if(!rows.length)return '<i>none</i>';
 let h='<table><tr>'+cols.map(c=>`<th>${c}</th>`).join('')+'</tr>';
 for(const r of rows){h+='<tr>'+cols.map(c=>`<td>${r[c]??''}</td>`).join('')+'</tr>'}
 return h+'</table>'}
(async()=>{
 try{const reg=await j('/api/regime');const r=reg[0]||{};
  const el=document.getElementById('regime');
  el.textContent=`Regime ${r.regime??'?'} | Nifty ${Math.round(r.nifty_close??0)} | breadth ${Math.round(r.breadth_above_200dma??0)}% | VIX ${r.india_vix??'n/a'} | as of ${r.date??''}`;
  el.classList.add(r.regime);
 }catch(e){document.getElementById('regime').textContent='regime unavailable: '+e}
 try{const s=await j('/api/signals');
  const rows=s.signals.map(x=>({symbol:`<a href="${x.chart_path?'/charts/'+x.chart_path.split(/charts[\\\\/]/).pop().replace(/\\\\/g,'/'):'#'}">${x.symbol}</a>`,
   setup:x.setup,grade:x.grade,score:x.composite_score,entry:x.entry_aggressive,stop:x.stop_loss,
   T1:x.t1,T2:x.t2,RR:x.rr}));
  document.getElementById('signals').innerHTML=`<div class="muted">date: ${s.date}</div>`+
   table(rows,['symbol','setup','grade','score','entry','stop','T1','T2','RR']);
 }catch(e){document.getElementById('signals').textContent='unavailable: '+e}
 try{const p=await j('/api/performance');
  document.getElementById('perf').innerHTML=
   table(p.per_setup,['setup','n','triggered','win_pct','sum_r','avg_r'])+
   `<div class="muted">open signals in flight: ${p.open_signals}</div>`;
 }catch(e){document.getElementById('perf').textContent='unavailable: '+e}
})();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return _PAGE
