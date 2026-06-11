"""
NSE Institutional Flow Tracker.

Fetches FII/DII cash + F&O activity, NIFTY/BANKNIFTY option chain (PCR + max pain),
and block deals from NSE's public endpoints. Computes 5-day cumulative trends and
prints a daily status verdict.

Honest caveats:
- NSE actively blocks scrapers. The script uses browser-like headers and establishes
  a cookie session first. Even so, NSE may rate-limit or temporarily block your IP.
- All data is end-of-day. By the time you run this after 6:30 PM IST, you see today's
  numbers. Pre-market runs show yesterday's.
- One-day institutional moves are noise. The 5-day cumulative is the actionable signal.
- Run once per evening, log to CSV, build a personal history. The edge compounds.

Usage:
    python3 nse_institutional_flow.py                 # Single run, print + log
    python3 nse_institutional_flow.py --history       # Print last 30 days from CSV
    python3 nse_institutional_flow.py --no-log        # Don't append to CSV

Output:
    Console: formatted status panel with verdict
    CSV log: ~/Documents/fiveema/data/nse_flow_history.csv
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

import requests
import pandas as pd


# ============ CONFIGURATION ============
DATA_DIR = Path.home() / "Documents" / "fiveema" / "data"
LOG_PATH = DATA_DIR / "nse_flow_history.csv"

NSE_BASE = "https://www.nseindia.com"
NSE_HOMEPAGE = f"{NSE_BASE}/"
NSE_API = {
    "fii_dii": f"{NSE_BASE}/api/fiidiiTradeReact",
    "option_chain_nifty": f"{NSE_BASE}/api/option-chain-indices?symbol=NIFTY",
    "option_chain_banknifty": f"{NSE_BASE}/api/option-chain-indices?symbol=BANKNIFTY",
    "block_deal": f"{NSE_BASE}/api/block-deal",
    "participant_wise_oi": f"{NSE_BASE}/api/snapshot-derivatives-equity",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": NSE_BASE,
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


# ============ NSE SESSION ============
def nse_session() -> requests.Session:
    """Set up a requests session that fakes a real browser visit.
    NSE requires you to visit the homepage first to obtain cookies before API calls work.
    """
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        r = s.get(NSE_HOMEPAGE, timeout=10)
        r.raise_for_status()
        time.sleep(1)  # let NSE breathe
    except Exception as e:
        print(f"  warning: couldn't establish NSE session ({e}). API calls may fail.", file=sys.stderr)
    return s


def fetch_json(session: requests.Session, url: str, retries: int = 2) -> Optional[dict]:
    """Fetch JSON from NSE with retry on 401/403. Returns None on persistent failure."""
    for attempt in range(retries + 1):
        try:
            r = session.get(url, timeout=15)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                # Cookies expired. Re-establish.
                time.sleep(2)
                session.get(NSE_HOMEPAGE, timeout=10)
                continue
            print(f"  warning: {url} returned {r.status_code}", file=sys.stderr)
            return None
        except json.JSONDecodeError:
            print(f"  warning: {url} returned non-JSON", file=sys.stderr)
            return None
        except Exception as e:
            print(f"  warning: {url} failed ({e})", file=sys.stderr)
            if attempt < retries:
                time.sleep(2)
                continue
            return None
    return None


# ============ DATA FETCHERS ============
def fetch_fii_dii_cash(session: requests.Session) -> dict:
    """FII/DII cash-market buy/sell from the consolidated daily report.
    Returns dict with 'fii_buy', 'fii_sell', 'fii_net', 'dii_buy', 'dii_sell', 'dii_net'.
    """
    data = fetch_json(session, NSE_API["fii_dii"])
    if not data or not isinstance(data, list):
        return {}
    result = {}
    for row in data:
        category = row.get("category", "").upper()
        if "FII" in category or "FPI" in category:
            result["fii_buy"]  = float(row.get("buyValue",  0) or 0)
            result["fii_sell"] = float(row.get("sellValue", 0) or 0)
            result["fii_net"]  = float(row.get("netValue",  0) or 0)
        elif "DII" in category:
            result["dii_buy"]  = float(row.get("buyValue",  0) or 0)
            result["dii_sell"] = float(row.get("sellValue", 0) or 0)
            result["dii_net"]  = float(row.get("netValue",  0) or 0)
    return result


def parse_expiry(s: str) -> Optional[date]:
    """NSE expiryDate format examples: '12-Jun-2026' or '12 Jun 2026'. Returns date or None."""
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def find_monthly_expiry(expiry_dates: list[str]) -> Optional[str]:
    """Find the monthly expiry — the LAST Thursday-class expiry in the current calendar month
    (or next month if we're past the current month's last expiry).
    NSE shifts to Wednesday if Thursday is a holiday; the rule "last expiry of the month" handles both.
    """
    today = date.today()
    parsed = [(parse_expiry(s), s) for s in expiry_dates]
    parsed = [(d, s) for d, s in parsed if d is not None]
    if not parsed:
        return None
    # Group by (year, month) and pick the LATEST date in each group → that's the monthly
    by_month: dict[tuple, tuple] = {}
    for d, s in parsed:
        key = (d.year, d.month)
        if key not in by_month or d > by_month[key][0]:
            by_month[key] = (d, s)
    monthly_expiries = sorted(by_month.values(), key=lambda x: x[0])
    # Pick the nearest monthly that's today or in the future
    for d, s in monthly_expiries:
        if d >= today:
            return s
    return None


def fetch_option_chain_raw(session: requests.Session, symbol: str) -> Optional[dict]:
    """Fetch raw NSE option chain. Returns whole JSON or None on failure."""
    url = NSE_API["option_chain_nifty"] if symbol == "NIFTY" else NSE_API["option_chain_banknifty"]
    return fetch_json(session, url)


def analyze_expiry(raw_data: dict, target_expiry: str) -> dict:
    """Compute spot, PCR, max pain, top OI strikes for one specific expiry."""
    if not raw_data:
        return {}

    records = raw_data.get("records", {})
    spot = records.get("underlyingValue", 0)
    all_data = records.get("data", [])
    rows = [r for r in all_data if r.get("expiryDate") == target_expiry]

    total_call_oi = 0
    total_put_oi  = 0
    max_call_oi_strike = None
    max_call_oi_value  = 0
    max_put_oi_strike  = None
    max_put_oi_value   = 0
    strikes = []
    call_oi_by_strike = {}
    put_oi_by_strike  = {}

    for row in rows:
        strike = row.get("strikePrice")
        if strike is None:
            continue
        strikes.append(strike)
        ce = row.get("CE", {}) or {}
        pe = row.get("PE", {}) or {}
        call_oi = ce.get("openInterest", 0) or 0
        put_oi  = pe.get("openInterest", 0) or 0
        total_call_oi += call_oi
        total_put_oi  += put_oi
        call_oi_by_strike[strike] = call_oi
        put_oi_by_strike[strike]  = put_oi
        if call_oi > max_call_oi_value:
            max_call_oi_value  = call_oi
            max_call_oi_strike = strike
        if put_oi > max_put_oi_value:
            max_put_oi_value   = put_oi
            max_put_oi_strike  = strike

    pcr = (total_put_oi / total_call_oi) if total_call_oi > 0 else None

    # Max pain — strike that minimizes total option holder pain.
    max_pain = None
    if strikes:
        min_total_loss = float("inf")
        for x in strikes:
            total_loss = 0
            for k in strikes:
                if k > x:
                    total_loss += call_oi_by_strike.get(k, 0) * (k - x)
                elif k < x:
                    total_loss += put_oi_by_strike.get(k, 0) * (x - k)
            if total_loss < min_total_loss:
                min_total_loss = total_loss
                max_pain = x

    return {
        "spot": spot,
        "expiry": target_expiry,
        "pcr": pcr,
        "max_pain": max_pain,
        "total_call_oi": total_call_oi,
        "total_put_oi":  total_put_oi,
        "top_call_oi_strike": max_call_oi_strike,
        "top_put_oi_strike":  max_put_oi_strike,
    }


def fetch_option_chain_both(session: requests.Session, symbol: str) -> dict:
    """Fetch the option chain once and analyze both nearest weekly + monthly expiry."""
    raw = fetch_option_chain_raw(session, symbol)
    if not raw:
        return {"weekly": {}, "monthly": {}}
    records = raw.get("records", {})
    expiry_dates = records.get("expiryDates", [])
    if not expiry_dates:
        return {"weekly": {}, "monthly": {}}

    weekly_expiry = expiry_dates[0]
    monthly_expiry = find_monthly_expiry(expiry_dates) or weekly_expiry

    weekly = analyze_expiry(raw, weekly_expiry)
    monthly = analyze_expiry(raw, monthly_expiry) if monthly_expiry != weekly_expiry else weekly
    return {"weekly": weekly, "monthly": monthly}


def fetch_block_deals(session: requests.Session) -> list[dict]:
    """Fetch today's block deals from NSE's /api/block-deal endpoint.

    NSE aggregates block deals per symbol per session (Session 1 = morning,
    Session 2 = afternoon). There is no public buy-side/sell-side flag — but
    the % change from previous close hints at which way the aggressor leaned.
    Returns list sorted by deal value (largest first).
    """
    data = fetch_json(session, NSE_API["block_deal"])
    if not data:
        return []
    raw = data.get("data", []) or []
    deals = []
    for row in raw:
        value_rupees = row.get("totalTradedValue") or 0
        deals.append({
            "symbol":   row.get("symbol"),
            "session":  row.get("session"),
            "value_cr": value_rupees / 1e7,  # raw rupees → crores
            "qty":      row.get("totalTradedVolume"),
            "price":    row.get("lastPrice"),
            "pchange":  row.get("pchange"),
        })
    deals.sort(key=lambda d: d.get("value_cr") or 0, reverse=True)
    return deals[:20]


# ============ HISTORY (CSV) ============
def load_history() -> pd.DataFrame:
    if not LOG_PATH.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(LOG_PATH, parse_dates=["date"])
    except Exception:
        return pd.DataFrame()


def append_history(record: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    columns = [
        "date", "fii_cash_net", "dii_cash_net",
        "nifty_spot",
        "nifty_pcr_weekly", "nifty_max_pain_weekly",
        "nifty_pcr_monthly", "nifty_max_pain_monthly",
        "banknifty_spot",
        "banknifty_pcr_weekly", "banknifty_max_pain_weekly",
        "banknifty_pcr_monthly", "banknifty_max_pain_monthly",
        "verdict",
    ]
    is_new = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        if is_new:
            w.writeheader()
        w.writerow({k: record.get(k, "") for k in columns})


def cumulative_5day(df: pd.DataFrame, col: str) -> Optional[float]:
    """Sum the last 5 entries of `col`. Returns None if fewer than 2 rows."""
    if df.empty or col not in df.columns or len(df) < 2:
        return None
    return float(pd.to_numeric(df[col].tail(5), errors="coerce").sum())


# ============ VERDICT LOGIC ============
def status_verdict(
    fii_net: Optional[float],
    dii_net: Optional[float],
    fii_5d: Optional[float],
    dii_5d: Optional[float],
    pcr: Optional[float],
) -> tuple[str, str]:
    """Return (verdict, reasoning) string pair.
    Combines today's FII/DII direction, 5-day trend, and PCR.
    """
    reasons = []

    # FII signal
    fii_signal = 0  # -1=bearish, 0=neutral, +1=bullish
    if fii_5d is not None:
        if fii_5d > 2000:
            fii_signal = 1
            reasons.append(f"FII 5-day cumulative +{fii_5d:.0f} Cr (sustained buying)")
        elif fii_5d < -2000:
            fii_signal = -1
            reasons.append(f"FII 5-day cumulative {fii_5d:.0f} Cr (sustained selling)")
        else:
            reasons.append(f"FII 5-day cumulative {fii_5d:+.0f} Cr (neutral)")
    elif fii_net is not None:
        if fii_net > 1000:
            fii_signal = 1
            reasons.append(f"FII today +{fii_net:.0f} Cr (single-day, treat cautiously)")
        elif fii_net < -1000:
            fii_signal = -1
            reasons.append(f"FII today {fii_net:.0f} Cr (single-day, treat cautiously)")

    # DII signal
    dii_signal = 0
    if dii_5d is not None:
        if dii_5d > 2000:
            dii_signal = 1
            reasons.append(f"DII 5-day cumulative +{dii_5d:.0f} Cr (domestic accumulation)")
        elif dii_5d < -2000:
            dii_signal = -1
            reasons.append(f"DII 5-day cumulative {dii_5d:.0f} Cr (domestic distribution)")
    elif dii_net is not None:
        if dii_net > 1000:
            dii_signal = 1
        elif dii_net < -1000:
            dii_signal = -1

    # PCR contrarian signal
    pcr_signal = 0
    if pcr is not None:
        if pcr > 1.5:
            pcr_signal = 1
            reasons.append(f"PCR {pcr:.2f} (excess bearish positioning → contrarian bullish)")
        elif pcr < 0.6:
            pcr_signal = -1
            reasons.append(f"PCR {pcr:.2f} (excess bullish positioning → contrarian bearish)")
        else:
            reasons.append(f"PCR {pcr:.2f} (normal)")

    score = fii_signal + dii_signal + pcr_signal
    if score >= 2:
        verdict = "BULLISH BIAS"
    elif score >= 1:
        verdict = "MILD BULLISH"
    elif score <= -2:
        verdict = "BEARISH BIAS"
    elif score <= -1:
        verdict = "MILD BEARISH"
    else:
        # Special case: FII selling + DII buying = absorption (often holds market up)
        if fii_signal < 0 and dii_signal > 0:
            verdict = "DIVERGENT (DII absorbing FII)"
        else:
            verdict = "MIXED / NEUTRAL"
    return verdict, " | ".join(reasons) if reasons else "insufficient data"


# ============ OUTPUT FORMATTER ============
def fmt_crore(value: Optional[float]) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.0f} Cr"


def print_chain(label: str, weekly: dict, monthly: dict) -> None:
    """Print weekly + monthly option-chain stats side by side."""
    print(f"  {label}")
    spot = weekly.get("spot") or monthly.get("spot")
    if spot:
        print(f"    Spot                          {spot:,.2f}")

    def line(field: str, w_val, m_val, fmt="{:,.2f}") -> str:
        w_str = (fmt.format(w_val) if w_val is not None else "—")
        m_str = (fmt.format(m_val) if m_val is not None else "—")
        return f"    {field:<26}    Weekly: {w_str:>10}   Monthly: {m_str:>10}"

    print(line("Put-Call Ratio",      weekly.get("pcr"),               monthly.get("pcr"),               "{:.2f}"))
    print(line("Max pain strike",     weekly.get("max_pain"),          monthly.get("max_pain"),          "{:,.0f}"))
    print(line("Top Call OI strike",  weekly.get("top_call_oi_strike"),monthly.get("top_call_oi_strike"),"{:,.0f}"))
    print(line("Top Put OI strike",   weekly.get("top_put_oi_strike"), monthly.get("top_put_oi_strike"), "{:,.0f}"))
    print(f"    Weekly expiry:  {weekly.get('expiry','—')}    Monthly expiry: {monthly.get('expiry','—')}")
    print()


def print_panel(snapshot: dict, history: pd.DataFrame) -> None:
    fii_5d = cumulative_5day(history, "fii_cash_net")
    dii_5d = cumulative_5day(history, "dii_cash_net")
    # Verdict uses MONTHLY PCR — that's the institutional read, not the retail-noisy weekly PCR.
    nifty_pcr_for_verdict = snapshot.get("nifty_pcr_monthly") or snapshot.get("nifty_pcr_weekly")
    verdict, reasoning = status_verdict(
        snapshot.get("fii_cash_net"),
        snapshot.get("dii_cash_net"),
        fii_5d,
        dii_5d,
        nifty_pcr_for_verdict,
    )
    snapshot["verdict"] = verdict

    print()
    print("=" * 90)
    print(f"  NSE INSTITUTIONAL FLOW  —  {snapshot['date']}")
    print("=" * 90)
    print()
    print(f"  CASH MARKET")
    print(f"    FII today              {fmt_crore(snapshot.get('fii_cash_net'))}")
    print(f"    DII today              {fmt_crore(snapshot.get('dii_cash_net'))}")
    print(f"    FII 5-day cumulative   {fmt_crore(fii_5d)}")
    print(f"    DII 5-day cumulative   {fmt_crore(dii_5d)}")
    print()

    if snapshot.get("nifty_weekly") or snapshot.get("nifty_monthly"):
        print_chain("NIFTY", snapshot.get("nifty_weekly", {}), snapshot.get("nifty_monthly", {}))

    if snapshot.get("banknifty_weekly") or snapshot.get("banknifty_monthly"):
        print_chain("BANK NIFTY", snapshot.get("banknifty_weekly", {}), snapshot.get("banknifty_monthly", {}))

    deals = snapshot.get("block_deals", [])
    if deals:
        shown = deals[:5]
        print(f"  BLOCK DEALS (top {len(shown)} by value)")
        for d in shown:
            sess  = (d.get("session") or "")[-1:] or "?"          # "Session 1" → "1"
            sym   = (d.get("symbol")  or "?")[:14]
            val   = d.get("value_cr") or 0
            price = d.get("price")
            pch   = d.get("pchange")
            pch_s = f"{pch:+.2f}%" if isinstance(pch, (int, float)) else "    ?"
            price_s = f"₹{price:>6}" if isinstance(price, (int, float)) else "      ?"
            print(f"    S{sess}  {sym:<14}  ₹{val:>7,.1f} Cr  @ {price_s}  ({pch_s})")
        print()

    print(f"  VERDICT:  {verdict}")
    print(f"  reasoning: {reasoning}")
    print()
    print("=" * 72)
    print()


def print_history(n: int = 30) -> None:
    df = load_history()
    if df.empty:
        print("No history logged yet.")
        return
    df = df.sort_values("date").tail(n)
    print(df.to_string(index=False))


# ============ MAIN ============
def is_market_day(d: date) -> bool:
    """Skip weekends. Doesn't handle Indian holidays — if you want that, maintain a list."""
    return d.weekday() < 5  # 0=Mon, 4=Fri


