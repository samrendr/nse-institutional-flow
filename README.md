# NSE Institutional Flow Tracker

Daily FII/DII, options PCR, max pain, and block deals — auto-fetched from NSE, logged to CSV,
published to a self-updating HTML dashboard via GitHub Pages.

## What you get

- **Daily CSV log** of FII/DII cash + NIFTY/BANKNIFTY weekly+monthly option chain metrics
- **Auto-scheduled** to run every weekday at 6:45 PM IST
- **Web dashboard** at `https://<your-github-username>.github.io/<repo-name>/`
- **Two execution modes**:
  - Local: macOS launchd (in `com.fiveema.nseflow.plist`)
  - Cloud: GitHub Actions (in `.github/workflows/daily.yml`)

You can use either or both. They don't conflict — each writes to its own location.

## Files

| File | Purpose |
|---|---|
| `nse_institutional_flow.py` | The fetcher. Pulls FII/DII + option chain + block deals from NSE. |
| `generate_dashboard.py` | Reads the CSV history, writes `docs/index.html`. |
| `requirements.txt` | Python deps (requests, pandas). |
| `.github/workflows/daily.yml` | GitHub Actions cron job — runs both scripts daily. |
| `com.fiveema.nseflow.plist` | macOS launchd config for local automation. |
| `run_daily.sh` | Wrapper called by the plist — fetches, regenerates, commits, pushes. |
| `data/nse_flow_history.csv` | Auto-generated. Persistent daily log. |
| `docs/index.html` | Auto-generated. Served via GitHub Pages. |

---

## Setup — Cloud (GitHub Actions + Pages)

### 1. Initialize git and push to GitHub

```bash
cd ~/Documents/fiveema
git init
git add nse_institutional_flow.py generate_dashboard.py requirements.txt .github/ README.md
git commit -m "initial: NSE flow tracker"

# Create a new public repo on github.com (call it whatever, e.g. "nse-flow")
# Then push:
git branch -M main
git remote add origin https://github.com/<YOUR_USERNAME>/<REPO_NAME>.git
git push -u origin main
```

### 2. Enable GitHub Pages

1. Go to your repo on GitHub → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: **main**, folder: **/docs**
4. Click Save

After the first scheduled run (or a manual trigger — see step 4), your dashboard will be live at
`https://<YOUR_USERNAME>.github.io/<REPO_NAME>/`.

### 3. Verify GitHub Actions has write permission

1. Repo → **Settings** → **Actions** → **General**
2. Under "Workflow permissions", select **Read and write permissions**
3. Save

This lets the bot commit the updated CSV and HTML each day.

### 4. Manually trigger the first run (optional but recommended)

1. Repo → **Actions** tab
2. Click "NSE Daily Flow" in the left sidebar
3. Click **Run workflow** → main → Run

This bootstraps the first CSV row and HTML page, so you don't have to wait until 6:45 PM IST tomorrow.

### 5. Honest caveat: NSE may block cloud IPs

**This is the biggest risk for the cloud setup.** NSE actively geo-restricts their public APIs.
GitHub Actions runs on Microsoft Azure data centers (typically US/EU). NSE may return 401/403
errors to those IPs.

If this happens you'll see warnings in the GitHub Actions log. The workflow is set to **continue
on error** so the dashboard still regenerates from existing history — but new rows won't be added.

**Mitigations if NSE blocks the cloud:**

- **Run locally via launchd** (next section) and keep cloud as backup
- **Run hybrid**: local fetches the data + commits to GitHub; GitHub Pages just hosts the dashboard
- **Use a proxy**: route requests through an Indian residential proxy (costs ₹500-2000/month)
- **Accept partial data**: some endpoints work from anywhere (option chain often does; FII/DII less reliably)

In practice many users start with cloud, observe whether NSE blocks, and switch to local-only or
hybrid if needed.

---

## Setup — Local (macOS launchd)

