import React, { useMemo, useState, useEffect } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";

// ---- Config ----
// Property value, LTV, and product type are fixed to match exactly what the
// scraper captures (see scraper/msm_automation/msm_lenders.py) - MSM returns
// rates computed for a specific loan, not a generic curve, so letting these
// be "adjustable" here would just relabel the same underlying 500k/90%/Fixed
// data rather than actually change what's shown. Fix length and repayment
// term stay adjustable since the scraper covers both fix lengths and the
// repayment term only drives client-side payment math, not which rate row
// is picked.
const HOUSE_VALUE = 500_000;
const LTV_BAND = 90;
const DEPOSIT = Math.round(HOUSE_VALUE * (1 - LTV_BAND / 100));
const LOAN_AMOUNT = HOUSE_VALUE - DEPOSIT;
const FIX_LENGTHS = [2, 3]; // scraper only captures 2/3yr fixed (see scraper/msm_automation)
const LOAN_TERMS = [25, 30];
const LENDER_PALETTE = [
  "#5EEAD4",
  "#60A5FA",
  "#F472B6",
  "#FBBF24",
  "#A78BFA",
  "#FB923C",
  "#4ADE80",
  "#F59E0B",
  "#34D399",
  "#FCA5A5",
  "#93C5FD",
  "#C4B5FD",
];

function lenderColor(lender, index) {
  return LENDER_PALETTE[index % LENDER_PALETTE.length];
}

// ---- Sample data generator: shape-matches data/rates.json's lender matrix
// (90% LTV / Fixed 2yr+3yr only, matching what the real scraper produces).
// Swap this for a real fetch of data/rates.json once the scraper is live. ----
function genMatrixHistory(baseRate, days, seed) {
  const today = new Date();
  const history = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const date = d.toISOString().slice(0, 10);
    const rates = FIX_LENGTHS.map((fix, fIdx) => {
      const base = baseRate + fix * 0.06; // longer fixes ~slightly costlier here
      const wiggle = Math.sin((i + seed + fIdx) / 6) * 0.02;
      const drift = -0.003 * (days - i);
      const rate = Math.round((base + wiggle + drift) * 100) / 100;
      return {
        ltv_band: LTV_BAND,
        product_type: "fixed",
        fix_years: fix,
        fix_months: fix * 12,
        rate_pct: rate,
        product_fee: 999,
        total_fees: 999,
        follow_on_rate_pct: Math.round((rate + 1.6) * 100) / 100,
      };
    });
    history.push({ date, status: "ok", rates });
  }
  return history;
}

const SAMPLE_LENDERS = {
  Nationwide: genMatrixHistory(4.85, 60, 1),
  Barclays: genMatrixHistory(4.90, 60, 2),
  Santander: genMatrixHistory(4.95, 60, 3),
  Halifax: genMatrixHistory(4.92, 60, 4),
  HSBC: genMatrixHistory(4.88, 60, 5),
  NatWest: genMatrixHistory(4.87, 60, 6),
  Lloyds: genMatrixHistory(4.93, 60, 7),
};

const SAMPLE_BOE_BASE = (() => {
  const today = new Date();
  const out = [];
  for (let i = 59; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    out.push({ date: d.toISOString().slice(0, 10), rate: 3.75 });
  }
  return out;
})();

// ---- Real data loading: fetches data/rates.json (copied into public/ by CI on each
// scrape). Falls back to the generated sample data above if it's missing/empty, e.g.
// before the scraper has run for the first time. ----
function useRatesData() {
  const [state, setState] = useState({
    loading: true, live: false, lenders: SAMPLE_LENDERS, boeBase: SAMPLE_BOE_BASE, trackingStart: null,
  });

  useEffect(() => {
    fetch("./rates.json")
      .then((r) => (r.ok ? r.json() : null))
      .then((json) => {
        const hasLenderData = json && Object.values(json.lenders || {}).some((h) => h.length > 0);
        if (!hasLenderData) {
          setState((s) => ({ ...s, loading: false, live: false }));
          return;
        }
        const boeBase = (json.boe?.bank_rate || []).map((p) => ({ date: p.date, rate: p.value }));
        setState({
          loading: false,
          live: true,
          lenders: json.lenders,
          boeBase: boeBase.length > 0 ? boeBase : SAMPLE_BOE_BASE,
          trackingStart: json.meta?.tracking_start || null,
        });
      })
      .catch(() => setState((s) => ({ ...s, loading: false, live: false })));
  }, []);

  return state;
}