def main():
    parser = argparse.ArgumentParser(description="NSE Institutional Flow Tracker")
    parser.add_argument("--history", action="store_true", help="Show last 30 days from CSV and exit")
    parser.add_argument("--no-log",  action="store_true", help="Don't append today's run to CSV")
    parser.add_argument("--force",   action="store_true", help="Run even on weekends (for testing)")
    args = parser.parse_args()

    if args.history:
        print_history()
        return

    today = date.today()
    if not is_market_day(today) and not args.force:
        print(f"  {today.strftime('%A')} — NSE closed. Skipping. Use --force to override.")
        return

    today_str = today.isoformat()
    print(f"Fetching NSE data for {today_str}…")
    session = nse_session()

    snapshot = {"date": today_str}

    cash = fetch_fii_dii_cash(session)
    snapshot["fii_cash_net"] = cash.get("fii_net")
    snapshot["dii_cash_net"] = cash.get("dii_net")

    time.sleep(1)
    nifty_chains = fetch_option_chain_both(session, "NIFTY")
    snapshot["nifty_weekly"]  = nifty_chains["weekly"]
    snapshot["nifty_monthly"] = nifty_chains["monthly"]
    snapshot["nifty_spot"]                  = nifty_chains["weekly"].get("spot")
    snapshot["nifty_pcr_weekly"]            = nifty_chains["weekly"].get("pcr")
    snapshot["nifty_max_pain_weekly"]       = nifty_chains["weekly"].get("max_pain")
    snapshot["nifty_pcr_monthly"]           = nifty_chains["monthly"].get("pcr")
    snapshot["nifty_max_pain_monthly"]      = nifty_chains["monthly"].get("max_pain")

    time.sleep(1)
    bnf_chains = fetch_option_chain_both(session, "BANKNIFTY")
    snapshot["banknifty_weekly"]  = bnf_chains["weekly"]
    snapshot["banknifty_monthly"] = bnf_chains["monthly"]
    snapshot["banknifty_spot"]              = bnf_chains["weekly"].get("spot")
    snapshot["banknifty_pcr_weekly"]        = bnf_chains["weekly"].get("pcr")
    snapshot["banknifty_max_pain_weekly"]   = bnf_chains["weekly"].get("max_pain")
    snapshot["banknifty_pcr_monthly"]       = bnf_chains["monthly"].get("pcr")
    snapshot["banknifty_max_pain_monthly"]  = bnf_chains["monthly"].get("max_pain")

    time.sleep(1)
    snapshot["block_deals"] = fetch_block_deals(session)

    history = load_history()
    try:
        print_panel(snapshot, history)
    except Exception as e:
        print(f"  (panel print failed: {e}; continuing to save data)")

    if not args.no_log:
        append_history(snapshot)
        print(f"  logged to {LOG_PATH}")


if __name__ == "__main__":
    main()
