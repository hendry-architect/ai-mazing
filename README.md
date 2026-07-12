# 🔬 AI-mazing Data Analyst

A clean, reusable data-analysis app built around a sharpened analyst engine.
Upload any CSV, pick a built-in sample dataset, or pull **live Amplitude event data**,
type a plain-language question, and get a full
**LOAD → CLEAN → PROFILE → ANALYZE → VISUALIZE → REPORT** playbook in seconds —
complete with charts and a downloadable PDF report.

> **No Amplitude account required.** The app works fully offline with CSV uploads
> and four built-in sample datasets. Amplitude integration is optional.

---

## Project structure

```
ai-mazing/
├── analyst.py           # 🧠 Core engine  — run_analysis() + export_report_pdf()
├── amplitude_source.py  # 📡 Amplitude connector — fetch_amplitude_events()
├── app.py               # 🖥  Streamlit front-end
├── requirements.txt     # 📦 Fully-pinned Python dependencies
├── .env.example         # 🔑 Credential template (copy → .env, never commit)
├── .gitignore           # 🚫 Excludes secrets, outputs, caches
├── .streamlit/
│   └── config.toml      # ⚙️  Theme + server settings (no secrets here)
├── README.md            # 📖 This file
└── outputs/             # 📊 Auto-created — charts and PDFs written here
```

---

## Local Quickstart

### Prerequisites
- Python 3.9 or newer
- Git (optional, for cloning)

### Steps

```bash
# 1. Clone (or unzip) the repo
git clone https://github.com/YOUR_USERNAME/ai-mazing.git
cd ai-mazing

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. (Optional) Configure Amplitude credentials
cp .env.example .env
# Edit .env and fill in AMPLITUDE_API_KEY and AMPLITUDE_SECRET_KEY
# Then load them into your shell:
export $(grep -v '^#' .env | xargs)

# 5. Launch the app
streamlit run app.py
```

Open **http://localhost:8501** in your browser.

The app is fully functional without step 4 — CSV uploads and sample datasets
work with no credentials.

---

## Deploy

### Option A — Streamlit Community Cloud (free tier)

Streamlit Community Cloud is the easiest zero-config host for Streamlit apps.

**1. Push to GitHub**

```bash
git init && git add -A
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/ai-mazing.git
git push -u origin main
```

Make sure `.env` and `.streamlit/secrets.toml` are listed in `.gitignore`
(they are by default) — **never push real credentials**.

**2. Connect to Streamlit Community Cloud**

