# Mortgage Rate Tracker

Tracks UK mortgage rates (90% LTV / 2yr fixed by default, adjustable) across
Nationwide, Barclays, Santander, Halifax, HSBC, NatWest and Lloyds, plotted
against the Bank of England base rate. £0 cost - GitHub Actions + GitHub
Pages, both free tiers.

## How it fits together

```
scraper/          Python. Fetches BoE data + lender rate matrices daily.
data/rates.json    The dataset. Committed by the scrape workflow.
web/               Vite + React frontend. Reads data/rates.json at build time.
.github/workflows/
  scrape.yml       Runs daily, updates data/rates.json, commits it.
  deploy.yml       Triggered by that commit, rebuilds and deploys web/ to Pages.
```

## Get it live: step by step

### 1. Create the GitHub repo
- github.com -> New repository -> name it (e.g. `mortgage-tracker`) -> Public -> don't add a README.

### 2. Push this code
```bash
cd mortgage-tracker
git init
git add .
git commit -m "initial scraper + dashboard"
git branch -M main
git remote add origin https://github.com/<you>/mortgage-tracker.git
git push -u origin main
```

### 3. If your repo name isn't "mortgage-tracker"
Edit `web/vite.config.js` - the `base` value must match your repo name exactly
(e.g. repo `rates-app` -> `base: "/rates-app/"`). Commit and push that change.

### 4. Turn on GitHub Pages
- Repo -> Settings -> Pages -> Source -> **GitHub Actions** (not "Deploy from a branch").
- That's it - no further config, `deploy.yml` handles the rest.

### 5. Run the scraper once, manually
- Repo -> Actions tab -> "Daily rate scrape" -> Run workflow -> Run workflow (green button).
- Wait ~30-60s, then check the run's log. Each lender prints a status line, e.g.:
  ```
  [Nationwide] status=ok rows=12
  [Halifax] status=error rows=0
  ```
- This commits real data to `data/rates.json`, which auto-triggers `deploy.yml`.

### 6. Check the site
- Repo -> Settings -> Pages will show your live URL once `deploy.yml` finishes
  (usually `https://<you>.github.io/mortgage-tracker/`).
- Add it to your phone's home screen (Share -> Add to Home Screen) for an app-like icon.

### 7. If a lender shows "not_found" or "error"
- Send me the `note` field from that lender's entry in `data/rates.json`, or the
  lender's rates page URL, and I'll fix the row-parsing logic in `scraper/lenders.py`.
- Halifax, HSBC, NatWest, and Lloyds are expected to fail right now - they need
  a Playwright-based scraper (see notes in `scraper/lenders.py`), not built yet.

## Local development (optional)
```bash
cd web
npm install
npm run dev       # live-reloading dev server
```

## Notes on the data
- Bank of England series (`data/rates.json` -> `boe`) includes real history back
  to 2022 from day one - that part backfills automatically.
- Per-lender rates only start accumulating from the day the scraper first runs
  successfully - there's no free source for historical per-lender rates, so
  those lines will start as a single point and grow one point per day.
