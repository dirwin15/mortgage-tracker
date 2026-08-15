# MoneySuperMarket manual capture

MSM's live rates-table results (`POST /mortgages/rates-table/api/v1/enquiry`) are
blocked for automated requests by Cloudflare - confirmed to fail identically in both
headless and headed Playwright, on the very first request, even with a valid session
and XSRF token. That means it's a browser-fingerprint block, not a rate limit, so no
amount of request-throttling or filter-narrowing gets past it from a script.

This bookmarklet instead captures the real JSON MSM's own page fetches, from inside
your actual logged-in-as-a-human browser tab, where Cloudflare has no reason to block
anything.

## Install

1. Open `msm_bookmarklet.bookmarklet.txt` in this folder.
2. Create a new bookmark in your browser (any browser - bookmarklets are universal).
3. Paste the entire contents of that file as the bookmark's URL/address.
4. Name it something like "MSM Capture".

(`msm_bookmarklet.js` is the same code, readable/unminified, if you want to inspect
or edit it before trusting it with a tab that has your session cookies in it.)

## Use

1. Go to the MSM rates-table URL with your filters set (see below).
2. Click the bookmark. A small badge appears bottom-right; it captures the current
   page's data immediately and every page after as you paginate.
3. Click through result pages using MSM's own "next page" controls.
   - If MSM does a full page reload on pagination, the badge (and the fetch hook)
     will reset - just click the bookmark again on each new page. Nothing already
     captured is lost; it's stored in `localStorage`, not memory.
   - If pagination is a soft client-side navigation, one click covers everything.
4. Click the badge to download everything captured so far as one JSON file
   (`msm_capture_YYYY-MM-DD.json`).
5. Shift-click the badge to clear stored data and start a fresh capture session.

## Recommended filters, to cut the ~25 pages down

The default "whole of market" results include every lender on MSM's panel (dozens),
every fee/no-fee variant of near-identical products, and terms you don't track. None
of that is filterable by lender name as far as I found in the sidebar - so the lender
narrowing has to happen after capture (the parser keeps only rows whose lender name
matches the 7 tracked lenders and discards the rest). But these UI filters do reduce
volume up front:

- **Mortgage type**: tick only `Fixed` (do a separate capture pass for `Tracker` if
  you want that product type too - the app's default view is fixed anyway).
- **Mortgage term**: tick `2 years`, `3 years`, `5 years` - untick `Longer than 5
  years` (drops 10yr+ products the app doesn't use).
- Leave the "Only show" section (Decision in Principle, Shared ownership, Shared
  equity, Offset, First Homes, Family assist) all **unticked** - these are
  eligibility-gated niche products, not representative of a standard scenario.
- Untick **"Show green mortgages"** and **"Show current account mortgages"** in
  Additional options - these add conditional variants (new-build-only, requires a
  current account) that inflate the list without being generally available rates.

Because `propertyValue`/`depositAmount` (not a direct LTV field) is what MSM uses to
derive LTV, you'll need one capture pass per LTV band you want to track (60/75/80/
85/90/95%) - each with `depositAmount` set so `depositAmount / propertyValue`
matches that band. That's 6 capture sessions rather than 1, but each should be far
short of 25 pages once the term/type filters above are applied.

## Not yet built

The parser that turns a `msm_capture_*.json` file into the `RateRow` matrix
`run_all.py` expects doesn't exist yet - it needs to be written against the real
field names in an actual captured response, which requires one real capture first
(field names weren't observable from the Cloudflare-blocked automated attempts).
Once you have a sample capture, share its shape (or a few representative rows) and
the parser can be written to match it exactly rather than guessing.