1. Go to **[share.streamlit.io](https://share.streamlit.io)** and sign in with GitHub.
2. Click **"New app"**.
3. Select your repository and branch (`main`).
4. Set **Main file path** to `app.py`.
5. Click **"Deploy"**.

**3. Add Amplitude credentials (optional)**

1. In the Streamlit Cloud dashboard, open your deployed app.
2. Click the **⋮ menu → Settings → Secrets**.
3. Paste your credentials in TOML format — **do not wrap in quotes unless the
   value contains special characters**:

```toml
AMPLITUDE_API_KEY     = "your_api_key_here"
AMPLITUDE_SECRET_KEY  = "your_secret_key_here"
AMPLITUDE_PROJECT_ID  = ""        # optional — leave blank to auto-detect
AMPLITUDE_REGION      = "us"      # or "eu" for EU data-centre orgs
```

4. Click **Save**. The app restarts automatically and the
   📡 Amplitude (live) data source will become active.

> **Find your credentials:** Amplitude → Settings → Projects →
> [your project] → API Credentials.

---

### Option B — Render (free & paid tiers)

Render gives you a persistent server with zero cold-start on paid plans.

**1. Create a Web Service**

1. Go to **[render.com](https://render.com)** and sign in.
2. Click **"New → Web Service"**.
3. Connect your GitHub account and select the `ai-mazing` repository.
4. Configure the service:

| Field | Value |
|-------|-------|
| **Name** | `ai-mazing` (or anything you like) |
| **Runtime** | `Python 3` |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `streamlit run app.py --server.port $PORT --server.address 0.0.0.0` |
| **Instance Type** | Free (or Starter for always-on) |

5. Click **"Create Web Service"**.

**2. Add Amplitude credentials (optional)**

1. In the Render dashboard, open your service → **"Environment"** tab.
2. Add the following key/value pairs (Render encrypts these at rest):

| Key | Value |
|-----|-------|
| `AMPLITUDE_API_KEY` | your API key |
| `AMPLITUDE_SECRET_KEY` | your secret key |
| `AMPLITUDE_PROJECT_ID` | your project ID *(optional)* |
| `AMPLITUDE_REGION` | `us` or `eu` *(optional, default `us`)* |

3. Click **"Save Changes"**. Render redeploys automatically.

> **Note:** On Render's free tier the service spins down after 15 minutes of
> inactivity. First load after spin-down takes ~30 seconds. Upgrade to Starter
> ($7/mo) for always-on.

---

### ⚠️ Amplitude keys are always optional

The app runs completely without Amplitude credentials:

| Data source | Requires credentials? |
|-------------|----------------------|
| 📁 Upload CSV | ❌ No |
| 🛒 Sample datasets (ecommerce, events, sales, users) | ❌ No |
| 📡 Amplitude (live) | ✅ Yes — graceful error + fallback if absent |

---

## Using the analyst engine directly (no UI)

```python
from analyst import run_analysis, generate_sample_dataset, export_report_pdf

# With a CSV file
result = run_analysis("my_data.csv", "What are the top products by revenue?")

# With a pandas DataFrame
import pandas as pd
df = pd.read_csv("orders.csv")
result = run_analysis(df, "Show me the weekly trend in sales")

# With a built-in sample
df = generate_sample_dataset("ecommerce")   # ecommerce | events | sales | users
result = run_analysis(df, "Which country drives the most revenue?")

# Result dict
print(result["summary"])        # plain-language headline + supporting facts
print(result["cleaning_log"])   # what was cleaned and why
print(result["chart_paths"])    # absolute paths to saved PNG charts
print(result["caveats"])        # data-quality / methodology warnings

# Export to PDF
pdf_path = export_report_pdf(result)
print(pdf_path)                 # e.g. outputs/report_20250627_120000.pdf
```

---

## Using the Amplitude connector directly

```python
from amplitude_source import fetch_amplitude_events, summarise_by_event

# Set credentials via env vars first:
# export AMPLITUDE_API_KEY=...
# export AMPLITUDE_SECRET_KEY=...

df, status = fetch_amplitude_events(metric="totals", days=7, limit=50)

if status.ok:
    print(df.head())
    print(summarise_by_event(df))
else:
    print(status)   # human-readable error with status.code + status.message
```

---

## Playbook steps

| Step | What it does |
|------|-------------|
| **LOAD** | Reads CSV / DataFrame / Excel / Parquet / JSON; auto-parses date columns; reports shape, dtypes, nulls, 5-row sample |
| **CLEAN** | Strips whitespace · drops fully-empty columns · removes exact duplicates · median-imputes small numeric gaps · fills string nulls with `(unknown)` |
| **PROFILE** | Per-column stats: mean/median/std/min/max/Q1/Q3 for numerics; top-5 values for categoricals; date range for datetimes; IQR-based outlier counts |
| **ANALYZE** | Keyword-routed: top-N · time-series · distribution · correlation · segment/group breakdown |
| **VISUALIZE** | Saves up to 4 PNGs to `outputs/`: horizontal bar · time-series line · distribution histogram · correlation heatmap |
| **REPORT** | Plain-language headline + supporting facts + explicit caveats list |

---

## Built-in sample datasets

| Name | Rows | Description |
|------|------|-------------|
| `ecommerce` | 2,000 | Orders: product, country, quantity, revenue, rating |
| `events` | 10,000 | Amplitude-style events: event_name, platform, country, timestamp |
| `sales` | 1,500 | Pipeline: rep, region, deal value, win/loss, days to close |
| `users` | 3,000 | Cohort: plan tier, sessions, LTV, churn flag |

---

## Requirements

- Python **3.9+**
- See `requirements.txt` for fully-pinned dependency versions

---

## Security notes

- **Never commit `.env` or `.streamlit/secrets.toml`** — both are in `.gitignore`.
- Credentials are resolved exclusively via `st.secrets` (Streamlit) or environment
  variables — nothing is hardcoded in source files.
- `outputs/` PNGs and PDFs are gitignored; they are ephemeral and may contain
  data from your analysis.
