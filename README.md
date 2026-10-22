# Real Exchange Rate Calculator

An interactive Streamlit app that computes the bilateral **real exchange rate (RER)** between any two
IMF countries (or the Euro area), using monthly CPI and exchange-rate data downloaded live from the
IMF SDMX 3.0 API.

## Economics

| Symbol | Definition |
|---|---|
| E1(t), E2(t) | IMF exchange rates: local currency units per USD (monthly period average) |
| **S(t)** | Units of Country 2 currency per 1 unit of Country 1 currency = E2(t) / E1(t) |
| P1(t), P2(t) | Monthly consumer price indices of Country 1 and Country 2 |
| **RER(t)** | S(t) × P1(t) / P2(t) |
| **RER\*** | Average of RER(t) over the valid months in the selected start–end period |
| **Real Index(t)** | 100 × RER(t) / RER\* |

- A month is **valid** only if all four inputs (E1, E2, P1, P2) are available and positive.
- RER\* is recalculated automatically whenever the start or end month changes.
- The nominal rate S(t) is plotted in **actual currency units** (not normalised).
- A Real Index above 100 means Country 1's currency is stronger in real terms than its sample average.

## Features

- Pick Country 1 and Country 2 from all IMF countries that publish both a monthly CPI and a monthly
  USD exchange rate, plus the Euro area.
- Data from January 1976 where available.
- Choose start and end months; the default is the full period with complete data.
- Chart view: **Real**, **Nominal**, or **Both** (with a separate y-axis for each line), with zoom, hover
  and a range slider.
- **CSV download** of every month in the selected period: both exchange rates, S(t), both CPIs, RER(t),
  RER\*, the Real Index, and a validity flag.

## Installation (Python 3.12)

```bash
python -m venv .venv
```

Activate the environment (Windows: `.venv\Scripts\activate`, macOS/Linux: `source .venv/bin/activate`), then:

```bash
pip install -r requirements.txt
```

```bash
streamlit run app.py
```

The app opens in your browser at http://localhost:8501.

## Data source

IMF SDMX 3.0 API: `https://api.imf.org/external/sdmx/3.0`

| Series | Dataflow | Key |
|---|---|---|
| CPI | `IMF.STA/CPI` | `{ISO3}.CPI._T.IX.M` |
| Exchange rate | `IMF.STA/ER` | `{ISO3}.XDC_USD.PA_RT.M` |

Example request:

```
https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/CPI/+/USA.CPI._T.IX.M?c[TIME_PERIOD]=ge:1976-01
```

The app asks for SDMX-CSV output (`Accept: application/vnd.sdmx.data+csv;version=2.0.0`). Downloads
are cached for 24 hours.

## Data notes and limitations

- **Euro area (code `G163`)**: the IMF publishes no `CPI` index type for G163. It publishes the
  Harmonised Index of Consumer Prices instead, so the app falls back to the key `G163.HICP._T.IX.M`.
  That index starts in December 1999, and the euro exchange rate starts in January 1999, so Euro-area
  pairs begin in December 1999.
- **United States**: the IMF reports the USD rate as 1. If that series were ever missing, the app uses 1.
- **Gaps**: some countries have missing months or shorter histories. Months with any missing input are
  excluded from RER\*, shown as gaps in the chart, and flagged `Valid = False` in the CSV.
- **CPI base years** differ across countries. This does not matter, because the Real Index is
  normalised by RER\*.
- **Country list**: built from the IMF `CL_COUNTRY` codelist, filtered to countries with both monthly
  series. If the IMF API is unreachable, a short built-in list is shown instead.
- **Redenominations**: for countries that removed zeros from their currency, check the IMF series for
  breaks. S(t) is shown exactly as the IMF reports it.
