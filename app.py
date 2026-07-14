"""
app.py — AI-mazing Data Analyst · Streamlit Front-End
======================================================
Run with:
    streamlit run app.py

The app lets a user:
    1. Upload a CSV OR pick a pre-built sample dataset OR pull live Amplitude data
    2. Type a plain-language question
    3. Click "Analyse" to run the full playbook via analyst.py
    4. Browse results across four tabs:
       📋 Profile | 📊 Charts | 📝 Report | 🔧 Raw Stats
"""

import io
import os
import time

import pandas as pd
import streamlit as st
from PIL import Image

# ── Import the analyst engine ─────────────────────────────────────────────────
from analyst import (
    run_analysis,
    generate_sample_dataset,
    export_report_pdf,
    analyze_with_code_execution,   # feature-flagged cloud engine
    PLAYBOOK,                      # exposed for sidebar info tooltip
)

# ── Import the Amplitude data connector ──────────────────────────────────────
from amplitude_source import fetch_amplitude_events, summarise_by_event

# ─────────────────────────────────────────────────────────────────────────────
# HELPER — render a file returned by analyze_with_code_execution
# ─────────────────────────────────────────────────────────────────────────────

def render_output_file(file_ref: dict) -> None:
    """
    Render one entry from analyze_with_code_execution()["files"].

    file_ref keys:
        name       str    — original filename (e.g. 'top_events_bar.png')
        mime_type  str    — MIME type (e.g. 'image/png', 'text/csv')
        data       bytes  — raw file bytes

    Images are displayed inline via st.image().
    All other types get a st.download_button().
    """
    name = file_ref.get("name", "output")
    mime_type = file_ref.get("mime_type", "application/octet-stream")
    data = file_ref.get("data", b"")

    if isinstance(data, str):          # guard: base64 string sneaked through
        import base64
        data = base64.b64decode(data)

    if mime_type.startswith("image/"):
        st.image(data, caption=name, use_container_width=True)
    else:
        st.download_button(
            label     = f"⬇ Download {name}",
            data      = data,
            file_name = name,
            mime      = mime_type,
        )

# ─────────────────────────────────────────────────────────────────────────────
# HELPER — reset session for a fresh analysis ("New Analysis" button)
# ─────────────────────────────────────────────────────────────────────────────

def start_new_analysis() -> None:
    """
    Clear any cached analysis state and rerun the app so the user lands back
    on the clean landing screen, ready to run a brand-new analysis.
    """
    for _k in ("last_result", "analysis_running", "run_token"):
        st.session_state.pop(_k, None)
    st.rerun()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI-mazing Analyst",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS — clean, modern look ──────────────────────────────────────────
