# MSM automation

Scrapes MoneySuperMarket's real rates-table results for the 7 tracked lenders.
This is the production path - `manual_capture/` is a documented fallback if
this ever stops working (see "If this breaks" below).

## Why this needs a self-hosted runner

MoneySuperMarket's results are fetched by the page's own JS via
`POST /mortgages/rates-table/api/v1/enquiry`. That endpoint is behind
Cloudflare bot management, and it took a few rounds of elimination to find a
combination that gets through:

1. Bare `requests` - blocked (Cloudflare's JS challenge page, no way to pass
   it without a JS engine).
2. Vanilla Playwright, headless or headed - blocked identically on the first
   request, even with a valid session/XSRF token pulled from the live page.
   This is a browser-fingerprint block (CDP leaks like `navigator.webdriver`,
   `Runtime.enable`, etc.), not a rate limit.
3. `patchright` (a Playwright fork that patches those specific CDP leaks),
   headed - works. Confirmed with a real 200 and real product data, run
   locally with a real display.
4. `patchright`, `headless=True` - blocked again. Cloudflare detects
   headless-specific signals beyond what patchright patches. Standard fix:
   run headed under Xvfb (Linux) so Chromium keeps its normal rendering path
   without a physical monitor - `validate-msm-access.yml` proved this works
   mechanically (`navigator.webdriver: False`, real rendering, no JS
   challenge) but still got blocked.
5. That block turned out to be IP-reputation, not fingerprint: the response
   body was Cloudflare's "unusual requests coming from the network you are
   using", and the IP resolved to `AS8075 Microsoft Corporation` - GitHub
   Actions' hosted runners run on Azure, and Cloudflare doesn't like
   datacenter ranges regardless of what browser is behind them.
6. Running from this machine's own (residential) network - works. That's why
   this is a self-hosted runner: the fix isn't a browser at all, it's the IP
   the request comes from.

A consumer VPN (tested reasoning, not empirically - ExpressVPN specifically
was considered and dropped) would not help here and could plausibly be worse:
VPN provider IP ranges are commonly categorised and flagged by threat-intel
systems (including Cloudflare's) precisely because they're shared across many
anonymous users, unlike an ordinary residential ISP address.

## Fixed scenario

By design, not by limitation - this scrapes one fixed scenario rather than a
full matrix:

- Property value: GBP 500,000, deposit GBP 50,000 (90% LTV)
- Journey type: First Time Buyer
- Product type: Fixed only, 2/3/5 year terms
- Region: England, repayment method: Repayment

See `msm_lenders.py` for the constants. Changing any of these is legitimate
(e.g. a different LTV band) but changes what gets captured - it's not just a
performance knob.

## Runner setup (this machine)

Registered under Settings -> Actions -> Runners as `msm-desktop-runner`,
label `msm-scraper`, installed at `C:\actions-runner`. Runs in an interactive
logon session (Scheduled Task `GitHubActionsRunner-MSM`, trigger "at logon",
principal `Interactive`) rather than as a Windows service - this runner
package doesn't even offer a Windows service option (only Linux/macOS `.svc`
templates exist in the release), and a traditional Windows service would run
in Session 0, isolated from the desktop Chromium needs to render into. This
machine needs to be on and logged in for the runner to be listening.

`actions/setup-python` doesn't work on this runner (its installer invocation
fails - it assumes a GitHub-hosted image's preconfigured environment), and
plain `python` on PATH resolves to a Windows Store app-execution-alias stub,
not a real interpreter. Everything here uses `py` (the Python launcher)
instead, which resolves to the real, already-installed Python on this
machine.

## If this breaks

Cloudflare vs. patchright is an active arms race - "works today" isn't
"guaranteed forever." If the daily job starts failing:

1. Re-run `.github/workflows/validate-msm-access.yml` manually - it prints
   clear PASS/FAIL diagnostics without touching `data/rates.json`.
2. If it fails with a Cloudflare challenge page in the output, the
   fingerprint patch likely needs updating (check patchright's releases/issue
   tracker) - that's a `pip install --upgrade patchright` away, potentially.
3. If it fails with "unusual requests coming from the network you are using"
   again, something changed about this machine's IP reputation specifically
   (e.g. a new ISP, a flagged address) rather than the browser layer.
4. Fall back to `manual_capture/` (a bookmarklet-based human-in-the-loop
   capture) if automation stops working entirely and needs time to fix.
