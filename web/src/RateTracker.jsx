import React, { useMemo, useState, useEffect } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";

// ---- Config ----
const LTV_BANDS = [60, 75, 80, 85, 90, 95];
const FIX_LENGTHS = [2, 3, 5];
const LOAN_TERMS = [25, 30];
const LENDER_COLORS = {
  Nationwide: "#5EEAD4",
  Barclays: "#60A5FA",
  Santander: "#F472B6",
  Halifax: "#FBBF24",
  HSBC: "#A78BFA",
  NatWest: "#FB923C",
  Lloyds: "#4ADE80",
};

// ---- Sample data generator: shape-matches data/rates.json's lender matrix.
// Swap this for a real fetch of data/rates.json once the scraper is live. ----
function genMatrixHistory(baseByBand, days, seed) {
  const today = new Date();
  const history = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const date = d.toISOString().slice(0, 10);
    const rates = [];
    LTV_BANDS.forEach((band, bIdx) => {
      FIX_LENGTHS.forEach((fix, fIdx) => {
        const base = baseByBand[band] + fix * 0.06; // longer fixes ~slightly costlier here
        const wiggle = Math.sin((i + seed + bIdx * 3 + fIdx) / 6) * 0.02;
        const drift = -0.003 * (days - i);
        const rate = Math.round((base + wiggle + drift) * 100) / 100;
        rates.push({ ltv_band: band, product_type: "fixed", fix_years: fix, rate_pct: rate });
      });
      // one tracker row per band
      const trackerBase = baseByBand[band] + 0.25;
      rates.push({
        ltv_band: band, product_type: "tracker", fix_years: null,
        rate_pct: Math.round((trackerBase + Math.sin((i + seed) / 6) * 0.02) * 100) / 100,
      });
    });
    history.push({ date, status: "ok", rates });
  }
  return history;
}

const BASE_BY_BAND = { 60: 4.05, 75: 4.25, 80: 4.45, 85: 4.60, 90: 4.85, 95: 5.15 };

const SAMPLE_LENDERS = {
  Nationwide: genMatrixHistory(BASE_BY_BAND, 60, 1),
  Barclays: genMatrixHistory(BASE_BY_BAND, 60, 2),
  Santander: genMatrixHistory(BASE_BY_BAND, 60, 3),
  Halifax: genMatrixHistory(BASE_BY_BAND, 60, 4),
  HSBC: genMatrixHistory(BASE_BY_BAND, 60, 5),
  NatWest: genMatrixHistory(BASE_BY_BAND, 60, 6),
  Lloyds: genMatrixHistory(BASE_BY_BAND, 60, 7),
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
  const [state, setState] = useState({ loading: true, live: false, lenders: SAMPLE_LENDERS, boeBase: SAMPLE_BOE_BASE });

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
        });
      })
      .catch(() => setState((s) => ({ ...s, loading: false, live: false })));
  }, []);

  return state;
}

function nearestBand(ltv) {
  return LTV_BANDS.reduce((best, b) => (Math.abs(b - ltv) < Math.abs(best - ltv) ? b : best));
}

function monthlyPayment(loanAmount, annualRatePct, termYears) {
  const r = annualRatePct / 100 / 12;
  const n = termYears * 12;
  if (r === 0) return loanAmount / n;
  return (loanAmount * r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);
}

