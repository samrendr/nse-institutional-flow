"""
Generate an HTML dashboard from the NSE flow CSV history.

Reads:  data/nse_flow_history.csv
Writes: docs/index.html

The HTML is self-contained — Chart.js is loaded from a CDN, all data is inlined.
Designed for GitHub Pages: served at https://USERNAME.github.io/REPO/

Mobile-friendly, dark theme, no build step required.
"""

import json
import sys
from datetime import datetime, date, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


DATA_DIR  = Path(__file__).parent / "data"
DOCS_DIR  = Path(__file__).parent / "docs"
CSV_PATH  = DATA_DIR / "nse_flow_history.csv"
HTML_PATH = DOCS_DIR / "index.html"


# ============ LOAD HISTORY ============
def load() -> pd.DataFrame:
    if not CSV_PATH.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(CSV_PATH, parse_dates=["date"])
        return df.sort_values("date").reset_index(drop=True)
    except Exception as e:
        print(f"warning: could not load CSV ({e})", file=sys.stderr)
        return pd.DataFrame()


def fmt_crore(v) -> str:
    if pd.isna(v) or v is None:
        return "—"
    v = float(v)
    sign = "+" if v > 0 else ""
    return f"{sign}{v:,.0f} Cr"


def fmt_num(v, fmt: str = "{:,.2f}") -> str:
    if pd.isna(v) or v is None:
        return "—"
    try:
        return fmt.format(float(v))
    except Exception:
        return str(v)


def verdict_class(v: Optional[str]) -> str:
    if not v or pd.isna(v):
        return "verdict-mixed"
    v = str(v).lower()
    if "bullish bias" in v:
        return "verdict-strong-bull"
    if "mild bullish" in v:
        return "verdict-bull"
    if "divergent" in v:
        return "verdict-divergent"
    if "bearish bias" in v:
        return "verdict-strong-bear"
    if "mild bearish" in v:
        return "verdict-bear"
    return "verdict-mixed"