Use this if you want a guaranteed-working data source (NSE doesn't block Indian residential IPs).
The local job runs `run_daily.sh`, which: fetches → regenerates dashboard → commits → pushes to GitHub.
That means the cloud cron failure is moot — your Mac feeds the dashboard from home each day.

```bash
# 1. Copy plist to launchd's load directory
cp ~/Documents/fiveema/com.fiveema.nseflow.plist ~/Library/LaunchAgents/

# 2. Load and schedule it
launchctl load ~/Library/LaunchAgents/com.fiveema.nseflow.plist

# 3. Verify scheduled
launchctl list | grep fiveema

# 4. Test the wrapper end-to-end (fetch, regen, commit, push)
bash ~/Documents/fiveema/run_daily.sh
```

The job runs daily at 6:45 PM IST. Your Mac must be awake (display can be off, but not in deep sleep).

The first test run must succeed at `git push` — if it doesn't, check `gh auth status` and confirm
the osxkeychain credential helper has your token. launchd jobs in `~/Library/LaunchAgents/` run in
your user session so they inherit keychain access; jobs in `/Library/LaunchDaemons/` would not.

To stop:
```bash
launchctl unload ~/Library/LaunchAgents/com.fiveema.nseflow.plist
```

To inspect what it did most recently:
```bash
tail ~/Documents/fiveema/data/nse_flow_stdout.log
tail ~/Documents/fiveema/data/nse_flow_stderr.log
```

---

## Daily usage

Three ways to view today's signal:

1. **Web dashboard** (recommended) — open `https://<your-username>.github.io/<repo>/` from any device,
   any time. Mobile-friendly. Auto-updates after each daily run.

2. **Local terminal** — `python3 nse_institutional_flow.py` for live console output.

3. **History view** — `python3 nse_institutional_flow.py --history` to dump last 30 days from CSV.

## Verdict logic

The dashboard's headline verdict combines three signals:

| Signal | Bullish | Bearish |
|---|---|---|
| FII 5-day cumulative cash flow | > +₹2,000 Cr | < −₹2,000 Cr |
| DII 5-day cumulative cash flow | > +₹2,000 Cr | < −₹2,000 Cr |
| NIFTY monthly PCR | > 1.5 (contrarian bullish — retail short, smart money long) | < 0.6 (contrarian bearish — retail long, smart money short) |

Scoring:
- 2+ bullish signals → **BULLISH BIAS**
- 1 bullish → **MILD BULLISH**
- FII selling while DII buying → **DIVERGENT (DII absorbing FII)** — common in Indian markets, often resilient
- 1 bearish → **MILD BEARISH**
- 2+ bearish → **BEARISH BIAS**
- Else → **MIXED / NEUTRAL**

## Files generated

Both `data/nse_flow_history.csv` and `docs/index.html` are committed back to the repo by the workflow.
You can scroll through `data/nse_flow_history.csv` directly on GitHub for raw access, or open
the dashboard HTML for visual.

## Troubleshooting

**"GitHub Actions ran but committed no changes."**
NSE probably blocked the cloud IP. Check the workflow logs in the Actions tab. Existing CSV history
is preserved; dashboard still regenerates from what's there.

**"Dashboard shows no data."**
You haven't run the fetcher yet, or all runs failed. Run `python3 nse_institutional_flow.py --force --no-log`
locally to test if your IP works. If it does, commit the CSV manually.

**"NSE rate-limited me locally too."**
Wait an hour. NSE rate limits are aggressive but short-lived. Don't run the fetcher more than once
per ~10 minutes.

**"I want different schedule times."**
- GitHub Actions: edit `.github/workflows/daily.yml`, change the cron expression
- Local launchd: edit `com.fiveema.nseflow.plist`, change Hour/Minute, then unload/reload

## Privacy note

If the repo is public, all your CSV history and HTML dashboard are world-readable. The data
is NSE public data anyway — but if you don't want your trading interests visible, make the repo
private. Private repos require a GitHub Pro plan for GitHub Pages.
