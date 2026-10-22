"""
Real Exchange Rate (RER) Calculator
-----------------------------------
Streamlit app that downloads monthly CPI and exchange-rate data from the
IMF SDMX 3.0 API and computes the bilateral real exchange rate:

    S(t)   = units of Country 2 currency per 1 unit of Country 1 currency
    RER(t) = S(t) * P1(t) / P2(t)
    RER*   = mean of RER(t) over valid months in the selected sample
    Real Index(t) = 100 * RER(t) / RER*

Run with:  streamlit run app.py
"""

from __future__ import annotations

import io

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
IMF_BASE = "https://api.imf.org/external/sdmx/3.0"
DATA_URL = IMF_BASE + "/data/dataflow/IMF.STA/{flow}/+/{key}"
CODELIST_URL = IMF_BASE + "/structure/codelist/IMF/CL_COUNTRY/+"
CSV_ACCEPT = "application/vnd.sdmx.data+csv;version=2.0.0"
HEADERS = {"User-Agent": "rer-calculator/1.0 (educational app)"}
START_PERIOD = "1976-01"
TIMEOUT = 60

EURO_AREA = "G163"
EURO_AREA_NAME = "Euro area"

# CPI key from the assignment. The Euro area publishes a harmonised index
# (HICP) instead of a "CPI" index type, so it is tried as a fallback.
CPI_KEYS = ["{iso}.CPI._T.IX.M", "{iso}.HICP._T.IX.M"]
ER_KEY = "{iso}.XDC_USD.PA_RT.M"  # local currency units per USD, period average

# Used only if the IMF country list cannot be downloaded.
FALLBACK_COUNTRIES = {
    "USA": "United States", "G163": EURO_AREA_NAME, "MEX": "Mexico",
    "CAN": "Canada", "GBR": "United Kingdom", "JPN": "Japan",
    "CHN": "China", "BRA": "Brazil", "ARG": "Argentina", "CHL": "Chile",
    "COL": "Colombia", "PER": "Peru", "IND": "India", "KOR": "Korea",
    "AUS": "Australia", "CHE": "Switzerland", "ZAF": "South Africa",
    "TUR": "Türkiye", "DEU": "Germany", "FRA": "France",
}


# ---------------------------------------------------------------------------
# IMF API helpers
# ---------------------------------------------------------------------------
def _get(url: str, params: dict | None = None, accept: str = CSV_ACCEPT) -> requests.Response:
    resp = requests.get(url, params=params, headers={**HEADERS, "Accept": accept}, timeout=TIMEOUT)
    resp.raise_for_status()
    return resp


def _parse_period(p: pd.Series) -> pd.Series:
    """Convert IMF periods like '1976-M01' to month-start timestamps."""
    return pd.to_datetime(p.astype(str).str.replace("-M", "-", regex=False), format="%Y-%m", errors="coerce")