# ============ BUILD HTML ============
def build_html(df: pd.DataFrame) -> str:
    last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if df.empty:
        latest = {}
    else:
        latest = df.iloc[-1].to_dict()

    # Compute 5-day cumulative
    fii_5d = float(pd.to_numeric(df["fii_cash_net"].tail(5), errors="coerce").sum()) if "fii_cash_net" in df.columns and len(df) > 0 else None
    dii_5d = float(pd.to_numeric(df["dii_cash_net"].tail(5), errors="coerce").sum()) if "dii_cash_net" in df.columns and len(df) > 0 else None

    # Recent rows for the table — last 30 entries
    recent = df.tail(30).iloc[::-1] if not df.empty else df  # newest first

    # JSON data for Chart.js
    if not df.empty:
        last_60 = df.tail(60)
        chart_data = {
            "labels":   [d.strftime("%d %b") for d in last_60["date"]],
            "fii":      [None if pd.isna(v) else float(v) for v in pd.to_numeric(last_60["fii_cash_net"], errors="coerce")],
            "dii":      [None if pd.isna(v) else float(v) for v in pd.to_numeric(last_60["dii_cash_net"], errors="coerce")],
            "nifty":    [None if pd.isna(v) else float(v) for v in pd.to_numeric(last_60["nifty_spot"],   errors="coerce")],
            "nifty_pcr_m": [None if pd.isna(v) else float(v) for v in pd.to_numeric(last_60.get("nifty_pcr_monthly", [None]*len(last_60)), errors="coerce")],
        }
    else:
        chart_data = {"labels": [], "fii": [], "dii": [], "nifty": [], "nifty_pcr_m": []}

    chart_json = json.dumps(chart_data)

    verdict   = latest.get("verdict", "—")
    v_class   = verdict_class(verdict)
    latest_date = latest.get("date", "—")
    if isinstance(latest_date, (pd.Timestamp, datetime)):
        latest_date = latest_date.strftime("%Y-%m-%d (%A)")

    rows_html = ""
    for _, r in recent.iterrows():
        d_str = r["date"].strftime("%Y-%m-%d") if not pd.isna(r["date"]) else "—"
        v_cls = verdict_class(r.get("verdict"))
        rows_html += f"""
          <tr>
            <td>{d_str}</td>
            <td class="num">{fmt_crore(r.get('fii_cash_net'))}</td>
            <td class="num">{fmt_crore(r.get('dii_cash_net'))}</td>
            <td class="num">{fmt_num(r.get('nifty_spot'), "{:,.0f}")}</td>
            <td class="num">{fmt_num(r.get('nifty_pcr_monthly'), "{:.2f}")}</td>
            <td class="num">{fmt_num(r.get('nifty_max_pain_monthly'), "{:,.0f}")}</td>
            <td class="num">{fmt_num(r.get('banknifty_pcr_monthly'), "{:.2f}")}</td>
            <td class="{v_cls}">{r.get('verdict','—')}</td>
          </tr>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NSE Institutional Flow</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  <style>
    :root {{
      --bg:           #0d1117;
      --bg-elevated:  #161b22;
      --border:       #30363d;
      --text:         #e6edf3;
      --text-muted:   #8b949e;
      --green:        #3fb950;
      --red:          #f85149;
      --yellow:       #d29922;
      --blue:         #58a6ff;
      --purple:       #a371f7;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      padding: 16px;
      max-width: 1200px;
      margin: 0 auto;
    }}
    header {{
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
      margin-bottom: 24px;
    }}
    h1 {{ font-size: 22px; font-weight: 600; }}
    .meta {{ color: var(--text-muted); font-size: 12px; margin-top: 4px; }}

    .tabbar {{ display: flex; gap: 4px; margin: 16px 0 24px; border-bottom: 1px solid var(--border); }}
    .tab {{ padding: 10px 18px; color: var(--text-muted); text-decoration: none; font-weight: 600;
      font-size: 13px; border-bottom: 2px solid transparent; }}
    .tab:hover {{ color: var(--text); }}
    .tab.active {{ color: var(--text); border-bottom-color: var(--blue); }}

    .verdict-box {{
      background: var(--bg-elevated);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
      text-align: center;
    }}
    .verdict-label {{ font-size: 12px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 1px; }}
    .verdict {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
    .verdict-strong-bull {{ color: var(--green); }}
    .verdict-bull        {{ color: #56d364; }}
    .verdict-divergent   {{ color: var(--yellow); }}
    .verdict-mixed       {{ color: var(--text-muted); }}
    .verdict-bear        {{ color: #ff7b72; }}
    .verdict-strong-bear {{ color: var(--red); }}

    .grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 24px;
    }}
    @media (max-width: 700px) {{ .grid {{ grid-template-columns: 1fr; }} }}

    .card {{
      background: var(--bg-elevated);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }}
    .card h2 {{
      font-size: 12px;
      text-transform: uppercase;
      color: var(--text-muted);
      letter-spacing: 1px;
      margin-bottom: 12px;
    }}
    .stat-row {{
      display: flex;
      justify-content: space-between;
      padding: 6px 0;
      border-bottom: 1px solid var(--border);
    }}
    .stat-row:last-child {{ border-bottom: none; }}
    .stat-label {{ color: var(--text-muted); }}
    .stat-value {{ font-family: "SF Mono", Monaco, Consolas, monospace; font-weight: 600; }}
    .positive {{ color: var(--green); }}
    .negative {{ color: var(--red); }}

    .chart-section {{
      background: var(--bg-elevated);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      margin-bottom: 24px;
    }}
    .chart-section h2 {{
      font-size: 12px;
      text-transform: uppercase;
      color: var(--text-muted);
      letter-spacing: 1px;
      margin-bottom: 12px;
    }}
    canvas {{ max-height: 280px; }}

    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--bg-elevated);
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      font-size: 12px;
    }}
    th, td {{
      padding: 8px 10px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    th {{
      background: #21262d;
      color: var(--text-muted);
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 1px;
      font-weight: 600;
    }}
    tr:last-child td {{ border-bottom: none; }}
    td.num {{ font-family: "SF Mono", Monaco, Consolas, monospace; text-align: right; }}

    footer {{
      margin-top: 32px;
      padding-top: 16px;
      border-top: 1px solid var(--border);
      text-align: center;
      color: var(--text-muted);
      font-size: 11px;
    }}
    .table-wrap {{ overflow-x: auto; }}
  </style>
</head>
<body>

<header>
  <h1>NSE Institutional Flow</h1>
  <div class="meta">Latest: {latest_date} · Updated {last_updated} · {len(df)} days logged</div>
</header>

<nav class="tabbar">
  <a href="index.html" class="tab active">Institutional Flow</a>
  <a href="gex.html" class="tab">Dealer Gamma (GEX)</a>
</nav>

<div class="verdict-box">
  <div class="verdict-label">Today's Verdict</div>
  <div class="verdict {v_class}">{verdict}</div>
</div>

<div class="grid">
  <div class="card">
    <h2>Cash Market</h2>
    <div class="stat-row">
      <span class="stat-label">FII today</span>
      <span class="stat-value {'positive' if (latest.get('fii_cash_net') or 0) > 0 else 'negative' if (latest.get('fii_cash_net') or 0) < 0 else ''}">{fmt_crore(latest.get('fii_cash_net'))}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">DII today</span>
      <span class="stat-value {'positive' if (latest.get('dii_cash_net') or 0) > 0 else 'negative' if (latest.get('dii_cash_net') or 0) < 0 else ''}">{fmt_crore(latest.get('dii_cash_net'))}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">FII 5-day cumulative</span>
      <span class="stat-value {'positive' if (fii_5d or 0) > 0 else 'negative' if (fii_5d or 0) < 0 else ''}">{fmt_crore(fii_5d)}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">DII 5-day cumulative</span>
      <span class="stat-value {'positive' if (dii_5d or 0) > 0 else 'negative' if (dii_5d or 0) < 0 else ''}">{fmt_crore(dii_5d)}</span>
    </div>
  </div>

  <div class="card">
    <h2>NIFTY 50</h2>
    <div class="stat-row">
      <span class="stat-label">Spot</span>
      <span class="stat-value">{fmt_num(latest.get('nifty_spot'), '{:,.2f}')}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">PCR — Weekly</span>
      <span class="stat-value">{fmt_num(latest.get('nifty_pcr_weekly'), '{:.2f}')}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">PCR — Monthly</span>
      <span class="stat-value">{fmt_num(latest.get('nifty_pcr_monthly'), '{:.2f}')}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Max pain — Weekly</span>
      <span class="stat-value">{fmt_num(latest.get('nifty_max_pain_weekly'), '{:,.0f}')}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Max pain — Monthly</span>
      <span class="stat-value">{fmt_num(latest.get('nifty_max_pain_monthly'), '{:,.0f}')}</span>
    </div>
  </div>

  <div class="card">
    <h2>BANK NIFTY</h2>
    <div class="stat-row">
      <span class="stat-label">Spot</span>
      <span class="stat-value">{fmt_num(latest.get('banknifty_spot'), '{:,.2f}')}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">PCR — Weekly</span>
      <span class="stat-value">{fmt_num(latest.get('banknifty_pcr_weekly'), '{:.2f}')}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">PCR — Monthly</span>
      <span class="stat-value">{fmt_num(latest.get('banknifty_pcr_monthly'), '{:.2f}')}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Max pain — Weekly</span>
      <span class="stat-value">{fmt_num(latest.get('banknifty_max_pain_weekly'), '{:,.0f}')}</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Max pain — Monthly</span>
      <span class="stat-value">{fmt_num(latest.get('banknifty_max_pain_monthly'), '{:,.0f}')}</span>
    </div>
  </div>

  <div class="card">
    <h2>How to read this</h2>
    <p style="color: var(--text-muted); margin-bottom: 10px;">
      The verdict combines FII + DII 5-day positioning with NIFTY monthly PCR.
    </p>
    <ul style="color: var(--text-muted); padding-left: 16px; font-size: 12px;">
      <li><strong style="color: var(--green);">Bullish bias</strong> — at least two signals are bullish</li>
      <li><strong style="color: #d29922;">Divergent</strong> — DII absorbing FII selling, market often resilient</li>
      <li><strong style="color: var(--red);">Bearish bias</strong> — at least two signals are bearish</li>
      <li><strong>Single-day data is noise.</strong> The 5-day cumulative and monthly PCR are the real signals.</li>
    </ul>
  </div>
</div>

<div class="chart-section">
  <h2>FII vs DII — Last 60 Days</h2>
  <canvas id="flowChart"></canvas>
</div>

<div class="chart-section">
  <h2>NIFTY Spot vs Monthly PCR — Last 60 Days</h2>
  <canvas id="niftyChart"></canvas>
</div>

<h2 style="font-size: 12px; text-transform: uppercase; color: var(--text-muted); letter-spacing: 1px; margin-bottom: 12px;">History (last 30 days)</h2>

<div class="table-wrap">
<table>
  <thead>
    <tr>
      <th>Date</th>
      <th>FII Cash</th>
      <th>DII Cash</th>
      <th>NIFTY Spot</th>
      <th>NIFTY PCR (M)</th>
      <th>NIFTY MaxPain (M)</th>
      <th>BNF PCR (M)</th>
      <th>Verdict</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>
</div>

<footer>
  Generated by nse_institutional_flow.py · Updated daily ~13:15 UTC (6:45 PM IST) via GitHub Actions ·
  <a href="https://github.com" style="color: var(--blue);">source</a>
</footer>

<script>
const data = {chart_json};

new Chart(document.getElementById('flowChart'), {{
  type: 'bar',
  data: {{
    labels: data.labels,
    datasets: [
      {{ label: 'FII (₹ Cr)', data: data.fii, backgroundColor: '#58a6ff' }},
      {{ label: 'DII (₹ Cr)', data: data.dii, backgroundColor: '#a371f7' }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      y: {{ grid: {{ color: '#30363d' }}, ticks: {{ color: '#8b949e' }} }},
      x: {{ grid: {{ color: '#30363d' }}, ticks: {{ color: '#8b949e' }} }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }} }}
  }}
}});

new Chart(document.getElementById('niftyChart'), {{
  type: 'line',
  data: {{
    labels: data.labels,
    datasets: [
      {{
        label: 'NIFTY Spot',
        data: data.nifty,
        borderColor: '#3fb950',
        backgroundColor: 'transparent',
        yAxisID: 'y',
        tension: 0.2,
      }},
      {{
        label: 'Monthly PCR',
        data: data.nifty_pcr_m,
        borderColor: '#d29922',
        backgroundColor: 'transparent',
        yAxisID: 'y1',
        tension: 0.2,
      }}
    ]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    scales: {{
      y:  {{ position: 'left',  grid: {{ color: '#30363d' }}, ticks: {{ color: '#8b949e' }} }},
      y1: {{ position: 'right', grid: {{ drawOnChartArea: false }}, ticks: {{ color: '#8b949e' }} }},
      x:  {{ grid: {{ color: '#30363d' }}, ticks: {{ color: '#8b949e' }} }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#e6edf3' }} }} }}
  }}
}});
</script>

</body>
</html>"""


def main():
    df = load()
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    html = build_html(df)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"  wrote {HTML_PATH}  ({len(df)} rows)")


if __name__ == "__main__":
    main()