st.markdown("""
<style>
    /* Main background */
    .stApp { background: #f4f4f8; }

    /* Sidebar */
    [data-testid="stSidebar"] { background: #1a1a2e; color: #fff; }
    [data-testid="stSidebar"] * { color: #e0e0e0 !important; }
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stRadio label { color: #c0c0d0 !important; }

    /* Cards */
    .analyst-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    }

    /* Metric pills */
    .metric-pill {
        display: inline-block;
        background: #4361EE18;
        color: #4361EE;
        border: 1px solid #4361EE44;
        border-radius: 20px;
        padding: 0.2rem 0.75rem;
        font-size: 0.82rem;
        font-weight: 600;
        margin: 0.2rem 0.2rem 0.2rem 0;
    }

    /* Cleaning log items */
    .log-item {
        font-family: monospace;
        font-size: 0.82rem;
        background: #f0f4ff;
        border-left: 3px solid #4361EE;
        padding: 0.3rem 0.75rem;
        margin: 0.3rem 0;
        border-radius: 0 6px 6px 0;
    }

    /* Caveat items */
    .caveat-item {
        font-size: 0.85rem;
        background: #fff8e1;
        border-left: 3px solid #FF9800;
        padding: 0.3rem 0.75rem;
        margin: 0.3rem 0;
        border-radius: 0 6px 6px 0;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 0.5rem 1.25rem;
        font-weight: 600;
        background: #e8eaf6;
    }
    .stTabs [aria-selected="true"] {
        background: #4361EE !important;
        color: white !important;
    }

    /* Hide Streamlit branding */
    #MainMenu, footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — Data source + question
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🔬 AI-mazing Analyst")
    st.markdown("Powered by the **LOAD→CLEAN→PROFILE→ANALYZE→VISUALIZE→REPORT** playbook.")
    st.divider()

    # ── Data source ───────────────────────────────────────────────────────────
    st.markdown("### 📂 Data Source")
    data_source = st.radio(
        "Choose input",
        ["Upload File", "Sample Dataset", "📡 Amplitude (live)"],
        label_visibility="collapsed",
    )

    uploaded_file = None
    sample_name   = None
    amp_days      = 7
    amp_metric    = "totals"

    if data_source == "Upload File":
        uploaded_file = st.file_uploader(
            "Drop a CSV, Excel, or PDF file here",
            type=["csv", "xlsx", "xls", "pdf"],
            help="CSV, Excel (.xlsx/.xls), or PDF (tables extracted). Max ~50 MB.",
        )
        excel_sheet = None
        if uploaded_file is not None and uploaded_file.name.lower().endswith((".xlsx", ".xls")):
            try:
                _xls = pd.ExcelFile(uploaded_file)
                excel_sheet = st.selectbox("Excel sheet", options=_xls.sheet_names)
                uploaded_file.seek(0)      # reset pointer after peeking
            except Exception as _e:
                st.error(f"Could not read Excel sheets: {_e}")

    elif data_source == "Sample Dataset":
        sample_name = st.selectbox(
            "Pick a sample dataset",
            options=["ecommerce", "events", "sales", "users"],
            format_func=lambda x: {
                "ecommerce": "🛒 E-Commerce Orders",
                "events":    "📡 Product Events (Amplitude-style)",
                "sales":     "💼 Sales Pipeline",
                "users":     "👤 User Cohort",
            }[x],
        )
        st.caption({
            "ecommerce": "2,000 orders · product, country, revenue, rating",
            "events":    "10,000 events · event_name, platform, country",
            "sales":     "1,500 deals · rep, region, deal_value, won",
            "users":     "3,000 users · plan, sessions, LTV, churn",
        }[sample_name])

    else:  # Amplitude (live)
        from amplitude_source import _get_secret
        _proj_id = _get_secret("AMPLITUDE_PROJECT_ID", default="(not set)")
        st.markdown(f"**Amplitude project ID:** `{_proj_id}`")
        amp_days = st.slider(
            "Lookback window (days)",
            min_value=1, max_value=90, value=7, step=1,
        )
        amp_metric = st.selectbox(
            "Metric",
            options=["totals", "uniques", "average"],
            format_func=lambda x: {
                "totals":  "Totals (event count)",
                "uniques": "Uniques (distinct users)",
                "average": "Average (events / user)",
            }[x],
        )
        cred_ok = bool(
            os.getenv("AMPLITUDE_API_KEY") and os.getenv("AMPLITUDE_SECRET_KEY")
        )
        if cred_ok:
            st.success("✅ Credentials detected")
        else:
            st.warning(
                "Set **AMPLITUDE_API_KEY** and **AMPLITUDE_SECRET_KEY** "
                "as env vars to enable live data. "
                "Find them in Amplitude → Settings → Projects → API Credentials.",
                icon="🔑",
            )

    st.divider()

    # ── Analysis engine ───────────────────────────────────────────────────────
    st.markdown("### ⚙️ Analysis Engine")

    _code_exec_enabled = os.environ.get("ENABLE_CODE_EXEC") == "1"
    _engine_options = [
        "Local (fast, free)",
        "Claude code-execution (Fable 5)",
    ]
    analysis_engine = st.radio(
        "Engine",
        _engine_options,
        index=0,                       # default → Local; no cost/behaviour change
        label_visibility="collapsed",
        help=(
            "**Local**: runs the built-in pandas/matplotlib pipeline instantly, "
            "at zero cost.\n\n"
            "**Claude code-execution**: streams the full playbook to a Claude "
            "model with server-side code execution (~$0.44 / ~80 s per run). "
            "Requires ANTHROPIC_API_KEY and ENABLE_CODE_EXEC=1."
        ),
    )

    if analysis_engine == "Claude code-execution (Fable 5)":
        if _code_exec_enabled:
            _anthro_set = bool(
                os.environ.get("ANTHROPIC_API_KEY")
                or (__import__("streamlit").secrets.get("ANTHROPIC_API_KEY", "")
                    if hasattr(__import__("streamlit"), "secrets") else "")
            )
            if _anthro_set:
                st.success("✅ ANTHROPIC_API_KEY detected", icon="🤖")
            else:
                st.warning("Set **ANTHROPIC_API_KEY** to use this engine.", icon="🔑")
            st.caption("~$0.44 · ~80 s per run")
        else:
            st.info(
                "Set **ENABLE_CODE_EXEC=1** as an env var to unlock this engine.",
                icon="🔒",
            )

    st.divider()

    # ── Question ──────────────────────────────────────────────────────────────
    st.markdown("### ❓ Your Question")
    question = st.text_area(
        "Ask anything about the data",
        value="What are the top events by volume and how do they trend over time?",
        height=110,
        label_visibility="collapsed",
    )

    st.divider()

    # ── Analyse button ────────────────────────────────────────────────────────
    run_btn = st.button(
        "🚀 Analyse",
        use_container_width=True,
        type="primary",
    )

    # ── New Analysis button ─────────────────────────────────────────────────
    # Clears any previous results and returns to the clean landing screen so the
    # user can start a fresh analysis without manually resetting inputs.
    new_btn = st.button(
        "🆕 New Analysis",
        use_container_width=True,
        help="Clear the current results and start a brand-new analysis.",
    )
    if new_btn:
        start_new_analysis()

    st.markdown("""
    <div style='margin-top:2rem;font-size:0.75rem;color:#888;text-align:center;'>
        AI-mazing v1.1 · analyst.py + amplitude_source.py<br>
        Charts &amp; PDFs saved to <code>outputs/</code>
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# HERO — landing state
# ─────────────────────────────────────────────────────────────────────────────

if not run_btn:
    st.markdown("""
    <div class='analyst-card' style='text-align:center;padding:3rem 2rem;'>
        <div style='font-size:3.5rem;'>🔬</div>
        <h1 style='color:#1a1a2e;margin:0.5rem 0;'>AI-mazing Data Analyst</h1>
        <p style='color:#555;font-size:1.05rem;max-width:560px;margin:0 auto;'>
            Upload a CSV or pick a sample dataset, type your question,
            and click <strong>Analyse</strong> to run the full
            LOAD → CLEAN → PROFILE → ANALYZE → VISUALIZE → REPORT playbook.
        </p>
        <div style='margin-top:1.5rem;'>
            <span class='metric-pill'>📥 Auto-load & parse</span>
            <span class='metric-pill'>🧹 Smart cleaning</span>
            <span class='metric-pill'>📊 Auto-charts</span>
            <span class='metric-pill'>📝 Plain-language report</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Sample question suggestions
    st.markdown("#### 💡 Try asking...")
    cols = st.columns(2)
    suggestions = [
        ("🛒", "What products generate the most revenue?"),
        ("📡", "What are the top events by volume?"),
        ("💼", "Which region has the best win rate?"),
        ("👤", "How does LTV differ by plan tier?"),
    ]
    for i, (icon, q) in enumerate(suggestions):
        cols[i % 2].info(f"{icon} _{q}_")

    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────────────────────────────────────

amp_status    = None       # populated only for the Amplitude path
fallback_used = False      # True when Amplitude is empty and we fell back to sample

# ── "Still analyzing" alert ──────────────────────────────────────────────────
# Shown as soon as the user clicks Analyse so they get immediate feedback that
# the (potentially slow) playbook is running. It is cleared automatically once
# results are ready further down.
_analyzing_alert = st.empty()
_analyzing_alert.info("⏳ Analysing your data — this can take a moment. Please wait…", icon="⏳")

with st.spinner("📥 Loading data…"):

    # ── CSV upload ────────────────────────────────────────────────────────────
    if data_source == "Upload File":
        if uploaded_file is None:
            _analyzing_alert.empty()
            st.error("⚠️ Please upload a CSV or Excel file first.")
            st.stop()
        _fname = uploaded_file.name.lower()
        if _fname.endswith((".xlsx", ".xls")):
            uploaded_file.seek(0)
            df_input = pd.read_excel(uploaded_file, sheet_name=excel_sheet)
            source_label = f"{uploaded_file.name} · sheet: {excel_sheet}"
        elif _fname.endswith(".pdf"):
            uploaded_file.seek(0)
            df_input = uploaded_file   # analyst._load extracts tables from PDFs
            source_label = f"{uploaded_file.name} (PDF · tables extracted)"
        else:
            df_input = uploaded_file   # analyst._load handles CSV file-like objects
            source_label = uploaded_file.name

    # ── Sample dataset ────────────────────────────────────────────────────────
    elif data_source == "Sample Dataset":
        df_input = generate_sample_dataset(sample_name)
        source_label = f"Sample: {sample_name}"

    # ── Amplitude (live) ──────────────────────────────────────────────────────
    else:
        df_input, amp_status = fetch_amplitude_events(
            metric=amp_metric,
            days=amp_days,
        )
        source_label = f"Amplitude live · last {amp_days}d · {amp_metric}"

        # ── Handle every non-ok status ────────────────────────────────────────
        if not amp_status.ok:

            _analyzing_alert.empty()

            # Show a specific, friendly message per status code
            if amp_status.code == "no_credentials":
                st.warning(
                    "**No API credentials found.**\n\n"
                    f"{amp_status.message}\n\n"
                    "Tip: `export AMPLITUDE_API_KEY=... AMPLITUDE_SECRET_KEY=...` "
                    "then restart Streamlit.",
                    icon="🔑",
                )

            elif amp_status.code == "empty_project":
                st.info(
                    "**Your Amplitude project has no events yet.** "
                    "Connect an SDK, track some events, then come back — "
                    "the chart will populate automatically.\n\n"
                    f"_Project ID: {amp_status.project_id} · "
                    f"Window: last {amp_days} day(s)_",
                    icon="📭",
                )

            else:  # api_error | parse_error
                st.error(
                    f"**Amplitude API error** (`{amp_status.code}`):\n\n"
                    f"{amp_status.message}",
                    icon="🚨",
                )

            # ── Fallback offer ────────────────────────────────────────────────
            st.markdown("---")
            st.markdown(
                "#### 🔄 Fall back to a sample dataset?\n"
                "You can still explore the analyst with realistic demo data "
                "while you set up your Amplitude instrumentation."
            )
            col_fb1, col_fb2 = st.columns([1, 3])
            with col_fb1:
                fallback_btn = st.button(
                    "Use 'events' sample",
                    type="primary",
                    use_container_width=True,
                )
            with col_fb2:
                st.caption(
                    "Loads the built-in Amplitude-style events sample "
                    "(10,000 rows · event_name, platform, country, timestamp)."
                )

            if fallback_btn:
                df_input = generate_sample_dataset("events")
                source_label = "Sample (fallback): events"
                fallback_used = True
                st.success(
                    "✅ Loaded the 'events' sample dataset as a fallback. "
                    "Click **Analyse** again to run the playbook.",
                    icon="🎉",
                )
            else:
                st.stop()   # wait for user to choose fallback or fix credentials

# ─────────────────────────────────────────────────────────────────────────────
# RUN PLAYBOOK — branches on analysis_engine
# ─────────────────────────────────────────────────────────────────────────────

_use_cloud = (
    analysis_engine == "Claude code-execution (Fable 5)"
    and os.environ.get("ENABLE_CODE_EXEC") == "1"
)

# ══════════════════════════════════════════════════════════════════════════════
# BRANCH A — Cloud code-execution engine (feature-flagged)
# ══════════════════════════════════════════════════════════════════════════════
if _use_cloud:

    # Build the user prompt: question + a CSV snapshot of the dataframe
    # (analyst._load already returned a clean df via run_analysis; here we
    #  re-load so we can serialise it without coupling to the local pipeline)
    try:
        from analyst import _load, _clean  # noqa: PLC0415
        _df_raw   = _load(df_input)["df"]
        _df_clean = _clean(_df_raw)["df"]
        _csv_snap = _df_clean.head(500).to_csv(index=False)   # cap at 500 rows
    except Exception as _e:
        _csv_snap = f"(could not serialise dataframe: {_e})"

    _user_prompt = (
        f"{question}\n\n"
        f"Here is the dataset (up to 500 rows):\n\n```csv\n{_csv_snap}\n```"
    )

    with st.spinner("🤖 Streaming Claude code-execution playbook… (~80 s)"):
        t0 = time.time()
        ce_result = analyze_with_code_execution(_user_prompt)
        elapsed = time.time() - t0

    _analyzing_alert.empty()

    st.success(
        f"✅ Code-execution playbook complete in **{elapsed:.0f}s** | "
        f"Source: *{source_label}*"
    )

    # ── Usage / cost caption ──────────────────────────────────────────────────
    _usage = ce_result.get("usage", {})
    if _usage:
        st.caption(
            f"🪙 Tokens — input: {_usage.get('input_tokens', '?'):,} "
            f"output: {_usage.get('output_tokens', '?'):,} "
            f"| Est. cost: **~$0.44** | Note: costs vary by actual token usage."
        )

    # ── Render report markdown ────────────────────────────────────────────────
    st.markdown("### 📝 Analysis Report")
    report_md = ce_result.get("report", "")
    if report_md:
        st.markdown(report_md)
    else:
        st.info("No report text returned from the model.", icon="ℹ️")

    # ── Render output files (charts / CSVs) ───────────────────────────────────
    _files = ce_result.get("files", [])
    if _files:
        st.markdown("### 📊 Output Files")
        for _fref in _files:
            render_output_file(_fref)

# ══════════════════════════════════════════════════════════════════════════════
# BRANCH B — Local pipeline (default; unchanged from before)
# ══════════════════════════════════════════════════════════════════════════════
else:
    progress_bar = st.progress(0, text="Starting playbook…")
    status_holder = st.empty()

    steps = [
        (15,  "📥 LOAD — reading & parsing…"),
        (35,  "🧹 CLEAN — removing nulls & duplicates…"),
        (55,  "📐 PROFILE — computing column statistics…"),
        (72,  "🧠 ANALYZE — finding patterns…"),
        (88,  "📊 VISUALIZE — generating charts…"),
        (100, "📝 REPORT — writing summary…"),
    ]

    for pct, msg in steps:
        progress_bar.progress(pct, text=msg)
        time.sleep(0.18)

    t0 = time.time()
    result = run_analysis(df_input, question)
    elapsed = time.time() - t0

    progress_bar.empty()
    status_holder.empty()
    _analyzing_alert.empty()

    st.success(f"✅ Playbook complete in **{elapsed:.1f}s** · "
               f"{result['stats']['shape']['rows']:,} rows × "
               f"{result['stats']['shape']['cols']} columns | "
               f"Source: *{source_label}*")

    # Show Amplitude metadata banner when live data was used successfully
    if amp_status and amp_status.ok:
        st.info(
            f"📡 **Amplitude live data** — {amp_status.message} "
            f"| Events: {', '.join(amp_status.events[:6])}"
            + (" …" if len(amp_status.events) > 6 else ""),
            icon="📡",
        )
    elif fallback_used:
        st.warning(
            "⚠️ Amplitude returned no data — showing **sample 'events' dataset** as fallback.",
            icon="🔄",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # QUICK METRIC STRIP
    # ─────────────────────────────────────────────────────────────────────────

    m1, m2, m3, m4 = st.columns(4)
    shape = result["stats"]["shape"]
    nulls = sum(result["stats"]["null_counts"].values())
    n_charts = len(result["chart_paths"])
    n_clean = len(result["cleaning_log"])

    m1.metric("📋 Rows", f"{shape['rows']:,}")
    m2.metric("📏 Columns", shape["cols"])
    m3.metric("🚿 Nulls left", nulls, delta=None if nulls == 0 else f"{nulls} remaining")
    m4.metric("📊 Charts", n_charts)

    # ─────────────────────────────────────────────────────────────────────────
    # TABS
    # ─────────────────────────────────────────────────────────────────────────

    tab_profile, tab_charts, tab_report, tab_raw = st.tabs(
        ["📋 Profile", "📊 Charts", "📝 Report", "🔧 Raw Stats"]
    )

    # ── TAB 1: PROFILE ────────────────────────────────────────────────────────
    with tab_profile:
        st.markdown("### Data Profile")

        with st.expander("🧹 Cleaning Log", expanded=False):
            for entry in result["cleaning_log"]:
                st.markdown(f"<div class='log-item'>✓ {entry}</div>",
                            unsafe_allow_html=True)

        st.markdown("---")

        profile = result["stats"]["profile"]
        cols_list = list(profile.keys())
        ncols = min(2, len(cols_list))
        grid = st.columns(ncols)

        for i, col_name in enumerate(cols_list):
            info = profile[col_name]
            with grid[i % ncols]:
                dtype_badge = {
                    "int": "🔢", "float": "🔢", "object": "🔤",
                    "bool": "☑️", "datetime": "📅",
                }.get(info["dtype"].split("[")[0].split("6")[0], "❓")

                st.markdown(f"""
                <div class='analyst-card'>
                    <strong>{dtype_badge} {col_name}</strong>
                    <span style='font-size:0.75rem;color:#888;margin-left:0.5rem;'>
                        {info['dtype']}
                    </span><br>
                    <span class='metric-pill'>{info['n_unique']:,} unique</span>
                    <span class='metric-pill'>{info['null_count']} nulls</span>
                """, unsafe_allow_html=True)

                if "mean" in info:
                    st.markdown(f"""
                        <span class='metric-pill'>μ {info['mean']:,}</span>
                        <span class='metric-pill'>med {info['median']:,}</span>
                        <span class='metric-pill'>σ {info['std']:,}</span>
                    """, unsafe_allow_html=True)
                    if info["n_outliers"] > 0:
                        st.markdown(
                            f"    <span class='metric-pill' style='background:#ffe0e0;"
                            f"color:#c00;border-color:#f00a;'>"
                            f"⚠ {info['n_outliers']} outliers ({info['outlier_pct']}%)"
                            f"</span>",
                            unsafe_allow_html=True,
                        )
                elif "top_values" in info:
                    top_str = " · ".join(
                        f"{k} ({v:,})" for k, v in list(info["top_values"].items())[:3]
                    )
                    st.caption(f"Top values: {top_str}")
                elif "range_days" in info:
                    st.caption(f"📅 {info['min_date'][:10]} → {info['max_date'][:10]} "
                               f"({info['range_days']} days)")

                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("#### 🗂️ Data Sample (first 5 rows)")
        sample_df = pd.DataFrame(result["stats"]["sample"])
        st.dataframe(sample_df, use_container_width=True)

    # ── TAB 2: CHARTS ─────────────────────────────────────────────────────────
    with tab_charts:
        st.markdown("### Generated Charts")

        chart_paths = result["chart_paths"]
        if not chart_paths:
            st.info("No charts generated — the dataset may have no plottable columns.")
        else:
            for idx in range(0, len(chart_paths), 2):
                cols = st.columns(2)
                for j, path in enumerate(chart_paths[idx: idx + 2]):
                    if os.path.exists(path):
                        img = Image.open(path)
                        with cols[j]:
                            st.image(img, use_container_width=True)
                            with open(path, "rb") as f:
                                st.download_button(
                                    label=f"⬇ Download {os.path.basename(path)}",
                                    data=f,
                                    file_name=os.path.basename(path),
                                    mime="image/png",
                                    key=f"dl_{idx}_{j}",
                                )

    # ── TAB 3: REPORT ─────────────────────────────────────────────────────────
    with tab_report:
        st.markdown("### Plain-Language Report")

        st.markdown(f"""
        <div class='analyst-card' style='border-left:4px solid #4361EE;'>
            <strong>❓ Question asked:</strong> {question}
        </div>
        """, unsafe_allow_html=True)

        st.markdown(result["summary"])
        st.divider()

        st.markdown("#### ⚠️ Caveats")
        for caveat in result["caveats"]:
            st.markdown(f"<div class='caveat-item'>⚠ {caveat}</div>",
                        unsafe_allow_html=True)

        st.divider()

        dl_col1, dl_col2 = st.columns(2)

        report_text = (
            f"Question: {question}\n\n"
            + result["summary"].replace("**", "").replace("###", "")
            + "\n\nCaveats:\n"
            + "\n".join(f"- {c}" for c in result["caveats"])
            + "\n\nCleaning Log:\n"
            + "\n".join(f"- {l}" for l in result["cleaning_log"])
        )
        with dl_col1:
            st.download_button(
                label="⬇ Download Report (.txt)",
                data=report_text,
                file_name="analyst_report.txt",
                mime="text/plain",
            )

        with dl_col2:
            with st.spinner("📄 Building PDF…"):
                pdf_path = export_report_pdf(result)
                with open(pdf_path, "rb") as pdf_file:
                    st.download_button(
                        label="📄 Download PDF Report",
                        data=pdf_file,
                        file_name="analyst_report.pdf",
                        mime="application/pdf",
                        type="primary",
                    )

    # ── TAB 4: RAW STATS ──────────────────────────────────────────────────────
    with tab_raw:
        st.markdown("### Raw Stats (JSON)")
        st.caption("Full output from `run_analysis()` — useful for debugging or downstream use.")
        st.json(result["stats"], expanded=False)

        st.markdown("#### Findings dict")
        st.json(result["stats"].get("findings", {}), expanded=False)
"""
app.py — AI-mazing Data Analyst · Streamlit Front-End
======================================================
Run with:
    streamlit run app.py

The app lets a user:
    1. Upload a CSV OR pick a pre-built sample dataset OR pull live Amplitude data
    2. Type a plain-language question
    3. Click "Analyse" to run the full playbook via analyst.py
    4. Browse results across four tabs:
       📋 Profile | 📊 Charts | 📝 Report | 🔧 Raw Stats
"""

import io
import os
import time

import pandas as pd
import streamlit as st
from PIL import Image

# ── Import the analyst engine ─────────────────────────────────────────────────
from analyst import (
    run_analysis,
    generate_sample_dataset,
    export_report_pdf,
    analyze_with_code_execution,   # feature-flagged cloud engine
    PLAYBOOK,                      # exposed for sidebar info tooltip
)

# ── Import the Amplitude data connector ──────────────────────────────────────
from amplitude_source import fetch_amplitude_events, summarise_by_event

# ─────────────────────────────────────────────────────────────────────────────
# HELPER — render a file returned by analyze_with_code_execution
# ─────────────────────────────────────────────────────────────────────────────

def render_output_file(file_ref: dict) -> None:
    """
    Render one entry from analyze_with_code_execution()["files"].

    file_ref keys:
        name       str    — original filename (e.g. 'top_events_bar.png')
        mime_type  str    — MIME type (e.g. 'image/png', 'text/csv')
        data       bytes  — raw file bytes

    Images are displayed inline via st.image().
    All other types get a st.download_button().
    """
    name = file_ref.get("name", "output")
    mime_type = file_ref.get("mime_type", "application/octet-stream")
    data = file_ref.get("data", b"")

    if isinstance(data, str):          # guard: base64 string sneaked through
        import base64
        data = base64.b64decode(data)

    if mime_type.startswith("image/"):
        st.image(data, caption=name, use_container_width=True)
    else:
        st.download_button(
            label     = f"⬇ Download {name}",
            data      = data,
            file_name = name,
            mime      = mime_type,
        )

# ─────────────────────────────────────────────────────────────────────────────
# HELPER — reset session for a fresh analysis ("New Analysis" button)
# ─────────────────────────────────────────────────────────────────────────────

def start_new_analysis() -> None:
    """
    Clear any cached analysis state and rerun the app so the user lands back
    on the clean landing screen, ready to run a brand-new analysis.
    """
    for _k in ("last_result", "analysis_running", "run_token"):
        st.session_state.pop(_k, None)
    st.rerun()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AI-mazing Analyst",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS — clean, modern look ──────────────────────────────────────────
st.markdown("""
<style>
    /* Main background */
    .stApp { background: #f4f4f8; }

    /* Sidebar */
    [data-testid="stSidebar"] { background: #1a1a2e; color: #fff; }
    [data-testid="stSidebar"] * { color: #e0e0e0 !important; }
    [data-testid="stSidebar"] .stSelectbox label,
    [data-testid="stSidebar"] .stRadio label { color: #c0c0d0 !important; }

    /* Cards */
    .analyst-card {
        background: #ffffff;
        border-radius: 12px;
        padding: 1.25rem 1.5rem;
        margin-bottom: 1rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.07);
    }

    /* Metric pills */
    .metric-pill {
        display: inline-block;
        background: #4361EE18;
        color: #4361EE;
        border: 1px solid #4361EE44;
        border-radius: 20px;
        padding: 0.2rem 0.75rem;
        font-size: 0.82rem;
        font-weight: 600;
        margin: 0.2rem 0.2rem 0.2rem 0;
    }

    /* Cleaning log items */
    .log-item {
        font-family: monospace;
        font-size: 0.82rem;
        background: #f0f4ff;
        border-left: 3px solid #4361EE;
        padding: 0.3rem 0.75rem;
        margin: 0.3rem 0;
        border-radius: 0 6px 6px 0;
    }

    /* Caveat items */
    .caveat-item {
        font-size: 0.85rem;
        background: #fff8e1;
        border-left: 3px solid #FF9800;
        padding: 0.3rem 0.75rem;
        margin: 0.3rem 0;
        border-radius: 0 6px 6px 0;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 0.5rem 1.25rem;
        font-weight: 600;
        background: #e8eaf6;
    }
    .stTabs [aria-selected="true"] {
        background: #4361EE !important;
        color: white !important;
    }

    /* Hide Streamlit branding */
    #MainMenu, footer { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# SIDEBAR — Data source + question
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🔬 AI-mazing Analyst")
    st.markdown("Powered by the **LOAD→CLEAN→PROFILE→ANALYZE→VISUALIZE→REPORT** playbook.")
    st.divider()

    # ── Data source ───────────────────────────────────────────────────────────
    st.markdown("### 📂 Data Source")
    data_source = st.radio(
        "Choose input",
        ["Upload File", "Sample Dataset", "📡 Amplitude (live)"],
        label_visibility="collapsed",
    )

    uploaded_file = None
    sample_name   = None
    amp_days      = 7
    amp_metric    = "totals"

    if data_source == "Upload File":
        uploaded_file = st.file_uploader(
            "Drop a CSV or Excel file here",
            type=["csv", "xlsx", "xls"],
            help="CSV or Excel (.xlsx/.xls). Max ~50 MB.",
        )
        excel_sheet = None
        if uploaded_file is not None and uploaded_file.name.lower().endswith((".xlsx", ".xls")):
            try:
                _xls = pd.ExcelFile(uploaded_file)
                excel_sheet = st.selectbox("Excel sheet", options=_xls.sheet_names)
                uploaded_file.seek(0)      # reset pointer after peeking
            except Exception as _e:
                st.error(f"Could not read Excel sheets: {_e}")

    elif data_source == "Sample Dataset":
        sample_name = st.selectbox(
            "Pick a sample dataset",
            options=["ecommerce", "events", "sales", "users"],
            format_func=lambda x: {
                "ecommerce": "🛒 E-Commerce Orders",
                "events":    "📡 Product Events (Amplitude-style)",
                "sales":     "💼 Sales Pipeline",
                "users":     "👤 User Cohort",
            }[x],
        )
        st.caption({
            "ecommerce": "2,000 orders · product, country, revenue, rating",
            "events":    "10,000 events · event_name, platform, country",
            "sales":     "1,500 deals · rep, region, deal_value, won",
            "users":     "3,000 users · plan, sessions, LTV, churn",
        }[sample_name])

    else:  # Amplitude (live)
        from amplitude_source import _get_secret
        _proj_id = _get_secret("AMPLITUDE_PROJECT_ID", default="(not set)")
        st.markdown(f"**Amplitude project ID:** `{_proj_id}`")
        amp_days = st.slider(
            "Lookback window (days)",
            min_value=1, max_value=90, value=7, step=1,
        )
        amp_metric = st.selectbox(
            "Metric",
            options=["totals", "uniques", "average"],
            format_func=lambda x: {
                "totals":  "Totals (event count)",
                "uniques": "Uniques (distinct users)",
                "average": "Average (events / user)",
            }[x],
        )
        cred_ok = bool(
            os.getenv("AMPLITUDE_API_KEY") and os.getenv("AMPLITUDE_SECRET_KEY")
        )
        if cred_ok:
            st.success("✅ Credentials detected")
        else:
            st.warning(
                "Set **AMPLITUDE_API_KEY** and **AMPLITUDE_SECRET_KEY** "
                "as env vars to enable live data. "
                "Find them in Amplitude → Settings → Projects → API Credentials.",
                icon="🔑",
            )

    st.divider()

    # ── Analysis engine ───────────────────────────────────────────────────────
    st.markdown("### ⚙️ Analysis Engine")

    _code_exec_enabled = os.environ.get("ENABLE_CODE_EXEC") == "1"
    _engine_options = [
        "Local (fast, free)",
        "Claude code-execution (Fable 5)",
    ]
    analysis_engine = st.radio(
        "Engine",
        _engine_options,
        index=0,                       # default → Local; no cost/behaviour change
        label_visibility="collapsed",
        help=(
            "**Local**: runs the built-in pandas/matplotlib pipeline instantly, "
            "at zero cost.\n\n"
            "**Claude code-execution**: streams the full playbook to a Claude "
            "model with server-side code execution (~$0.44 / ~80 s per run). "
            "Requires ANTHROPIC_API_KEY and ENABLE_CODE_EXEC=1."
        ),
    )

    if analysis_engine == "Claude code-execution (Fable 5)":
        if _code_exec_enabled:
            _anthro_set = bool(
                os.environ.get("ANTHROPIC_API_KEY")
                or (__import__("streamlit").secrets.get("ANTHROPIC_API_KEY", "")
                    if hasattr(__import__("streamlit"), "secrets") else "")
            )
            if _anthro_set:
                st.success("✅ ANTHROPIC_API_KEY detected", icon="🤖")
            else:
                st.warning("Set **ANTHROPIC_API_KEY** to use this engine.", icon="🔑")
            st.caption("~$0.44 · ~80 s per run")
        else:
            st.info(
                "Set **ENABLE_CODE_EXEC=1** as an env var to unlock this engine.",
                icon="🔒",
            )

    st.divider()

    # ── Question ──────────────────────────────────────────────────────────────
    st.markdown("### ❓ Your Question")
    question = st.text_area(
        "Ask anything about the data",
        value="What are the top events by volume and how do they trend over time?",
        height=110,
        label_visibility="collapsed",
    )

    st.divider()

    # ── Analyse button ────────────────────────────────────────────────────────
    run_btn = st.button(
        "🚀 Analyse",
        use_container_width=True,
        type="primary",
    )

    # ── New Analysis button ─────────────────────────────────────────────────
    # Clears any previous results and returns to the clean landing screen so the
    # user can start a fresh analysis without manually resetting inputs.
    new_btn = st.button(
        "🆕 New Analysis",
        use_container_width=True,
        help="Clear the current results and start a brand-new analysis.",
    )
    if new_btn:
        start_new_analysis()

    st.markdown("""
    <div style='margin-top:2rem;font-size:0.75rem;color:#888;text-align:center;'>
        AI-mazing v1.1 · analyst.py + amplitude_source.py<br>
        Charts &amp; PDFs saved to <code>outputs/</code>
    </div>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# HERO — landing state
# ─────────────────────────────────────────────────────────────────────────────

if not run_btn:
    st.markdown("""
    <div class='analyst-card' style='text-align:center;padding:3rem 2rem;'>
        <div style='font-size:3.5rem;'>🔬</div>
        <h1 style='color:#1a1a2e;margin:0.5rem 0;'>AI-mazing Data Analyst</h1>
        <p style='color:#555;font-size:1.05rem;max-width:560px;margin:0 auto;'>
            Upload a CSV or pick a sample dataset, type your question,
            and click <strong>Analyse</strong> to run the full
            LOAD → CLEAN → PROFILE → ANALYZE → VISUALIZE → REPORT playbook.
        </p>
        <div style='margin-top:1.5rem;'>
            <span class='metric-pill'>📥 Auto-load & parse</span>
            <span class='metric-pill'>🧹 Smart cleaning</span>
            <span class='metric-pill'>📊 Auto-charts</span>
            <span class='metric-pill'>📝 Plain-language report</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Sample question suggestions
    st.markdown("#### 💡 Try asking...")
    cols = st.columns(2)
    suggestions = [
        ("🛒", "What products generate the most revenue?"),
        ("📡", "What are the top events by volume?"),
        ("💼", "Which region has the best win rate?"),
        ("👤", "How does LTV differ by plan tier?"),
    ]
    for i, (icon, q) in enumerate(suggestions):
        cols[i % 2].info(f"{icon} _{q}_")

    st.stop()

# ─────────────────────────────────────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────────────────────────────────────

amp_status    = None       # populated only for the Amplitude path
fallback_used = False      # True when Amplitude is empty and we fell back to sample

# ── "Still analyzing" alert ──────────────────────────────────────────────────
# Shown as soon as the user clicks Analyse so they get immediate feedback that
# the (potentially slow) playbook is running. It is cleared automatically once
# results are ready further down.
_analyzing_alert = st.empty()
_analyzing_alert.info("⏳ Analysing your data — this can take a moment. Please wait…", icon="⏳")

with st.spinner("📥 Loading data…"):

    # ── CSV upload ────────────────────────────────────────────────────────────
    if data_source == "Upload File":
        if uploaded_file is None:
            _analyzing_alert.empty()
            st.error("⚠️ Please upload a CSV or Excel file first.")
            st.stop()
        _fname = uploaded_file.name.lower()
        if _fname.endswith((".xlsx", ".xls")):
            uploaded_file.seek(0)
            df_input = pd.read_excel(uploaded_file, sheet_name=excel_sheet)
            source_label = f"{uploaded_file.name} · sheet: {excel_sheet}"
        else:
            df_input = uploaded_file   # analyst._load handles CSV file-like objects
            source_label = uploaded_file.name

    # ── Sample dataset ────────────────────────────────────────────────────────
    elif data_source == "Sample Dataset":
        df_input = generate_sample_dataset(sample_name)
        source_label = f"Sample: {sample_name}"

    # ── Amplitude (live) ──────────────────────────────────────────────────────
    else:
        df_input, amp_status = fetch_amplitude_events(
            metric=amp_metric,
            days=amp_days,
        )
        source_label = f"Amplitude live · last {amp_days}d · {amp_metric}"

        # ── Handle every non-ok status ────────────────────────────────────────
        if not amp_status.ok:

            _analyzing_alert.empty()

            # Show a specific, friendly message per status code
            if amp_status.code == "no_credentials":
                st.warning(
                    "**No API credentials found.**\n\n"
                    f"{amp_status.message}\n\n"
                    "Tip: `export AMPLITUDE_API_KEY=... AMPLITUDE_SECRET_KEY=...` "
                    "then restart Streamlit.",
                    icon="🔑",
                )

            elif amp_status.code == "empty_project":
                st.info(
                    "**Your Amplitude project has no events yet.** "
                    "Connect an SDK, track some events, then come back — "
                    "the chart will populate automatically.\n\n"
                    f"_Project ID: {amp_status.project_id} · "
                    f"Window: last {amp_days} day(s)_",
                    icon="📭",
                )

            else:  # api_error | parse_error
                st.error(
                    f"**Amplitude API error** (`{amp_status.code}`):\n\n"
                    f"{amp_status.message}",
                    icon="🚨",
                )

            # ── Fallback offer ────────────────────────────────────────────────
            st.markdown("---")
            st.markdown(
                "#### 🔄 Fall back to a sample dataset?\n"
                "You can still explore the analyst with realistic demo data "
                "while you set up your Amplitude instrumentation."
            )
            col_fb1, col_fb2 = st.columns([1, 3])
            with col_fb1:
                fallback_btn = st.button(
                    "Use 'events' sample",
                    type="primary",
                    use_container_width=True,
                )
            with col_fb2:
                st.caption(
                    "Loads the built-in Amplitude-style events sample "
                    "(10,000 rows · event_name, platform, country, timestamp)."
                )

            if fallback_btn:
                df_input = generate_sample_dataset("events")
                source_label = "Sample (fallback): events"
                fallback_used = True
                st.success(
                    "✅ Loaded the 'events' sample dataset as a fallback. "
                    "Click **Analyse** again to run the playbook.",
                    icon="🎉",
                )
            else:
                st.stop()   # wait for user to choose fallback or fix credentials

# ─────────────────────────────────────────────────────────────────────────────
# RUN PLAYBOOK — branches on analysis_engine
# ─────────────────────────────────────────────────────────────────────────────

_use_cloud = (
    analysis_engine == "Claude code-execution (Fable 5)"
    and os.environ.get("ENABLE_CODE_EXEC") == "1"
)

# ══════════════════════════════════════════════════════════════════════════════
# BRANCH A — Cloud code-execution engine (feature-flagged)
# ══════════════════════════════════════════════════════════════════════════════
if _use_cloud:

    # Build the user prompt: question + a CSV snapshot of the dataframe
    # (analyst._load already returned a clean df via run_analysis; here we
    #  re-load so we can serialise it without coupling to the local pipeline)
    try:
        from analyst import _load, _clean  # noqa: PLC0415
        _df_raw   = _load(df_input)["df"]
        _df_clean = _clean(_df_raw)["df"]
        _csv_snap = _df_clean.head(500).to_csv(index=False)   # cap at 500 rows
    except Exception as _e:
        _csv_snap = f"(could not serialise dataframe: {_e})"

    _user_prompt = (
        f"{question}\n\n"
        f"Here is the dataset (up to 500 rows):\n\n```csv\n{_csv_snap}\n```"
    )

    with st.spinner("🤖 Streaming Claude code-execution playbook… (~80 s)"):
        t0 = time.time()
        ce_result = analyze_with_code_execution(_user_prompt)
        elapsed = time.time() - t0

    _analyzing_alert.empty()

    st.success(
        f"✅ Code-execution playbook complete in **{elapsed:.0f}s** | "
        f"Source: *{source_label}*"
    )

    # ── Usage / cost caption ──────────────────────────────────────────────────
    _usage = ce_result.get("usage", {})
    if _usage:
        st.caption(
            f"🪙 Tokens — input: {_usage.get('input_tokens', '?'):,} "
            f"output: {_usage.get('output_tokens', '?'):,} "
            f"| Est. cost: **~$0.44** | Note: costs vary by actual token usage."
        )

    # ── Render report markdown ────────────────────────────────────────────────
    st.markdown("### 📝 Analysis Report")
    report_md = ce_result.get("report", "")
    if report_md:
        st.markdown(report_md)
    else:
        st.info("No report text returned from the model.", icon="ℹ️")

    # ── Render output files (charts / CSVs) ───────────────────────────────────
    _files = ce_result.get("files", [])
    if _files:
        st.markdown("### 📊 Output Files")
        for _fref in _files:
            render_output_file(_fref)

# ══════════════════════════════════════════════════════════════════════════════
# BRANCH B — Local pipeline (default; unchanged from before)
# ══════════════════════════════════════════════════════════════════════════════
else:
    progress_bar = st.progress(0, text="Starting playbook…")
    status_holder = st.empty()

    steps = [
        (15,  "📥 LOAD — reading & parsing…"),
        (35,  "🧹 CLEAN — removing nulls & duplicates…"),
        (55,  "📐 PROFILE — computing column statistics…"),
        (72,  "🧠 ANALYZE — finding patterns…"),
        (88,  "📊 VISUALIZE — generating charts…"),
        (100, "📝 REPORT — writing summary…"),
    ]

    for pct, msg in steps:
        progress_bar.progress(pct, text=msg)
        time.sleep(0.18)

    t0 = time.time()
    result = run_analysis(df_input, question)
    elapsed = time.time() - t0

    progress_bar.empty()
    status_holder.empty()
    _analyzing_alert.empty()

    st.success(f"✅ Playbook complete in **{elapsed:.1f}s** · "
               f"{result['stats']['shape']['rows']:,} rows × "
               f"{result['stats']['shape']['cols']} columns | "
               f"Source: *{source_label}*")

    # Show Amplitude metadata banner when live data was used successfully
    if amp_status and amp_status.ok:
        st.info(
            f"📡 **Amplitude live data** — {amp_status.message} "
            f"| Events: {', '.join(amp_status.events[:6])}"
            + (" …" if len(amp_status.events) > 6 else ""),
            icon="📡",
        )
    elif fallback_used:
        st.warning(
            "⚠️ Amplitude returned no data — showing **sample 'events' dataset** as fallback.",
            icon="🔄",
        )

    # ─────────────────────────────────────────────────────────────────────────
    # QUICK METRIC STRIP
    # ─────────────────────────────────────────────────────────────────────────

    m1, m2, m3, m4 = st.columns(4)
    shape = result["stats"]["shape"]
    nulls = sum(result["stats"]["null_counts"].values())
    n_charts = len(result["chart_paths"])
    n_clean = len(result["cleaning_log"])

    m1.metric("📋 Rows", f"{shape['rows']:,}")
    m2.metric("📏 Columns", shape["cols"])
    m3.metric("🚿 Nulls left", nulls, delta=None if nulls == 0 else f"{nulls} remaining")
    m4.metric("📊 Charts", n_charts)

    # ─────────────────────────────────────────────────────────────────────────
    # TABS
    # ─────────────────────────────────────────────────────────────────────────

    tab_profile, tab_charts, tab_report, tab_raw = st.tabs(
        ["📋 Profile", "📊 Charts", "📝 Report", "🔧 Raw Stats"]
    )

    # ── TAB 1: PROFILE ────────────────────────────────────────────────────────
    with tab_profile:
        st.markdown("### Data Profile")

        with st.expander("🧹 Cleaning Log", expanded=False):
            for entry in result["cleaning_log"]:
                st.markdown(f"<div class='log-item'>✓ {entry}</div>",
                            unsafe_allow_html=True)

        st.markdown("---")

        profile = result["stats"]["profile"]
        cols_list = list(profile.keys())
        ncols = min(2, len(cols_list))
        grid = st.columns(ncols)

        for i, col_name in enumerate(cols_list):
            info = profile[col_name]
            with grid[i % ncols]:
                dtype_badge = {
                    "int": "🔢", "float": "🔢", "object": "🔤",
                    "bool": "☑️", "datetime": "📅",
                }.get(info["dtype"].split("[")[0].split("6")[0], "❓")

                st.markdown(f"""
                <div class='analyst-card'>
                    <strong>{dtype_badge} {col_name}</strong>
                    <span style='font-size:0.75rem;color:#888;margin-left:0.5rem;'>
                        {info['dtype']}
                    </span><br>
                    <span class='metric-pill'>{info['n_unique']:,} unique</span>
                    <span class='metric-pill'>{info['null_count']} nulls</span>
                """, unsafe_allow_html=True)

                if "mean" in info:
                    st.markdown(f"""
                        <span class='metric-pill'>μ {info['mean']:,}</span>
                        <span class='metric-pill'>med {info['median']:,}</span>
                        <span class='metric-pill'>σ {info['std']:,}</span>
                    """, unsafe_allow_html=True)
                    if info["n_outliers"] > 0:
                        st.markdown(
                            f"    <span class='metric-pill' style='background:#ffe0e0;"
                            f"color:#c00;border-color:#f00a;'>"
                            f"⚠ {info['n_outliers']} outliers ({info['outlier_pct']}%)"
                            f"</span>",
                            unsafe_allow_html=True,
                        )
                elif "top_values" in info:
                    top_str = " · ".join(
                        f"{k} ({v:,})" for k, v in list(info["top_values"].items())[:3]
                    )
                    st.caption(f"Top values: {top_str}")
                elif "range_days" in info:
                    st.caption(f"📅 {info['min_date'][:10]} → {info['max_date'][:10]} "
                               f"({info['range_days']} days)")

                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("#### 🗂️ Data Sample (first 5 rows)")
        sample_df = pd.DataFrame(result["stats"]["sample"])
        st.dataframe(sample_df, use_container_width=True)

    # ── TAB 2: CHARTS ─────────────────────────────────────────────────────────
    with tab_charts:
        st.markdown("### Generated Charts")

        chart_paths = result["chart_paths"]
        if not chart_paths:
            st.info("No charts generated — the dataset may have no plottable columns.")
        else:
            for idx in range(0, len(chart_paths), 2):
                cols = st.columns(2)
                for j, path in enumerate(chart_paths[idx: idx + 2]):
                    if os.path.exists(path):
                        img = Image.open(path)
                        with cols[j]:
                            st.image(img, use_container_width=True)
                            with open(path, "rb") as f:
                                st.download_button(
                                    label=f"⬇ Download {os.path.basename(path)}",
                                    data=f,
                                    file_name=os.path.basename(path),
                                    mime="image/png",
                                    key=f"dl_{idx}_{j}",
                                )

    # ── TAB 3: REPORT ─────────────────────────────────────────────────────────
    with tab_report:
        st.markdown("### Plain-Language Report")

        st.markdown(f"""
        <div class='analyst-card' style='border-left:4px solid #4361EE;'>
            <strong>❓ Question asked:</strong> {question}
        </div>
        """, unsafe_allow_html=True)

        st.markdown(result["summary"])
        st.divider()

        st.markdown("#### ⚠️ Caveats")
        for caveat in result["caveats"]:
            st.markdown(f"<div class='caveat-item'>⚠ {caveat}</div>",
                        unsafe_allow_html=True)

        st.divider()

        dl_col1, dl_col2 = st.columns(2)

        report_text = (
            f"Question: {question}\n\n"
            + result["summary"].replace("**", "").replace("###", "")
            + "\n\nCaveats:\n"
            + "\n".join(f"- {c}" for c in result["caveats"])
            + "\n\nCleaning Log:\n"
            + "\n".join(f"- {l}" for l in result["cleaning_log"])
        )
        with dl_col1:
            st.download_button(
                label="⬇ Download Report (.txt)",
                data=report_text,
                file_name="analyst_report.txt",
                mime="text/plain",
            )

        with dl_col2:
            with st.spinner("📄 Building PDF…"):
                pdf_path = export_report_pdf(result)
                with open(pdf_path, "rb") as pdf_file:
                    st.download_button(
                        label="📄 Download PDF Report",
                        data=pdf_file,
                        file_name="analyst_report.pdf",
                        mime="application/pdf",
                        type="primary",
                    )

    # ── TAB 4: RAW STATS ──────────────────────────────────────────────────────
    with tab_raw:
        st.markdown("### Raw Stats (JSON)")
        st.caption("Full output from `run_analysis()` — useful for debugging or downstream use.")
        st.json(result["stats"], expanded=False)

        st.markdown("#### Findings dict")
        st.json(result["stats"].get("findings", {}), expanded=False)