def fetch_csv(flow: str, key: str, params: dict | None = None) -> pd.DataFrame:
    """Download an SDMX-CSV response and return only rows with data."""
    resp = _get(DATA_URL.format(flow=flow, key=key), params=params)
    df = pd.read_csv(io.StringIO(resp.text), dtype=str)
    if df.empty or "OBS_VALUE" not in df.columns:
        return pd.DataFrame(columns=["COUNTRY", "TIME_PERIOD", "OBS_VALUE"])
    df = df.dropna(subset=["COUNTRY", "TIME_PERIOD", "OBS_VALUE"])
    return df


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def fetch_series(flow: str, key: str) -> pd.Series:
    """Monthly series (indexed by month start) from START_PERIOD onward."""
    df = fetch_csv(flow, key, params={"c[TIME_PERIOD]": f"ge:{START_PERIOD}"})
    if df.empty:
        return pd.Series(dtype=float)
    dates = _parse_period(df["TIME_PERIOD"])
    values = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    s = pd.Series(values.values, index=dates).dropna()
    s = s[~s.index.isna()]
    s = s[s.index >= pd.Timestamp(START_PERIOD)]
    s = s.groupby(level=0).last().sort_index()
    return s


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def get_cpi(iso: str) -> tuple[pd.Series, str]:
    """Return (CPI series, key used). Tries CPI first, then HICP."""
    for template in CPI_KEYS:
        key = template.format(iso=iso)
        s = fetch_series("CPI", key)
        if not s.empty:
            return s, key
    return pd.Series(dtype=float), CPI_KEYS[0].format(iso=iso)


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def get_er(iso: str) -> tuple[pd.Series, str]:
    """Return (LCU per USD series, key used)."""
    key = ER_KEY.format(iso=iso)
    s = fetch_series("ER", key)
    if s.empty and iso == "USA":
        # By definition 1 USD = 1 USD; used only if the IMF omits the series.
        idx = pd.date_range(START_PERIOD, pd.Timestamp.today().normalize(), freq="MS")
        s = pd.Series(1.0, index=idx)
    return s, key


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def get_country_list() -> tuple[dict[str, str], bool]:
    """
    Countries (ISO3 -> name) that have both a monthly CPI and a monthly
    USD exchange rate in the IMF database, plus the Euro area.
    Returns (dict, ok_flag); falls back to a short static list on failure.
    """
    try:
        resp = _get(CODELIST_URL, accept="application/json")
        codes = resp.json()["data"]["codelists"][0]["codes"]
        names = {c["id"]: c.get("name", c["id"]) for c in codes}

        last = {"lastNObservations": 1}
        cpi = set(fetch_csv("CPI", "*.CPI._T.IX.M", last)["COUNTRY"])
        er = set(fetch_csv("ER", "*.XDC_USD.PA_RT.M", last)["COUNTRY"])
        available = (cpi & er) | {EURO_AREA, "USA"}

        countries = {iso: names.get(iso, iso) for iso in available}
        countries[EURO_AREA] = EURO_AREA_NAME
        # Keep real countries only (IMF aggregate codes start with "G" + digits),
        # except the Euro area.
        countries = {
            k: v for k, v in countries.items()
            if k == EURO_AREA or not (k.startswith("G") and k[1:].isdigit())
        }
        if len(countries) < 10:
            raise ValueError("country list unexpectedly short")
        return dict(sorted(countries.items(), key=lambda kv: kv[1])), True
    except Exception:  # noqa: BLE001 - any network/parse failure -> fallback
        return dict(sorted(FALLBACK_COUNTRIES.items(), key=lambda kv: kv[1])), False


# ---------------------------------------------------------------------------
# Economics
# ---------------------------------------------------------------------------
def build_dataset(iso1: str, iso2: str) -> tuple[pd.DataFrame, dict]:
    """Merge IMF series and compute S(t) and RER(t) for every month."""
    p1, k_p1 = get_cpi(iso1)
    p2, k_p2 = get_cpi(iso2)
    e1, k_e1 = get_er(iso1)
    e2, k_e2 = get_er(iso2)

    df = pd.concat(
        {"E1_LCU_per_USD": e1, "E2_LCU_per_USD": e2, "P1_CPI": p1, "P2_CPI": p2},
        axis=1,
    ).sort_index()
    if df.empty:
        return df, {}

    # Full monthly calendar so gaps show up explicitly.
    full_idx = pd.date_range(df.index.min(), df.index.max(), freq="MS")
    df = df.reindex(full_idx)
    df.index.name = "Month"

    # IMF rates are LCU per USD. Units of C2 per 1 unit of C1:
    #   S = (C2 per USD) / (C1 per USD)
    # (S is kept even in months where a CPI is missing.)
    df["S_C2_per_C1"] = df["E2_LCU_per_USD"] / df["E1_LCU_per_USD"]

    # A month is valid only if all four inputs are present and positive.
    cols = ["E1_LCU_per_USD", "E2_LCU_per_USD", "P1_CPI", "P2_CPI"]
    df["Valid"] = (df[cols] > 0).all(axis=1)  # NaN > 0 is False
    df["RER"] = (df["S_C2_per_C1"] * df["P1_CPI"] / df["P2_CPI"]).where(df["Valid"])

    keys = {"P1": k_p1, "P2": k_p2, "E1": k_e1, "E2": k_e2}
    return df, keys