function monthlyPayment(loanAmount, annualRatePct, termYears) {
  const r = annualRatePct / 100 / 12;
  const n = termYears * 12;
  if (r === 0) return loanAmount / n;
  return (loanAmount * r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
}

// Balance remaining after monthsElapsed of paying monthlyPayment(...) at this rate,
// as if that rate applied for the full termYears (matches how a lender actually
// computes what you pay during a fix - not recalculated until the fix ends).
function remainingBalance(loanAmount, annualRatePct, termYears, monthsElapsed) {
  const r = annualRatePct / 100 / 12;
  const pmt = monthlyPayment(loanAmount, annualRatePct, termYears);
  if (r === 0) return loanAmount - pmt * monthsElapsed;
  return loanAmount * Math.pow(1 + r, monthsElapsed) - pmt * ((Math.pow(1 + r, monthsElapsed) - 1) / r);
}

// Full-term cost assuming the fixed rate for fixMonths, then reverting to
// followOnRatePct (lender's SVR/reversion rate) for the rest of loanTermYears.
// fixMonths must be the ACTUAL fix duration (MSM's interestRates[0].months),
// not fixYears*12 - a "2yr fixed" product's fix commonly runs to a specific
// calendar end date (e.g. fixed until 31/10/2028) that isn't exactly 24
// months out, and using the rounded fixYears*12 instead produced total-cost
// figures consistently off by GBP 1,500-4,000 against MSM's own numbers
// (verified against 20 live products - see msm_lenders.py). This generalises
// correctly to whatever loan term the user selects, since only the follow-on
// stage's length depends on that; the fix length itself doesn't.
// Falls back to a single-stage calc if no follow-on rate/fix-months were captured.
function twoStageTotals(loanAmount, fixRatePct, fixMonths, followOnRatePct, loanTermYears, totalFees) {
  const totalMonths = loanTermYears * 12;
  const fees = totalFees || 0;

  if (!followOnRatePct || !fixMonths || fixMonths >= totalMonths) {
    const pmt = Math.round(monthlyPayment(loanAmount, fixRatePct, loanTermYears) * 100) / 100;
    const totalRepaid = pmt * totalMonths;
    return { totalInterest: totalRepaid - loanAmount, totalPayable: totalRepaid + fees };
  }

  const stage1Pmt = Math.round(monthlyPayment(loanAmount, fixRatePct, loanTermYears) * 100) / 100;
  const balanceAfterFix = remainingBalance(loanAmount, fixRatePct, loanTermYears, fixMonths);
  const remainingMonths = totalMonths - fixMonths;
  const stage2Pmt = Math.round(monthlyPayment(balanceAfterFix, followOnRatePct, remainingMonths / 12) * 100) / 100;

  const totalRepaid = stage1Pmt * fixMonths + stage2Pmt * remainingMonths;
  return { totalInterest: totalRepaid - loanAmount, totalPayable: totalRepaid + fees };
}

function fmtGBP(n) {
  return n.toLocaleString("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 });
}

export default function RateTracker() {
  const { loading, live, lenders, boeBase, trackingStart } = useRatesData();
  const [fixYears, setFixYears] = useState(2);
  const [loanTerm, setLoanTerm] = useState(30);
  const [hidden, setHidden] = useState({});
  const [boeHistoryMode, setBoeHistoryMode] = useState("since_start"); // "since_start" | "full"

  const lenderNames = useMemo(() => Object.keys(lenders || {}), [lenders]);
  const lenderNameToColor = useMemo(() => {
    const map = {};
    lenderNames.forEach((name, index) => {
      map[name] = lenderColor(name, index);
    });
    return map;
  }, [lenderNames]);

  const filterRow = (r) =>
    r.ltv_band === LTV_BAND &&
    r.product_type === "fixed" &&
    r.fix_years === fixYears;

  // "since_start" trims the BoE line to when tracking actually began, so it lines up
  // with the (currently much shorter) lender history. "full" shows everything BoE has.
  const visibleBoeBase = useMemo(() => {
    if (boeHistoryMode === "full" || !trackingStart) return boeBase;
    return boeBase.filter((p) => p.date >= trackingStart);
  }, [boeBase, boeHistoryMode, trackingStart]);

  const chartData = useMemo(() => {
    const dateMap = {};
    Object.entries(lenders).forEach(([lender, history]) => {
      history.forEach((day) => {
        const match = (day.rates || []).find(filterRow);
        if (!match) return;
        dateMap[day.date] = dateMap[day.date] || { date: day.date };
        dateMap[day.date][lender] = match.rate_pct;
      });
    });
    visibleBoeBase.forEach(({ date, rate }) => {
      dateMap[date] = dateMap[date] || { date };
      dateMap[date]["BoE Base Rate"] = rate;
    });
    return Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixYears, lenders, visibleBoeBase]);

  const latest = useMemo(() => {
    const rows = Object.entries(lenders).map(([lender, history]) => {
      if (!history || history.length === 0) return null;
      const lastDay = history[history.length - 1];
      const prevDay = history[history.length - 8];
      const lastMatch = (lastDay.rates || []).find(filterRow);
      const prevMatch = prevDay?.rates?.find(filterRow);
      if (!lastMatch) return null;
      const delta = prevMatch ? Math.round((lastMatch.rate_pct - prevMatch.rate_pct) * 100) / 100 : 0;
      // Total payable/interest depend on the repayment term (a live user input,
      // not a scrape-time constant) and on reverting to the lender's follow-on
      // rate once the fix ends - see twoStageTotals for why a naive "fixed rate
      // for the whole term" calc doesn't match MSM's own figures.
      const fixMonths = lastMatch.fix_months ?? fixYears * 12; // fall back to a clean estimate if missing
      const { totalInterest, totalPayable } = twoStageTotals(
        LOAN_AMOUNT, lastMatch.rate_pct, fixMonths, lastMatch.follow_on_rate_pct, loanTerm, lastMatch.total_fees
      );
      return {
        lender,
        rate: lastMatch.rate_pct,
        delta,
        productFee: lastMatch.product_fee,
        totalAmountPayable: totalPayable,
        totalInterest,
      };
    }).filter(Boolean);
    return rows.sort((a, b) => a.rate - b.rate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fixYears, lenders, loanTerm]);

  const best = latest[0];
  const payment = best ? monthlyPayment(LOAN_AMOUNT, best.rate, loanTerm) : null;

  const toggle = (lender) => setHidden(h => ({ ...h, [lender]: !h[lender] }));

  const labelStyle = { fontSize: 11, letterSpacing: "0.08em", color: "#6B7280", marginBottom: 6, display: "block" };
  const pillRow = { display: "flex", gap: 6, flexWrap: "wrap" };
  const pill = (active) => ({
    padding: "6px 12px",
    borderRadius: 4,
    fontSize: 12,
    cursor: "pointer",
    border: `1px solid ${active ? "#5EEAD4" : "#2A3040"}`,
    background: active ? "#123531" : "#151A26",
    color: active ? "#5EEAD4" : "#8B93A5",
  });

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0B0E14",
      color: "#E6E9EF",
      fontFamily: "'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace",
      padding: "32px 24px",
    }}>
      <div style={{ maxWidth: 1140, margin: "0 auto" }}>

        <header style={{ marginBottom: 24, borderBottom: "1px solid #1E2330", paddingBottom: 20 }}>
          <div style={{ fontSize: 12, letterSpacing: "0.14em", color: "#6B7280", marginBottom: 6 }}>
            UK MORTGAGE RATE TRACKER
          </div>
          <h1 style={{ fontSize: 26, fontWeight: 600, margin: 0, color: "#F5F7FA", letterSpacing: "-0.01em" }}>
            {fmtGBP(HOUSE_VALUE)} property · {LTV_BAND}% LTV · {fixYears}yr fixed
          </h1>
          <div style={{ fontSize: 13, marginTop: 4, display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{
              fontSize: 10, letterSpacing: "0.08em", padding: "2px 8px", borderRadius: 3,
              background: live ? "#0F2A1F" : "#2A2410", color: live ? "#4ADE80" : "#FBBF24",
              border: `1px solid ${live ? "#1F4A34" : "#4A3F14"}`,
            }}>
              {loading ? "LOADING…" : live ? "LIVE DATA" : "SAMPLE DATA"}
            </span>
            <span style={{ color: "#8B93A5" }}>
              {live ? "from your scraper" : "rates.json not found yet — showing generated sample data"}
            </span>
          </div>
        </header>

        {/* Controls */}
        <section style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          marginBottom: 20,
          background: "#10141F",
          border: "1px solid #1E2330",
          borderRadius: 6,
          padding: 20,
        }}>
          <div>
            <label style={labelStyle}>SCENARIO</label>
            <div style={{ fontSize: 13, color: "#C9CEDA", paddingTop: 8, lineHeight: 1.6 }}>
              {fmtGBP(HOUSE_VALUE)} property · {fmtGBP(DEPOSIT)} deposit ({LTV_BAND}% LTV) · First Time Buyer
              <br />
              <span style={{ color: "#6B7280", fontSize: 12 }}>
                Fixed scenario, not adjustable — matches what the scraper captures (see scraper/msm_automation)
              </span>
            </div>
          </div>
          <div>
            <label style={labelStyle}>LOAN AMOUNT</label>
            <div style={{ fontSize: 13, color: "#C9CEDA", paddingTop: 8 }}>
              {fmtGBP(LOAN_AMOUNT)}
            </div>
          </div>

          <div>
            <label style={labelStyle}>FIX LENGTH</label>
            <div style={pillRow}>
              {FIX_LENGTHS.map((y) => (
                <span key={y} style={pill(fixYears === y)} onClick={() => setFixYears(y)}>
                  {y}yr
                </span>
              ))}
            </div>
          </div>
          <div>
            <label style={labelStyle}>REPAYMENT TERM (years) — affects monthly payment only, not the rate</label>
            <div style={pillRow}>
              {LOAN_TERMS.map((t) => (
                <span key={t} style={pill(loanTerm === t)} onClick={() => setLoanTerm(t)}>
                  {t}yr
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* Stat cards */}
        <section style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 20,
          marginBottom: 24,
        }}>
          <div style={{ background: "#10141F", border: "1px solid #1E2330", borderRadius: 6, padding: "18px 20px" }}>
            <div style={labelStyle}>BEST RATE TODAY</div>
            {best ? (
              <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                <span style={{ fontSize: 30, fontWeight: 700, color: lenderNameToColor[best.lender] || "#F5F7FA" }}>
                  {best.rate.toFixed(2)}%
                </span>
                <span style={{ fontSize: 14, color: "#C9CEDA" }}>{best.lender}</span>
              </div>
            ) : <span style={{ color: "#6B7280" }}>No data for this combination</span>}
          </div>
          <div style={{ background: "#10141F", border: "1px solid #1E2330", borderRadius: 6, padding: "18px 20px" }}>
            <div style={labelStyle}>EST. MONTHLY PAYMENT ({loanTerm}yr repayment)</div>
            <div style={{ fontSize: 30, fontWeight: 700, color: "#F5F7FA" }}>
              {payment ? fmtGBP(Math.round(payment)) : "—"}
            </div>
          </div>
          <div style={{ background: "#10141F", border: "1px solid #1E2330", borderRadius: 6, padding: "18px 20px" }}>
            <div style={labelStyle}>BOE BASE RATE</div>
            <div style={{ fontSize: 30, fontWeight: 700, color: "#8B93A5" }}>
              {boeBase.length > 0 ? `${boeBase[boeBase.length - 1].rate.toFixed(2)}%` : "—"}
            </div>
          </div>
        </section>

        {/* Chart */}
        <section style={{
          background: "#10141F",
          border: "1px solid #1E2330",
          borderRadius: 6,
          padding: "20px 16px 8px",
          marginBottom: 24,
        }}>
          <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 8, padding: "0 8px 12px" }}>
            <span style={{ fontSize: 11, letterSpacing: "0.08em", color: "#6B7280" }}>BOE HISTORY</span>
            <div style={pillRow}>
              <span style={pill(boeHistoryMode === "since_start")} onClick={() => setBoeHistoryMode("since_start")}>
                Since I started tracking
              </span>
              <span style={pill(boeHistoryMode === "full")} onClick={() => setBoeHistoryMode("full")}>
                Full history (2022+)
              </span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={360}>
            <LineChart data={chartData} margin={{ top: 8, right: 16, left: -8, bottom: 8 }}>
              <CartesianGrid stroke="#1E2330" strokeDasharray="3 3" />
              <XAxis dataKey="date" stroke="#4B5563" tick={{ fill: "#6B7280", fontSize: 11 }} tickFormatter={(d) => d.slice(5)} />
              <YAxis
                stroke="#4B5563"
                tick={{ fill: "#6B7280", fontSize: 11 }}
                domain={["dataMin - 0.2", "dataMax + 0.2"]}
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip
                contentStyle={{ background: "#151A26", border: "1px solid #2A3040", borderRadius: 4, fontSize: 12 }}
                labelStyle={{ color: "#8B93A5" }}
              />
              <Legend onClick={(e) => toggle(e.dataKey)} wrapperStyle={{ fontSize: 12, cursor: "pointer", paddingTop: 12 }} />
              <Line
                type="monotone"
                dataKey="BoE Base Rate"
                stroke="#4B5563"
                strokeDasharray="5 4"
                strokeWidth={1.5}
                dot={{ r: 2, fill: "#4B5563", strokeWidth: 0 }}
                hide={!!hidden["BoE Base Rate"]}
              />
              {lenderNames.map((lender) => (
                <Line
                  key={lender}
                  type="monotone"
                  dataKey={lender}
                  stroke={lenderNameToColor[lender] || "#F5F7FA"}
                  strokeWidth={best && lender === best.lender ? 2.5 : 1.5}
                  dot={{ r: 3, fill: lenderNameToColor[lender] || "#F5F7FA", strokeWidth: 0 }}
                  activeDot={{ r: 5 }}
                  hide={!!hidden[lender]}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </section>

        {/* Table */}
        <section style={{ background: "#10141F", border: "1px solid #1E2330", borderRadius: 6, overflow: "auto" }}>
          <div style={{
            display: "grid", gridTemplateColumns: "1fr 90px 90px 100px 130px 130px", minWidth: 720,
            padding: "10px 20px", fontSize: 11, letterSpacing: "0.1em", color: "#6B7280",
            borderBottom: "1px solid #1E2330",
          }}>
            <span>LENDER</span>
            <span style={{ textAlign: "right" }}>RATE</span>
            <span style={{ textAlign: "right" }}>7D TREND</span>
            <span style={{ textAlign: "right" }}>FEE</span>
            <span style={{ textAlign: "right" }}>TOTAL PAYABLE</span>
            <span style={{ textAlign: "right" }}>TOTAL INTEREST</span>
          </div>
          {latest.map(({ lender, rate, delta, productFee, totalAmountPayable, totalInterest }, i) => (
            <div key={lender} style={{
              display: "grid", gridTemplateColumns: "1fr 90px 90px 100px 130px 130px", minWidth: 720,
              padding: "12px 20px", fontSize: 14,
              borderBottom: i < latest.length - 1 ? "1px solid #161A24" : "none",
              background: i === 0 ? "#131826" : "transparent",
            }}>
              <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: lenderNameToColor[lender] || "#F5F7FA", display: "inline-block" }} />
                {lender}
              </span>
              <span style={{ textAlign: "right", color: "#F5F7FA", fontWeight: 600 }}>{rate.toFixed(2)}%</span>
              <span style={{ textAlign: "right", color: delta <= 0 ? "#4ADE80" : "#F87171" }}>
                {delta <= 0 ? "▼" : "▲"} {Math.abs(delta).toFixed(2)}
              </span>
              <span style={{ textAlign: "right", color: "#C9CEDA" }}>
                {productFee != null ? fmtGBP(productFee) : "—"}
              </span>
              <span style={{ textAlign: "right", color: "#C9CEDA" }}>
                {totalAmountPayable != null ? fmtGBP(totalAmountPayable) : "—"}
              </span>
              <span style={{ textAlign: "right", color: "#C9CEDA" }}>
                {totalInterest != null ? fmtGBP(totalInterest) : "—"}
              </span>
            </div>
          ))}
          {latest.length === 0 && (
            <div style={{ padding: 20, fontSize: 13, color: "#6B7280" }}>
              No lenders have data for this LTV / product / term combination yet.
            </div>
          )}
        </section>

        <footer style={{ marginTop: 20, fontSize: 11, color: "#4B5563" }}>
          Not financial advice. Rates shown are indicative only — always confirm with the lender.
        </footer>
      </div>
    </div>
  );
}
