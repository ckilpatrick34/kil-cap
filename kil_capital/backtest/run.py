"""Run backtests and write reports/<strategy_id>.json + .md and reports/SUMMARY.md.

    python -m kil_capital.backtest.run                 # every registered strategy
    python -m kil_capital.backtest.run --strategy longshot_fade
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import uuid
from pathlib import Path

from ..config import SETTINGS, RiskLimits, ROOT
from ..core.ledger import Ledger, canon
from ..strategies.registry import Registry
from .data import data_hash, load_cache
from .engine import SimConfig, run_backtest


def _git_hash() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        return "nogit"


def _pct(x):
    return "n/a" if x is None else f"{x:.2%}"


def render_md(rep: dict) -> str:
    L = [f"# Backtest report: {rep['strategy_id']}", ""]
    info = rep.get("info", {})
    L += [f"**Strategy:** {info.get('name')} ({info.get('catalog_id')}). **Evidence:** {info.get('evidence')}.",
          f"**Build verdict:** {rep.get('build_verdict', rep.get('verdict'))}  ", ""]
    for n in rep.get("notes", []):
        L.append(f"- {n}")
    o = rep.get("oos")
    if not isinstance(o, dict) or not o.get("bets"):
        L += ["", f"Verdict: **{rep['verdict']}**. Universe markets: {rep.get('universe_markets', 0)}."]
        return "\n".join(L) + "\n"
    L += ["", "## Out-of-sample summary", "",
          "| Item | Value |", "|---|---|",
          f"| ROI after fees | {_pct(o['roi'])} (95% CI {_pct(o['roi_ci95'][0])} … {_pct(o['roi_ci95'][1])}) |",
          f"| Net yield | {_pct(o['net_yield'])} |",
          f"| Hit rate | {_pct(o['hit_rate'])} (avg win ${o['avg_win']:.2f}, avg loss ${o['avg_loss']:.2f}) |",
          f"| Net P&L / capital at risk | ${o['net_pnl']:.2f} / ${o['capital_at_risk']:.2f} |",
          f"| Fees paid | ${o['fees_paid']:.2f} |",
          f"| Sample | {o['events']} independent events, {o['bets']} bets |",
          f"| CLV vs Kalshi close | {o['clv_cents_mean']} c (95% CI {o['clv_ci95']}) |",
          f"| Max drawdown | ${o['max_dd_usd']:.2f} ({o['max_dd_pct_alloc']:.1f}% of allocation) |",
          f"| Longest under water / losing streak | {o['longest_under_water_days']} days / {o['longest_losing_streak']} |",
          f"| Top-5 events' share of P&L | {o['top5_event_share_of_pnl']} |",
          f"| Capacity | median bar volume {o['median_bar_volume']} vs size {o['median_size']} |"]
    if o.get("brier"):
        b = o["brier"]
        L.append(f"| Brier / log loss (model vs market) | {b['model_brier']:.4f} vs {b['market_brier']:.4f} / "
                 f"{b['model_logloss']:.4f} vs {b['market_logloss']:.4f} (n={b['n']}) |")
    mt = rep["multiple_testing"]
    L += [f"| Multiple testing | {mt['variants_tried']} variants, p={mt['p_value']}, BH p={mt['p_bh_adjusted']}, "
          f"deflated-Sharpe prob={mt['deflated_sharpe_prob']} |",
          f"| Power | needs ~{rep['power']['events_needed_80pct']} events for 80% power at +2% ROI; have "
          f"{rep['power']['events_available']} |", ""]
    L += ["## Walk-forward folds (train 120 d, test 30 d, step 30 d) and holdout", "",
          "| Fold | Bets | ROI |", "|---|---|---|"]
    for f in rep["folds"]:
        L.append(f"| {f['fold']} | {f['bets']} | {_pct(f['roi'])} |")
    h = rep.get("holdout", {})
    L.append(f"| holdout | {h.get('bets', 0)} | {_pct(h.get('roi'))} |")
    L += ["", "## Robustness (OOS ROI)", "", "| Variant | ROI |", "|---|---|"]
    for k, v in rep.get("robustness", {}).items():
        L.append(f"| {k} | {_pct(v)} |")
    L += ["", "## Suggested go-live bar (§6.3, guidance only)", ""]
    for r in rep.get("v4_bar", []):
        L.append(f"- {'✓' if r['ok'] else '✗'} {r['item']}: {r['detail']}")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="all")
    ap.add_argument("--allocation", default="5000")
    a = ap.parse_args(argv)
    markets = load_cache(SETTINGS.data_dir / "cache")
    reg = Registry(SETTINGS.mlb_model_dir)
    ids = reg.ids() if a.strategy == "all" else [a.strategy]
    SETTINGS.reports_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(SETTINGS.db_path)
    rows = []
    for sid in ids:
        s = reg.get(sid)
        if sid in ("pm_carson",):
            continue
        if sid == "mlb_model":
            ext = s.external_report() or {"verdict": "PENDING", "notes": ["No report in KIL_MLB_MODEL_DIR yet."]}
            rep = {"strategy_id": sid, "info": s.info(), **ext}
            rep.setdefault("verdict", "PENDING")
        else:
            n_var = max(1, ledger.variants_tried(sid) + 1)
            cfg = SimConfig(allocation=__import__("decimal").Decimal(a.allocation))
            rep = run_backtest(s, markets, cfg, RiskLimits(), n_variants_tried=n_var)
            o = rep.get("oos") if isinstance(rep.get("oos"), dict) else {}
            ledger.record_variant(sid, "default", s.params, o.get("events", 0), o.get("roi", 0),
                                  rep.get("multiple_testing", {}).get("p_value"))
        rep["generated_at"] = time.time()
        rep["data_hash"] = data_hash(markets)
        rep["git_hash"] = _git_hash()
        run_id = uuid.uuid4().hex[:12]
        rep["run_id"] = run_id
        ledger.record_backtest_run(run_id=run_id, strategy_id=sid, version=s.params and canon(s.params)[:60],
                                   data_hash=rep["data_hash"], git_hash=rep["git_hash"],
                                   config_hash=hashlib.sha256(canon(rep.get("config", {})).encode()).hexdigest()[:12],
                                   folds=len(rep.get("folds", [])), verdict=rep.get("verdict"))
        (SETTINGS.reports_dir / f"{sid}.json").write_text(json.dumps(rep, default=str, indent=1))
        (SETTINGS.reports_dir / f"{sid}.md").write_text(render_md(rep) if "oos" in rep or "verdict" in rep else "")
        o = rep.get("oos") if isinstance(rep.get("oos"), dict) else {}
        rows.append(f"| {sid} | {rep.get('verdict')} | {o.get('events', 0)} | {_pct(o.get('roi')) if o else 'n/a'} |")
        print(f"{sid}: {rep.get('verdict')}")
    summ = ["# Backtest summary", "", f"Generated {time.strftime('%Y-%m-%d %H:%M %Z')} from {len(markets)} cached "
            "Kalshi market histories.", "", "| Strategy | Verdict | OOS events | OOS ROI |", "|---|---|---|---|", *rows]
    (SETTINGS.reports_dir / "SUMMARY.md").write_text("\n".join(summ) + "\n")


if __name__ == "__main__":
    main()