def compute_sample(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, float]:
    """Restrict to [start, end], compute RER* and the Real Index."""
    sample = df.loc[start:end].copy()
    rer_star = sample.loc[sample["Valid"], "RER"].mean()
    sample["RER_star"] = rer_star
    sample["Real_Index"] = 100 * sample["RER"] / rer_star
    return sample, rer_star


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------
REAL_COLOR = "#2a6fdb"
NOMINAL_COLOR = "#e07b24"


def make_chart(sample: pd.DataFrame, view: str, name1: str, name2: str,
               cur1: str, cur2: str) -> go.Figure:
    s_label = f"S(t): {cur2} per 1 {cur1}"
    real = go.Scatter(
        x=sample.index, y=sample["Real_Index"], name="Real Index (RER*=100)",
        mode="lines", line=dict(color=REAL_COLOR, width=2), connectgaps=False,
        hovertemplate="%{x|%Y-%m}<br>Real Index: %{y:.2f}<extra></extra>",
    )
    nominal = go.Scatter(
        x=sample.index, y=sample["S_C2_per_C1"], name=s_label,
        mode="lines", line=dict(color=NOMINAL_COLOR, width=2), connectgaps=False,
        hovertemplate="%{x|%Y-%m}<br>S: %{y:,.4f}<extra></extra>",
    )

    if view == "Both":
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(real, secondary_y=False)
        fig.add_trace(nominal, secondary_y=True)
        fig.update_yaxes(title_text="Real Index (RER* = 100)", color=REAL_COLOR, secondary_y=False)
        fig.update_yaxes(title_text=s_label, color=NOMINAL_COLOR, secondary_y=True,
                         showgrid=False)
        fig.add_hline(y=100, line_dash="dot", line_color="gray", secondary_y=False)
    elif view == "Real":
        fig = go.Figure(real)
        fig.update_yaxes(title_text="Real Index (RER* = 100)")
        fig.add_hline(y=100, line_dash="dot", line_color="gray")
    else:
        fig = go.Figure(nominal)
        fig.update_yaxes(title_text=s_label)

    fig.update_layout(
        title=f"{name1} vs {name2}",
        hovermode="x unified",
        height=520,
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_xaxes(title_text="Month", rangeslider_visible=True)
    return fig


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
def main() -> None:
    st.set_page_config(page_title="Real Exchange Rate Calculator", layout="wide")
    st.title("Real Exchange Rate Calculator")
    st.caption(
        "Data: IMF SDMX 3.0 API (monthly CPI and exchange rates, from January 1976 where available). "
        "S(t) = units of Country 2 currency per 1 unit of Country 1 currency; "
        "RER(t) = S(t) × P1(t) / P2(t)."
    )

    with st.spinner("Loading IMF country list..."):
        countries, ok = get_country_list()
    if not ok:
        st.warning("Could not load the full IMF country list; showing a reduced list.")

    codes = list(countries.keys())
    label = lambda iso: f"{countries[iso]} ({iso})"  # noqa: E731

    with st.sidebar:
        st.header("Settings")
        iso1 = st.selectbox("Country 1", codes, index=codes.index("USA") if "USA" in codes else 0,
                            format_func=label)
        default2 = "MEX" if "MEX" in codes else codes[1]
        iso2 = st.selectbox("Country 2", codes, index=codes.index(default2), format_func=label)

    if iso1 == iso2:
        st.info("Choose two different countries.")
        return

    name1, name2 = countries[iso1], countries[iso2]

    try:
        with st.spinner(f"Downloading IMF data for {name1} and {name2}..."):
            df, keys = build_dataset(iso1, iso2)
    except requests.RequestException as exc:
        st.error(f"IMF API request failed: {exc}. Please try again in a moment.")
        return

    # Coverage report
    missing = [lbl for lbl, col in [
        (f"CPI for {name1}", "P1_CPI"), (f"CPI for {name2}", "P2_CPI"),
        (f"exchange rate for {name1}", "E1_LCU_per_USD"),
        (f"exchange rate for {name2}", "E2_LCU_per_USD"),
    ] if df.empty or df[col].notna().sum() == 0]
    if missing:
        st.error("The IMF has no monthly data for: " + ", ".join(missing) + ".")
        return

    valid_months = df.index[df["Valid"]]
    if len(valid_months) == 0:
        st.error("No month has all four series (two CPIs, two exchange rates). "
                 "The series do not overlap in time.")
        return

    first_valid, last_valid = valid_months.min(), valid_months.max()
    month_opts = list(pd.date_range(first_valid, last_valid, freq="MS"))
    fmt = lambda d: d.strftime("%Y-%m")  # noqa: E731

    with st.sidebar:
        st.subheader("Sample period")
        start = st.selectbox("Start month", month_opts, index=0, format_func=fmt,
                             key=f"start_{iso1}_{iso2}")
        end = st.selectbox("End month", month_opts, index=len(month_opts) - 1, format_func=fmt,
                           key=f"end_{iso1}_{iso2}")
        view = st.radio("Chart", ["Real", "Nominal", "Both"], index=2, horizontal=True)
        st.caption(f"Months with all data: {fmt(first_valid)} to {fmt(last_valid)}")

    if start > end:
        st.error("Start month must be on or before the end month.")
        return

    sample, rer_star = compute_sample(df, start, end)
    n_valid = int(sample["Valid"].sum())
    n_total = len(sample)
    if n_valid == 0:
        st.error("No valid months in the selected period.")
        return

    cur1, cur2 = f"{iso1} currency", f"{iso2} currency"
    if iso1 == EURO_AREA:
        cur1 = "EUR"
    if iso2 == EURO_AREA:
        cur2 = "EUR"

    # Summary metrics
    last_row = sample[sample["Valid"]].iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("RER* (sample mean of RER)", f"{rer_star:,.4f}")
    c2.metric(f"Latest Real Index ({fmt(last_row.name)})", f"{last_row['Real_Index']:.2f}")
    c3.metric(f"Latest S(t) ({fmt(last_row.name)})", f"{last_row['S_C2_per_C1']:,.4f}")
    c4.metric("Valid months in sample", f"{n_valid} / {n_total}")

    if n_valid < n_total:
        st.warning(f"{n_total - n_valid} month(s) in the sample are missing at least one series "
                   "and are excluded from RER* (shown as gaps in the chart).")

    st.plotly_chart(make_chart(sample, view, name1, name2, cur1, cur2), width="stretch")
    st.caption("Real Index above 100: Country 1's currency is stronger in real terms than its sample "
               "average (Country 2 relatively cheaper). Below 100: weaker.")

    # Table + CSV
    out = sample.reset_index()
    out.insert(0, "Country1", iso1)
    out.insert(1, "Country2", iso2)
    out["Month"] = out["Month"].dt.strftime("%Y-%m")
    out = out[["Month", "Country1", "Country2", "E1_LCU_per_USD", "E2_LCU_per_USD",
               "S_C2_per_C1", "P1_CPI", "P2_CPI", "RER", "RER_star", "Real_Index", "Valid"]]

    st.download_button(
        "Download CSV (sample period)",
        data=out.to_csv(index=False).encode("utf-8"),
        file_name=f"rer_{iso1}_{iso2}_{fmt(start)}_{fmt(end)}.csv",
        mime="text/csv",
    )

    with st.expander("Data table"):
        st.dataframe(out, width="stretch", hide_index=True)

    with st.expander("Methodology and IMF series used"):
        st.markdown(f"""
- **E1(t), E2(t)**: IMF exchange rates, local currency units per USD (period average).
  Keys: `ER/{keys['E1']}`, `ER/{keys['E2']}`.
- **S(t) = E2(t) / E1(t)**: units of {cur2} per 1 {cur1} (nominal, not normalised).
- **P1(t), P2(t)**: monthly consumer price indices. Keys: `CPI/{keys['P1']}`, `CPI/{keys['P2']}`.
- **RER(t) = S(t) × P1(t) / P2(t)**.
- **RER\\*** = average of RER(t) over the {n_valid} valid months between {fmt(start)} and {fmt(end)}.
- **Real Index(t) = 100 × RER(t) / RER\\***. A month is *valid* only if all four inputs are present and positive.
""")


if __name__ == "__main__":
    main()