function fmtGBP(n) {
  return n.toLocaleString("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 });
}

export default function RateTracker() {
  const { loading, live, lenders, boeBase } = useRatesData();
  const [houseValue, setHouseValue] = useState(500000);
  const [ltvInput, setLtvInput] = useState(90);
  const [productType, setProductType] = useState("fixed");
  const [fixYears, setFixYears] = useState(2);
  const [loanTerm, setLoanTerm] = useState(30);
  const [hidden, setHidden] = useState({});

  const band = nearestBand(ltvInput);
  const deposit = Math.round(houseValue * (1 - ltvInput / 100));
  const loanAmount = houseValue - deposit;

  const filterRow = (r) =>
    r.ltv_band === band &&
    r.product_type === productType &&
    (productType !== "fixed" || r.fix_years === fixYears);

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
    boeBase.forEach(({ date, rate }) => {
      dateMap[date] = dateMap[date] || { date };
      dateMap[date]["BoE Base Rate"] = rate;
    });
    return Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [band, productType, fixYears, lenders, boeBase]);

  const latest = useMemo(() => {
    const rows = Object.entries(lenders).map(([lender, history]) => {
      if (!history || history.length === 0) return null;
      const lastDay = history[history.length - 1];
      const prevDay = history[history.length - 8];
      const lastMatch = (lastDay.rates || []).find(filterRow);
      const prevMatch = prevDay?.rates?.find(filterRow);
      if (!lastMatch) return null;
      const delta = prevMatch ? Math.round((lastMatch.rate_pct - prevMatch.rate_pct) * 100) / 100 : 0;
      return { lender, rate: lastMatch.rate_pct, delta };
    }).filter(Boolean);
    return rows.sort((a, b) => a.rate - b.rate);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [band, productType, fixYears, lenders]);

  const best = latest[0];
  const payment = best ? monthlyPayment(loanAmount, best.rate, loanTerm) : null;

  const toggle = (lender) => setHidden(h => ({ ...h, [lender]: !h[lender] }));

  const inputStyle = {
    background: "#151A26",
    border: "1px solid #2A3040",
    borderRadius: 4,
    color: "#F5F7FA",
    padding: "8px 10px",
    fontSize: 13,
    fontFamily: "inherit",
    width: "100%",
  };
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
            {fmtGBP(houseValue)} property · {ltvInput}% LTV · {fixYears}yr {productType}
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
            <label style={labelStyle}>HOUSE VALUE (£)</label>
            <input
              type="number"
              style={inputStyle}
              value={houseValue}
              min={50000}
              step={5000}
              onChange={(e) => setHouseValue(Number(e.target.value) || 0)}
            />
          </div>
          <div>
            <label style={labelStyle}>LTV RATIO (%) — snaps to nearest priced band ({band}%)</label>
            <input
              type="number"
              style={inputStyle}
              value={ltvInput}
              min={5}
              max={95}
              step={1}
              onChange={(e) => setLtvInput(Number(e.target.value) || 0)}
            />
          </div>

          <div>
            <label style={labelStyle}>PRODUCT TYPE</label>
            <div style={pillRow}>
              {["fixed", "tracker", "variable"].map((p) => (
                <span key={p} style={pill(productType === p)} onClick={() => setProductType(p)}>
                  {p}
                </span>
              ))}
            </div>
          </div>
          <div>
            <label style={labelStyle}>FIX LENGTH {productType !== "fixed" && "(n/a for this product)"}</label>
            <div style={pillRow}>
              {FIX_LENGTHS.map((y) => (
                <span
                  key={y}
                  style={{ ...pill(fixYears === y && productType === "fixed"), opacity: productType === "fixed" ? 1 : 0.35 }}
                  onClick={() => productType === "fixed" && setFixYears(y)}
                >
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
          <div>
            <label style={labelStyle}>DEPOSIT / LOAN AMOUNT</label>
            <div style={{ fontSize: 13, color: "#C9CEDA", paddingTop: 8 }}>
              {fmtGBP(deposit)} deposit · {fmtGBP(loanAmount)} loan
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
                <span style={{ fontSize: 30, fontWeight: 700, color: LENDER_COLORS[best.lender] }}>
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
            <div style={{ fontSize: 30, fontWeight: 700, color: "#8B93A5" }}>3.75%</div>
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
              <Line type="monotone" dataKey="BoE Base Rate" stroke="#4B5563" strokeDasharray="5 4" strokeWidth={1.5} dot={false} hide={!!hidden["BoE Base Rate"]} />
              {Object.keys(LENDER_COLORS).map((lender) => (
                <Line
                  key={lender}
                  type="monotone"
                  dataKey={lender}
                  stroke={LENDER_COLORS[lender]}
                  strokeWidth={best && lender === best.lender ? 2.5 : 1.5}
                  dot={false}
                  hide={!!hidden[lender]}
                  connectNulls
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </section>

        {/* Table */}
        <section style={{ background: "#10141F", border: "1px solid #1E2330", borderRadius: 6, overflow: "hidden" }}>
          <div style={{
            display: "grid", gridTemplateColumns: "1fr 100px 100px",
            padding: "10px 20px", fontSize: 11, letterSpacing: "0.1em", color: "#6B7280",
            borderBottom: "1px solid #1E2330",
          }}>
            <span>LENDER</span>
            <span style={{ textAlign: "right" }}>RATE</span>
            <span style={{ textAlign: "right" }}>7D TREND</span>
          </div>
          {latest.map(({ lender, rate, delta }, i) => (
            <div key={lender} style={{
              display: "grid", gridTemplateColumns: "1fr 100px 100px",
              padding: "12px 20px", fontSize: 14,
              borderBottom: i < latest.length - 1 ? "1px solid #161A24" : "none",
              background: i === 0 ? "#131826" : "transparent",
            }}>
              <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <span style={{ width: 8, height: 8, borderRadius: "50%", background: LENDER_COLORS[lender], display: "inline-block" }} />
                {lender}
              </span>
              <span style={{ textAlign: "right", color: "#F5F7FA", fontWeight: 600 }}>{rate.toFixed(2)}%</span>
              <span style={{ textAlign: "right", color: delta <= 0 ? "#4ADE80" : "#F87171" }}>
                {delta <= 0 ? "▼" : "▲"} {Math.abs(delta).toFixed(2)}
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
