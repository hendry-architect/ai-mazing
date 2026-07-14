"""
analyst.py — Sharpened Data Analyst Engine
===========================================
Exposes three public functions:

    run_analysis(df_or_path, question) -> dict
    export_report_pdf(result, out_path=None) -> str
    analyze_with_code_execution(user_prompt, model) -> dict  ← feature-flagged

The function executes the full LOAD → CLEAN → PROFILE → ANALYZE →
VISUALIZE → REPORT playbook and returns a structured result dict:

    {
        "summary":      str,          # plain-language headline + narrative
        "stats":        dict,         # shape, dtypes, null counts, profiles
        "chart_paths":  list[str],    # absolute paths of saved PNG charts
        "cleaning_log": list[str],    # one entry per cleaning action taken
        "caveats":      list[str],    # data-quality / methodology warnings
    }

Import and call directly, or drive from the Streamlit front-end (app.py).
"""

from __future__ import annotations

import io
import os
import textwrap
import warnings
from pathlib import Path
from typing import Union

import matplotlib
matplotlib.use("Agg")                         # non-interactive backend for servers
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Output directory ─────────────────────────────────────────────────────────
_HERE        = Path(__file__).parent
OUTPUTS_DIR  = _HERE / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Colour palette ────────────────────────────────────────────────────────────
PALETTE = ["#4361EE", "#3A0CA3", "#7209B7", "#F72585",
           "#4CC9F0", "#4CAF50", "#FF9800", "#E91E63"]
BG      = "#f4f4f8"
DARK    = "#1a1a2e"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — LOAD
# ─────────────────────────────────────────────────────────────────────────────

def _read_pdf_tables(source) -> pd.DataFrame:
    """
    Extract tabular data from a PDF and return it as a single DataFrame.

    Uses pdfplumber to pull every table found across all pages. Tables that
    share the same header are stacked vertically. The first row of each table
    is treated as the header. Accepts a file path (str/Path) or a file-like
    object (e.g. a Streamlit UploadedFile).

    Raises a clear ValueError if pdfplumber is missing or no tables are found.
    """
    try:
        import pdfplumber  # noqa: PLC0415 — lazy import, optional dependency
    except ImportError as _e:
        raise ValueError(
            "PDF support requires the 'pdfplumber' package. "
            "Install it with: pip install pdfplumber"
        ) from _e

    # pdfplumber accepts a path or a file-like object directly.
    if hasattr(source, "seek"):
        try:
            source.seek(0)
        except Exception:
            pass

    frames: list[pd.DataFrame] = []
    with pdfplumber.open(source) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not table or len(table) < 2:
                    continue  # need at least a header + one data row
                header = [
                    (str(c).strip() if c is not None else f"col_{i}")
                    for i, c in enumerate(table[0])
                ]
                rows = table[1:]
                frames.append(pd.DataFrame(rows, columns=header))

    if not frames:
        raise ValueError(
            "No tables could be extracted from the PDF. "
            "The analyst works on tabular data — make sure the PDF "
            "contains at least one table."
        )

    # Stack tables that share an identical column signature; otherwise keep
    # the largest table so the pipeline always receives a coherent frame.
    from collections import Counter
    signatures = Counter(tuple(f.columns) for f in frames)
    best_sig, _ = signatures.most_common(1)[0]
    matching = [f for f in frames if tuple(f.columns) == best_sig]
    df = pd.concat(matching, ignore_index=True)

    # Best-effort numeric coercion: PDF cells arrive as strings.
    for col in df.columns:
        _coerced = pd.to_numeric(
            df[col].astype(str).str.replace(",", "", regex=False),
            errors="coerce",
        )
        if _coerced.notna().mean() >= 0.8:  # mostly numeric → convert
            df[col] = _coerced

    return df


def _load(df_or_path: Union[pd.DataFrame, str, Path, io.IOBase]) -> dict:
    """
    Accept a DataFrame, file path, or file-like object.
    Returns {'df': DataFrame, 'load_notes': list[str]}.
    """
    notes: list[str] = []

    if isinstance(df_or_path, pd.DataFrame):
        df = df_or_path.copy()
        notes.append("Source: in-memory DataFrame")

    elif isinstance(df_or_path, (str, Path)):
        path = Path(df_or_path)
        ext  = path.suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(path)
        elif ext in (".xls", ".xlsx"):
            df = pd.read_excel(path)
        elif ext == ".parquet":
            df = pd.read_parquet(path)
        elif ext == ".json":
            df = pd.read_json(path)
        elif ext == ".pdf":
            df = _read_pdf_tables(path)
        else:
            raise ValueError(f"Unsupported file type: {ext!r}")
        notes.append(f"Source: file — {path.name} ({ext})")

    else:
        # file-like (e.g. Streamlit UploadedFile)
        _name = str(getattr(df_or_path, "name", "")).lower()
        if _name.endswith(".pdf"):
            df = _read_pdf_tables(df_or_path)
            notes.append("Source: uploaded PDF file-like object (tables extracted)")
        else:
            df = pd.read_csv(df_or_path)
            notes.append("Source: uploaded file-like object")

    # Try to parse any column that looks like a date
    for col in df.columns:
        if df[col].dtype == object and "date" in col.lower():
            try:
                df[col] = pd.to_datetime(df[col], infer_datetime_format=True)
                notes.append(f"Auto-parsed '{col}' as datetime")
            except Exception:
                pass

    load_info = {
        "df":         df,
        "shape":      df.shape,
        "columns":    df.columns.tolist(),
        "dtypes":     df.dtypes.astype(str).to_dict(),
        "null_counts": df.isnull().sum().to_dict(),
        "sample":     df.head(5).to_dict(orient="records"),
        "load_notes": notes,
    }
    return load_info


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — CLEAN
# ─────────────────────────────────────────────────────────────────────────────

def _clean(df: pd.DataFrame) -> dict:
    """
    Fix nulls, duplicates, and type mismatches.
    Returns {'df': cleaned DataFrame, 'log': list[str]}.
    """
    log: list[str] = []
    original_len = len(df)

    # 1. Strip leading/trailing whitespace from string columns
    str_cols = df.select_dtypes(include="object").columns
    for col in str_cols:
        before = df[col].str.strip() if df[col].dtype == object else df[col]
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
    if len(str_cols):
        log.append(f"Stripped whitespace from {len(str_cols)} string column(s): {list(str_cols)}")

    # 2. Drop fully-empty columns
    empty_cols = [c for c in df.columns if df[c].isnull().all()]
    if empty_cols:
        df.drop(columns=empty_cols, inplace=True)
        log.append(f"Dropped {len(empty_cols)} fully-empty column(s): {empty_cols}")

    # 3. Remove exact duplicate rows
    dup_count = df.duplicated().sum()
    if dup_count:
        df.drop_duplicates(inplace=True)
        df.reset_index(drop=True, inplace=True)
        log.append(f"Dropped {dup_count:,} exact duplicate rows")

    # 4. For numeric columns: fill isolated nulls with column median
    # Exclude bool columns — median-imputing booleans is meaningless and
    # triggers numpy 2.x boolean-subtraction errors during quantile computation.
    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns
                if df[c].dtype != bool]
    for col in num_cols:
        n_null = df[col].isnull().sum()
        if 0 < n_null <= max(5, int(0.05 * len(df))):   # ≤5% missing → impute
            median = df[col].median()
            df[col].fillna(median, inplace=True)
            log.append(f"Imputed {n_null} missing value(s) in '{col}' with median ({median:.4g})")
        elif n_null > 0:
            log.append(f"Left {n_null:,} missing value(s) in '{col}' (>{5}% threshold — review manually)")

    # 5. For string columns: fill nulls with "(unknown)"
    for col in df.select_dtypes(include="object").columns:
        n_null = df[col].isnull().sum()
        if n_null:
            df[col].fillna("(unknown)", inplace=True)
            log.append(f"Filled {n_null} null(s) in '{col}' with '(unknown)'")

    net_removed = original_len - len(df)
    if net_removed:
        log.append(f"Net rows removed: {net_removed:,}  ({original_len:,} → {len(df):,})")
    else:
        log.append("No rows removed — data was already clean")

    return {"df": df, "log": log}


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — PROFILE
# ─────────────────────────────────────────────────────────────────────────────

def _profile(df: pd.DataFrame) -> dict:
    """
    Compute per-column summary stats and flag outliers (IQR method for numerics).
    Returns a profile dict keyed by column name.
    """
    profile: dict = {}

    for col in df.columns:
        col_info: dict = {"dtype": str(df[col].dtype), "n_unique": df[col].nunique(),
                          "null_count": df[col].isnull().sum()}

        if pd.api.types.is_numeric_dtype(df[col]) and df[col].dtype != bool:
            desc = df[col].describe()
            q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
            iqr    = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = df[(df[col] < lo) | (df[col] > hi)][col]
            col_info.update({
                "mean":       round(float(desc["mean"]), 4),
                "median":     round(float(desc["50%"]),  4),
                "std":        round(float(desc["std"]),  4),
                "min":        round(float(desc["min"]),  4),
                "max":        round(float(desc["max"]),  4),
                "q1":         round(float(q1), 4),
                "q3":         round(float(q3), 4),
                "n_outliers": int(len(outliers)),
                "outlier_pct": round(len(outliers) / len(df) * 100, 2),
            })

        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            col_info.update({
                "min_date": str(df[col].min()),
                "max_date": str(df[col].max()),
                "range_days": (df[col].max() - df[col].min()).days,
            })

        else:
            top5 = df[col].value_counts().head(5).to_dict()
            col_info.update({
                "top_values": {str(k): int(v) for k, v in top5.items()},
                "coverage_pct": round(df[col].value_counts().head(5).sum() / len(df) * 100, 1),
            })

        profile[col] = col_info

    return profile


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — ANALYZE
# ─────────────────────────────────────────────────────────────────────────────

def _analyze(df: pd.DataFrame, question: str) -> dict:
    """
    Route the question to the most appropriate analysis strategy.
    Detects intent from keywords and column types.
    Returns an 'analysis' dict with findings and intermediate tables.
    """
    q_lower   = question.lower()
    findings  = {}

    # ── Detect column roles ───────────────────────────────────────────────
    date_cols  = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    # Exclude bool columns from numeric paths — numpy 2.x dropped boolean subtraction
    num_cols   = [c for c in df.select_dtypes(include=[np.number]).columns
                  if df[c].dtype != bool]
    cat_cols   = df.select_dtypes(include="object").columns.tolist()

    # ── Always: overall descriptive stats for numeric columns ─────────────
    if num_cols:
        findings["numeric_summary"] = df[num_cols].describe().round(3).to_dict()

    # ── Top-N / volume / frequency queries ───────────────────────────────
    if any(kw in q_lower for kw in ["top", "most", "popular", "volume", "frequency",
                                     "count", "rank", "highest", "largest"]):
        for col in cat_cols:
            vc = df[col].value_counts().head(10)
            findings[f"top_values_{col}"] = vc.to_dict()

    # ── Trend / time-series queries ───────────────────────────────────────
    if date_cols and any(kw in q_lower for kw in ["trend", "over time", "daily",
                                                    "weekly", "monthly", "time"]):
        dcol = date_cols[0]
        if num_cols:
            daily = df.groupby(dcol)[num_cols].sum()
            findings["time_series"] = daily.tail(30).to_dict()
        elif cat_cols:
            daily_counts = df.groupby(dcol).size().rename("count")
            findings["daily_counts"] = daily_counts.tail(30).to_dict()

    # ── Distribution queries ───────────────────────────────────────────────
    if any(kw in q_lower for kw in ["distribution", "histogram", "spread", "range"]):
        for col in num_cols[:3]:
            hist_vals, hist_bins = np.histogram(df[col].dropna(), bins=20)
            findings[f"histogram_{col}"] = {
                "counts": hist_vals.tolist(),
                "bin_edges": [round(b, 4) for b in hist_bins.tolist()],
            }

    # ── Correlation queries ───────────────────────────────────────────────
    if any(kw in q_lower for kw in ["correlat", "relationship", "vs", "versus",
                                      "compare", "against"]):
        if len(num_cols) >= 2:
            corr = df[num_cols].corr().round(3)
            findings["correlation_matrix"] = corr.to_dict()

    # ── Segment / group queries ───────────────────────────────────────────
    if any(kw in q_lower for kw in ["segment", "group", "by", "breakdown", "category",
                                      "cohort", "split", "per"]):
        for cat in cat_cols[:2]:
            if num_cols:
                grouped = df.groupby(cat)[num_cols[0]].agg(["mean","sum","count"]).round(3)
                findings[f"group_by_{cat}"] = grouped.to_dict()
            else:
                findings[f"group_by_{cat}"] = df[cat].value_counts().head(10).to_dict()

    # ── Fallback: always include value counts for every categorical column ─
    if not findings:
        for col in cat_cols[:3]:
            findings[f"value_counts_{col}"] = df[col].value_counts().head(10).to_dict()
        if num_cols:
            findings["numeric_summary"] = df[num_cols].describe().round(3).to_dict()

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — VISUALIZE
# ─────────────────────────────────────────────────────────────────────────────

def _visualize(df: pd.DataFrame, question: str, run_id: str) -> list[str]:
    """
    Generate up to 3 charts tailored to the data and question.
    Saves PNGs to OUTPUTS_DIR and returns their file paths.
    """
    q_lower   = question.lower()
    chart_paths: list[str] = []

    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    # Exclude bool columns — numpy 2.x does not support boolean subtraction (quantile/hist)
    num_cols  = [c for c in df.select_dtypes(include=[np.number]).columns
                 if df[c].dtype != bool]
    cat_cols  = df.select_dtypes(include="object").columns.tolist()

    def _save(fig: plt.Figure, name: str) -> str:
        path = str(OUTPUTS_DIR / f"{run_id}_{name}.png")
        fig.savefig(path, dpi=140, bbox_inches="tight", facecolor=BG)
        plt.close(fig)
        return path

    # ── Chart A: Top-N bar chart (categorical column) ─────────────────────
    if cat_cols:
        best_cat = max(cat_cols, key=lambda c: df[c].nunique() if df[c].nunique() <= 30 else 0,
                       default=cat_cols[0])
        vc = df[best_cat].value_counts().head(10)

        fig, ax = plt.subplots(figsize=(10, 5), facecolor=BG)
        colors  = (PALETTE * 3)[:len(vc)]
        bars    = ax.barh(vc.index[::-1], vc.values[::-1], color=colors[::-1],
                          height=0.6, edgecolor="none")
        for bar, val in zip(bars, vc.values[::-1]):
            ax.text(bar.get_width() + vc.max() * 0.01,
                    bar.get_y() + bar.get_height() / 2,
                    f"{val:,}", va="center", ha="left", fontsize=9,
                    fontweight="bold", color=DARK)
        ax.set_title(f"Top Values — {best_cat}", fontsize=13, fontweight="bold",
                     color=DARK, pad=12)
        ax.set_xlabel("Count", fontsize=10, color="#555")
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.set_xlim(0, vc.max() * 1.18)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.xaxis.grid(True, linestyle="--", alpha=0.35, color="#ccc")
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=9)
        ax.set_facecolor(BG)
        chart_paths.append(_save(fig, "bar_top_values"))

    # ── Chart B: Time-series line chart ───────────────────────────────────
    if date_cols:
        dcol = date_cols[0]
        if num_cols:
            # Daily sum of first numeric col
            ts = df.groupby(dcol)[num_cols[0]].sum().rename("value")
        else:
            ts = df.groupby(dcol).size().rename("value")

        fig, ax = plt.subplots(figsize=(10, 4), facecolor=BG)
        ax.plot(ts.index, ts.values, color=PALETTE[0], linewidth=2.2, marker="o",
                markersize=4)
        ax.fill_between(ts.index, ts.values, alpha=0.12, color=PALETTE[0])
        ax.set_title(f"Daily Trend — {num_cols[0] if num_cols else 'Event Count'}",
                     fontsize=13, fontweight="bold", color=DARK, pad=12)
        ax.set_xlabel("Date", fontsize=10, color="#555")
        ax.set_ylabel("Value", fontsize=10, color="#555")
        ax.spines[["top", "right"]].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.35, color="#ccc")
        ax.tick_params(axis="x", rotation=30, labelsize=8)
        ax.set_facecolor(BG)
        chart_paths.append(_save(fig, "line_trend"))

    # ── Chart C: Numeric distribution histogram ───────────────────────────
    if num_cols:
        col = num_cols[0]
        fig, ax = plt.subplots(figsize=(8, 4), facecolor=BG)
        ax.hist(df[col].dropna(), bins=30, color=PALETTE[2], edgecolor="white",
                linewidth=0.5, alpha=0.85)
        ax.axvline(df[col].mean(),   color=PALETTE[3], linestyle="--",
                   linewidth=1.6, label=f"Mean  {df[col].mean():.2f}")
        ax.axvline(df[col].median(), color=PALETTE[0], linestyle=":",
                   linewidth=1.6, label=f"Median {df[col].median():.2f}")
        ax.set_title(f"Distribution — {col}", fontsize=13, fontweight="bold",
                     color=DARK, pad=12)
        ax.set_xlabel(col, fontsize=10, color="#555")
        ax.set_ylabel("Frequency", fontsize=10, color="#555")
        ax.spines[["top", "right"]].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.35, color="#ccc")
        ax.legend(fontsize=9)
        ax.set_facecolor(BG)
        chart_paths.append(_save(fig, "hist_distribution"))

    # ── Chart D: Correlation heatmap (if ≥2 numeric cols) ────────────────
    if len(num_cols) >= 2 and "correlat" in q_lower:
        corr = df[num_cols].corr()
        n    = len(num_cols)
        fig, ax = plt.subplots(figsize=(max(6, n), max(5, n - 1)), facecolor=BG)
        im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1, vmax=1, aspect="auto")
        ax.set_xticks(range(n)); ax.set_yticks(range(n))
        ax.set_xticklabels(num_cols, rotation=45, ha="right", fontsize=9)
        ax.set_yticklabels(num_cols, fontsize=9)
        for i in range(n):
            for j in range(n):
                ax.text(j, i, f"{corr.values[i,j]:.2f}", ha="center", va="center",
                        fontsize=8, color="white" if abs(corr.values[i,j]) > 0.5 else DARK)
        plt.colorbar(im, ax=ax, shrink=0.8)
        ax.set_title("Correlation Matrix", fontsize=13, fontweight="bold",
                     color=DARK, pad=12)
        ax.set_facecolor(BG)
        chart_paths.append(_save(fig, "heatmap_correlation"))

    return chart_paths


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — REPORT
# ─────────────────────────────────────────────────────────────────────────────

def _report(df: pd.DataFrame, question: str, profile: dict,
            findings: dict, cleaning_log: list[str]) -> tuple[str, list[str]]:
    """
    Produce a plain-language summary and a list of caveats.
    """
    n_rows, n_cols = df.shape
    null_total     = sum(df.isnull().sum())
    num_cols       = df.select_dtypes(include=[np.number]).columns.tolist()
    cat_cols       = df.select_dtypes(include="object").columns.tolist()

    # ── Headline: biggest finding from the data ───────────────────────────
    headline_parts: list[str] = []

    # Top categorical value
    for col in cat_cols[:1]:
        vc = df[col].value_counts()
        top_val = vc.index[0]
        top_pct = vc.iloc[0] / len(df) * 100
        headline_parts.append(
            f"**'{top_val}'** is the most frequent value in **{col}** "
            f"({vc.iloc[0]:,} occurrences, {top_pct:.1f}% of rows)."
        )

    # Numeric range
    for col in num_cols[:1]:
        mn, mx = df[col].min(), df[col].max()
        headline_parts.append(
            f"**{col}** ranges from {mn:,.2f} to {mx:,.2f} "
            f"(mean: {df[col].mean():,.2f}, median: {df[col].median():,.2f})."
        )

    headline = "  ".join(headline_parts) if headline_parts else \
        f"Dataset has {n_rows:,} rows and {n_cols} columns — see profile for details."

    # ── Supporting narrative ──────────────────────────────────────────────
    support_lines: list[str] = [
        f"- Dataset shape: **{n_rows:,} rows × {n_cols} columns**.",
        f"- Cleaning applied: {len(cleaning_log)} action(s). "
        f"Remaining nulls after cleaning: **{null_total}**.",
    ]

    if num_cols:
        outlier_info = [
            f"{col} ({profile[col]['n_outliers']} outliers)"
            for col in num_cols
            if profile.get(col, {}).get("n_outliers", 0) > 0
        ]
        if outlier_info:
            support_lines.append(f"- Outliers detected in: {', '.join(outlier_info)}.")
        else:
            support_lines.append("- No statistical outliers detected in numeric columns.")

    if "time_series" in findings or "daily_counts" in findings:
        support_lines.append("- Time-series trend chart generated — inspect for seasonality or spikes.")

    body = "\n".join(support_lines)

    # ── Caveats ───────────────────────────────────────────────────────────
    caveats: list[str] = []
    if n_rows < 100:
        caveats.append(f"Small sample ({n_rows} rows) — conclusions may not generalise.")
    if null_total > 0:
        caveats.append(f"{null_total} null value(s) remain after cleaning — review manually.")
    if num_cols and any(profile.get(c, {}).get("outlier_pct", 0) > 5 for c in num_cols):
        caveats.append("Some numeric columns have >5% outliers — verify they are real data, not errors.")
    caveats.append("Correlation does not imply causation.")
    caveats.append("Analysis is descriptive; statistical significance was not tested.")

    summary = f"### Headline\n{headline}\n\n### Supporting Facts\n{body}"
    return summary, caveats


# ─────────────────────────────────────────────────────────────────────────────
# SAMPLE DATASET GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

def generate_sample_dataset(name: str = "ecommerce") -> pd.DataFrame:
    """
    Return a realistic sample DataFrame.
    Options: 'ecommerce', 'events', 'sales', 'users'.
    """
    rng = np.random.default_rng(42)

    if name == "ecommerce":
        n = 2_000
        dates = pd.date_range("2025-01-01", periods=n, freq="h")
        return pd.DataFrame({
            "order_date":   dates,
            "product":      rng.choice(["Laptop","Phone","Tablet","Watch","Headphones",
                                        "Keyboard","Monitor","Camera"], n,
                                        p=[.15,.20,.12,.10,.18,.08,.10,.07]),
            "category":     rng.choice(["Electronics","Accessories","Wearables"], n,
                                        p=[.5,.3,.2]),
            "country":      rng.choice(["US","UK","DE","FR","JP","CA","AU"], n,
                                        p=[.35,.15,.12,.10,.08,.12,.08]),
            "quantity":     rng.integers(1, 6, n),
            "unit_price":   np.round(rng.uniform(29, 1499, n), 2),
            "revenue":      None,          # will be derived during analysis
            "rating":       np.round(rng.uniform(2.5, 5.0, n), 1),
        }).assign(revenue=lambda d: np.round(d["quantity"] * d["unit_price"], 2))

    elif name == "events":
        n = 10_000
        event_names = ["Page Viewed","Button Clicked","Session Started",
                        "Search Performed","Item Added to Cart","Purchase Completed"]
        weights     = [0.30, 0.22, 0.18, 0.13, 0.10, 0.07]
        dates = pd.date_range("2025-06-20", "2025-06-26", freq="min")[:n]
        return pd.DataFrame({
            "timestamp":  pd.to_datetime(rng.choice(dates.astype(np.int64), n)).floor("min"),
            "event_name": rng.choice(event_names, n, p=weights),
            "user_id":    [f"u{rng.integers(1,2001)}" for _ in range(n)],
            "platform":   rng.choice(["web","ios","android"], n, p=[.55,.25,.20]),
            "country":    rng.choice(["US","UK","DE","FR","CA"], n,
                                      p=[.40,.18,.14,.12,.16]),
        })

    elif name == "sales":
        n = 1_500
        dates = pd.date_range("2024-01-01", "2024-12-31", periods=n)
        return pd.DataFrame({
            "date":        dates,
            "rep":         rng.choice([f"Rep_{i}" for i in range(1,11)], n),
            "region":      rng.choice(["North","South","East","West"], n),
            "deal_value":  np.round(rng.lognormal(8, 1, n), 2),
            "won":         rng.choice([True, False], n, p=[.35,.65]),
            "days_to_close": rng.integers(7, 180, n),
        })

    elif name == "users":
        n = 3_000
        return pd.DataFrame({
            "signup_date":   pd.date_range("2024-01-01", periods=n, freq="6h"),
            "plan":          rng.choice(["free","starter","pro","enterprise"], n,
                                         p=[.50,.25,.15,.10]),
            "country":       rng.choice(["US","UK","IN","DE","BR","JP"], n,
                                         p=[.30,.12,.20,.10,.15,.13]),
            "age":           rng.integers(18, 65, n),
            "sessions_30d":  rng.integers(0, 120, n),
            "revenue_ltv":   np.round(rng.exponential(120, n), 2),
            "churned":       rng.choice([True, False], n, p=[.22,.78]),
        })

    else:
        raise ValueError(f"Unknown sample dataset: {name!r}. "
                         "Choose from: ecommerce, events, sales, users.")


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def run_analysis(
    df_or_path: Union[pd.DataFrame, str, Path, io.IOBase],
    question:   str = "What are the most important patterns in this data?",
    run_id:     str | None = None,
) -> dict:
    """
    Execute the full LOAD → CLEAN → PROFILE → ANALYZE → VISUALIZE → REPORT
    playbook on *df_or_path* guided by *question*.

    Parameters
    ----------
    df_or_path : DataFrame | str | Path | file-like
        The dataset to analyse.
    question : str
        Plain-language question to guide the analysis.
    run_id : str | None
        Optional identifier for output filenames (auto-generated if None).

    Returns
    -------
    dict with keys:
        summary      – str, plain-language headline + supporting facts
        stats        – dict, shape / dtypes / profiles per column
        chart_paths  – list[str], absolute paths of saved PNG charts
        cleaning_log – list[str], one entry per cleaning action
        caveats      – list[str], data-quality / methodology warnings
    """
    import uuid, time

    run_id = run_id or f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    # ── 1. LOAD ──────────────────────────────────────────────────────────────
    load_result = _load(df_or_path)
    df_raw      = load_result["df"]

    # ── 2. CLEAN ─────────────────────────────────────────────────────────────
    clean_result  = _clean(df_raw)
    df_clean      = clean_result["df"]
    cleaning_log  = load_result["load_notes"] + clean_result["log"]

    # ── 3. PROFILE ───────────────────────────────────────────────────────────
    profile = _profile(df_clean)

    # ── 4. ANALYZE ───────────────────────────────────────────────────────────
    findings = _analyze(df_clean, question)

    # ── 5. VISUALIZE ─────────────────────────────────────────────────────────
    chart_paths = _visualize(df_clean, question, run_id)

    # ── 6. REPORT ────────────────────────────────────────────────────────────
    summary, caveats = _report(df_clean, question, profile, findings, cleaning_log)

    # ── Assemble stats dict ───────────────────────────────────────────────────
    stats = {
        "shape":      {"rows": df_clean.shape[0], "cols": df_clean.shape[1]},
        "columns":    load_result["columns"],
        "dtypes":     load_result["dtypes"],
        "null_counts": {k: int(v) for k, v in df_clean.isnull().sum().items()},
        "profile":    profile,
        "findings":   findings,
        "sample":     df_clean.head(5).to_dict(orient="records"),
    }

    return {
        "summary":      summary,
        "stats":        stats,
        "chart_paths":  chart_paths,
        "cleaning_log": cleaning_log,
        "caveats":      caveats,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PDF EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def export_report_pdf(
    result:   dict,
    out_path: str | Path | None = None,
) -> str:
    """
    Render the dict returned by ``run_analysis()`` into a clean, multi-page PDF.

    Pages produced
    --------------
    1. Cover — title, timestamp, question, shape pill
    2. Headline & Report — markdown-stripped summary paragraphs
    3. Caveats — bullet list
    4. Stats table — per-column dtype / unique / null / key stats
    5. Cleaning log — bullet list
    6+. Charts — one chart per page, centred with a caption

    Parameters
    ----------
    result   : dict returned by run_analysis()
    out_path : destination path (str or Path).
               Defaults to OUTPUTS_DIR / "report_<timestamp>.pdf".

    Returns
    -------
    str — absolute path of the saved PDF.
    """
    from datetime import datetime

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        HRFlowable,
        Image as RLImage,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    # ── Output path ───────────────────────────────────────────────────────────
    if out_path is None:
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = OUTPUTS_DIR / f"report_{ts}.pdf"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Page geometry ─────────────────────────────────────────────────────────
    PAGE_W, PAGE_H = A4                        # 595 × 842 pt
    MARGIN         = 2.2 * cm
    CONTENT_W      = PAGE_W - 2 * MARGIN

    # ── Colour palette (ReportLab HexColor) ──────────────────────────────────
    C_BRAND   = colors.HexColor("#4361EE")     # indigo
    C_DARK    = colors.HexColor("#1a1a2e")     # near-black
    C_MID     = colors.HexColor("#555555")
    C_LIGHT   = colors.HexColor("#f4f4f8")     # page background tint
    C_WARN    = colors.HexColor("#FF9800")     # amber for caveats
    C_SUCCESS = colors.HexColor("#4CAF50")
    C_ROW_ODD = colors.HexColor("#EEF0FF")
    C_WHITE   = colors.white

    # ── Typography ────────────────────────────────────────────────────────────
    base   = getSampleStyleSheet()

    def _style(name, **kwargs) -> ParagraphStyle:
        """Helper: clone base['Normal'] and apply overrides."""
        return ParagraphStyle(name, parent=base["Normal"], **kwargs)

    S = {
        # Cover
        "cover_title": _style("cover_title", fontSize=28, leading=34,
                               textColor=C_DARK, alignment=TA_CENTER,
                               fontName="Helvetica-Bold", spaceAfter=8),
        "cover_sub":   _style("cover_sub",   fontSize=12, leading=16,
                               textColor=C_MID, alignment=TA_CENTER,
                               spaceAfter=4),
        "cover_pill":  _style("cover_pill",  fontSize=10, leading=13,
                               textColor=C_BRAND, alignment=TA_CENTER,
                               spaceAfter=4),
        # Body
        "section":     _style("section",     fontSize=14, leading=18,
                               textColor=C_BRAND, fontName="Helvetica-Bold",
                               spaceBefore=14, spaceAfter=6),
        "body":        _style("body",        fontSize=10, leading=15,
                               textColor=C_DARK, spaceAfter=4),
        "bullet":      _style("bullet",      fontSize=10, leading=15,
                               textColor=C_DARK, leftIndent=14,
                               bulletIndent=4,  spaceAfter=3),
        "caveat":      _style("caveat",      fontSize=10, leading=15,
                               textColor=colors.HexColor("#7B3F00"),
                               leftIndent=14, bulletIndent=4, spaceAfter=3),
        "caption":     _style("caption",     fontSize=9,  leading=12,
                               textColor=C_MID, alignment=TA_CENTER,
                               spaceAfter=6),
        "table_hdr":   _style("table_hdr",   fontSize=9,  leading=11,
                               textColor=C_WHITE, fontName="Helvetica-Bold",
                               alignment=TA_CENTER),
        "table_cell":  _style("table_cell",  fontSize=9,  leading=11,
                               textColor=C_DARK),
    }

    # ── Helper: strip markdown bold/header markers ─────────────────────────
    def _clean(text: str) -> str:
        import re
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)   # **bold**
        text = re.sub(r"#{1,4}\s*",    "",    text)     # ## headers
        text = text.strip()
        return text

    # ── Helper: HR divider ─────────────────────────────────────────────────
    def _hr(color=C_BRAND, thickness=0.5) -> HRFlowable:
        return HRFlowable(width="100%", thickness=thickness,
                          color=color, spaceAfter=8, spaceBefore=4)

    # ─────────────────────────────────────────────────────────────────────────
    # Build the story (list of Flowables)
    # ─────────────────────────────────────────────────────────────────────────
    story: list = []

    timestamp = datetime.now().strftime("%d %B %Y, %H:%M")
    shape      = result["stats"]["shape"]

    # ── PAGE 1: Cover ─────────────────────────────────────────────────────────
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("AI-mazing Data Analyst", S["cover_title"]))
    story.append(Paragraph("Automated Analysis Report", S["cover_sub"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(_hr(C_BRAND, thickness=1.5))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(f"Generated: {timestamp}", S["cover_pill"]))
    story.append(Paragraph(
        f"Dataset: {shape['rows']:,} rows × {shape['cols']} columns",
        S["cover_pill"],
    ))

    # Embed question if present in findings (passed via summary header)
    # Extract question line from cleaning_log or summary if available
    story.append(Spacer(1, 1.5 * cm))

    # Mini stats table on cover
    cover_data = [
        [Paragraph("Metric", S["table_hdr"]),
         Paragraph("Value",  S["table_hdr"])],
        ["Rows",    f"{shape['rows']:,}"],
        ["Columns", str(shape["cols"])],
        ["Nulls remaining",
         str(sum(result["stats"]["null_counts"].values()))],
        ["Charts generated", str(len(result["chart_paths"]))],
        ["Cleaning actions", str(len(result["cleaning_log"]))],
    ]
    cover_tbl = Table(cover_data, colWidths=[CONTENT_W * 0.45, CONTENT_W * 0.45])
    cover_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_BRAND),
        ("TEXTCOLOR",  (0, 0), (-1, 0), C_WHITE),
        ("BACKGROUND", (0, 1), (-1, -1), C_LIGHT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_ROW_ODD]),
        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 1), (-1, -1), 10),
        ("ALIGN",      (1, 1), (1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ROWHEIGHT",  (0, 0), (-1, -1), 22),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    story.append(cover_tbl)

    # ── PAGE 2: Headline & Report Summary ────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Headline Finding", S["section"]))
    story.append(_hr())

    for line in result["summary"].split("\n"):
        line = _clean(line).strip()
        if not line or line in ("Headline", "Supporting Facts"):
            continue
        # Bullet lines start with "- "
        if line.startswith("- "):
            story.append(Paragraph(
                f"\u2022  {line[2:]}", S["bullet"]
            ))
        else:
            story.append(Paragraph(line, S["body"]))
        story.append(Spacer(1, 0.1 * cm))

    # ── PAGE 3: Caveats ───────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Caveats & Methodology Notes", S["section"]))
    story.append(_hr(C_WARN))

    for caveat in result["caveats"]:
        story.append(Paragraph(f"\u26a0  {_clean(caveat)}", S["caveat"]))

    # ── PAGE 4: Stats Table ───────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Column Profile", S["section"]))
    story.append(_hr())

    # Build header + one row per column
    tbl_header = [
        Paragraph(h, S["table_hdr"])
        for h in ["Column", "dtype", "Unique", "Nulls", "Key Stats"]
    ]
    tbl_rows = [tbl_header]

    for col_name, info in result["stats"]["profile"].items():
        if "mean" in info:
            key_stats = (f"μ={info['mean']:,}  med={info['median']:,}  "
                         f"σ={info['std']:,}  "
                         f"outliers={info['n_outliers']}")
        elif "top_values" in info:
            top3 = list(info["top_values"].items())[:2]
            key_stats = "  |  ".join(f"{k} ({v})" for k, v in top3)
        elif "range_days" in info:
            key_stats = (f"{info['min_date'][:10]} → {info['max_date'][:10]} "
                         f"({info['range_days']} days)")
        else:
            key_stats = "—"

        tbl_rows.append([
            Paragraph(col_name,          S["table_cell"]),
            Paragraph(info["dtype"],     S["table_cell"]),
            Paragraph(str(info["n_unique"]),   S["table_cell"]),
            Paragraph(str(info["null_count"]), S["table_cell"]),
            Paragraph(key_stats,         S["table_cell"]),
        ])

    col_widths = [
        CONTENT_W * 0.18,
        CONTENT_W * 0.14,
        CONTENT_W * 0.10,
        CONTENT_W * 0.09,
        CONTENT_W * 0.49,
    ]
    stats_tbl = Table(tbl_rows, colWidths=col_widths, repeatRows=1)
    stats_tbl.setStyle(TableStyle([
        # Header
        ("BACKGROUND",    (0, 0), (-1, 0), C_BRAND),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_WHITE),
        # Alternating body rows
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_ROW_ODD]),
        # Typography
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ROWHEIGHT",     (0, 0), (-1, -1), 18),
        # Grid
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.8, C_BRAND),
    ]))
    story.append(stats_tbl)

    # ── PAGE 5: Cleaning Log ──────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Cleaning Log", S["section"]))
    story.append(_hr(C_SUCCESS))

    for entry in result["cleaning_log"]:
        story.append(Paragraph(f"\u2713  {_clean(entry)}", S["bullet"]))

    # ── PAGES 6+: Charts (one per page) ──────────────────────────────────────
    for i, chart_path in enumerate(result["chart_paths"]):
        chart_path = Path(chart_path)
        if not chart_path.exists():
            continue

        story.append(PageBreak())
        story.append(Paragraph(f"Chart {i + 1} of {len(result['chart_paths'])}",
                                S["section"]))
        story.append(_hr())
        story.append(Spacer(1, 0.3 * cm))

        # Scale image to fill content width while keeping aspect ratio
        from PIL import Image as PILImage
        with PILImage.open(chart_path) as pil_img:
            img_w_px, img_h_px = pil_img.size

        max_w  = CONTENT_W
        max_h  = PAGE_H - 6 * cm           # leave room for header + caption
        scale  = min(max_w / img_w_px, max_h / img_h_px)
        draw_w = img_w_px * scale
        draw_h = img_h_px * scale

        story.append(RLImage(str(chart_path), width=draw_w, height=draw_h))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(chart_path.stem.replace("_", " ").title(),
                                S["caption"]))

    # ─────────────────────────────────────────────────────────────────────────
    # Build PDF
    # ─────────────────────────────────────────────────────────────────────────
    def _page_footer(canvas, doc):
        """Draw a slim footer on every page."""
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(C_MID)
        canvas.drawString(
            MARGIN,
            0.8 * cm,
            f"AI-mazing Analyst  ·  Generated {timestamp}",
        )
        canvas.drawRightString(
            PAGE_W - MARGIN,
            0.8 * cm,
            f"Page {doc.page}",
        )
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=1.6 * cm,         # room for footer
        title="AI-mazing Analyst Report",
        author="analyst.py",
    )
    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)

    return str(out_path)


# ═════════════════════════════════════════════════════════════════════════════
# FEATURE-FLAGGED: CODE-EXECUTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────
# This section adds an *optional* second analysis engine that delegates the
# entire LOAD→CLEAN→PROFILE→ANALYZE→VISUALIZE→REPORT playbook to a Claude
# model via Anthropic's server-side code_execution tool.
#
# ACTIVATION:  set env var ENABLE_CODE_EXEC=1  (see .env.example)
# API KEY:     set ANTHROPIC_API_KEY via env var or st.secrets
# COST NOTE:   ~$0.44 / ~80 s per run on claude-fable-5
#
# The local pipeline (run_analysis / export_report_pdf) is entirely unchanged.
# ═════════════════════════════════════════════════════════════════════════════

# ── Playbook system prompt sent to the model ──────────────────────────────────
PLAYBOOK: str = """
You are a sharpened Data Analyst. For every task, use the code_execution tool to
run all computation. Follow these six steps IN ORDER and show your work at each step.

STEP 1 — LOAD
• Read the dataset with pandas (CSV / DataFrame passed as a variable or path).
• Print: shape (rows × cols), column names, dtypes, null counts per column,
  and a 5-row sample with df.head(5).
• Auto-parse any column whose name contains 'date' to datetime.

STEP 2 — CLEAN
• Strip whitespace from all string columns.
• Drop columns that are 100 % null.
• Drop exact duplicate rows and print the count removed.
• For numeric columns (EXCLUDING bool dtype — numpy 2.x does not support boolean
  subtraction): impute isolated nulls (≤ 5 % of column) with the column median.
• Fill remaining string nulls with "(unknown)".
• Log every action taken with a "✓ " prefix.

STEP 3 — PROFILE
• For each numeric column (bool excluded): print mean, median, std, min, max,
  Q1, Q3, and IQR-based outlier count.
• For each datetime column: print min date, max date, and span in days.
• For each categorical / string column: print top-5 value counts and coverage %.
• Include all concrete numbers — no vague statements.

STEP 4 — ANALYZE
• Route to the strategy that best fits the user's question:
  - Top-N / volume   → value_counts(), groupby sum, sort descending
  - Trend over time  → groupby date then plot
  - Distribution     → histogram + mean/median lines
  - Correlation      → corr() heatmap (numeric cols only, bool excluded)
  - Segment/cohort   → groupby + agg
• Show intermediate DataFrames and concrete numbers at every step.

STEP 5 — VISUALIZE
• Generate at least one chart that directly answers the question.
• Use matplotlib with Agg backend; set a clear title and labelled axes.
• Save every chart to /tmp/ with a descriptive filename, e.g.:
    plt.savefig('/tmp/top_events_bar.png', dpi=140, bbox_inches='tight')
• Print the saved path for each file so the caller can collect it.

STEP 6 — REPORT
• Write a plain-language Markdown report with:
    ### Headline finding  (one bold sentence with the key number)
    ### Supporting facts  (2-3 bullet points with concrete values)
    ### Caveats           (sample size, missing data, correlation ≠ causation)
• Do NOT hedge without data — back every claim with a number from the analysis.
""".strip()


# ── Anthropic API key resolver ────────────────────────────────────────────────

def _get_anthropic_key() -> str:
    """
    Resolve the Anthropic API key using the same two-layer lookup as
    amplitude_source._get_secret():

      1. st.secrets["ANTHROPIC_API_KEY"]  (Streamlit Cloud / secrets.toml)
      2. os.environ["ANTHROPIC_API_KEY"]  (shell export / Render env panel)

    Returns an empty string — never raises — if neither source has the key.
    """
    # Layer 1: Streamlit secrets (no-op outside Streamlit context)
    try:
        import streamlit as st  # noqa: PLC0415
        val = st.secrets.get("ANTHROPIC_API_KEY", "")
        if val:
            return str(val).strip()
    except Exception:
        pass
    # Layer 2: environment variable
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


# ── Main feature-flagged function ─────────────────────────────────────────────

def analyze_with_code_execution(
    user_prompt: str,
    model: str = "claude-fable-5",
) -> dict:
    """
    Run the LOAD→CLEAN→PROFILE→ANALYZE→VISUALIZE→REPORT playbook by streaming
    a request to Anthropic with the server-side code_execution tool.

    Parameters
    ----------
    user_prompt : str
        The full prompt sent to the model — typically the user's question plus
        a serialised snapshot of the DataFrame (e.g. df.to_csv()).
    model : str
        Anthropic model ID.  Defaults to 'claude-fable-5'.

    Returns
    -------
    dict with keys:
        "report"  str            — accumulated markdown text from the model
        "files"   list[dict]     — collected output files, each:
                                     {"name": str, "mime_type": str,
                                      "data": bytes}
        "usage"   dict           — token counts from the final message
                                     {"input_tokens": int,
                                      "output_tokens": int}

    Error handling
    --------------
    If ANTHROPIC_API_KEY is absent, or if *anthropic* is not installed, or if
    any network/API error occurs, the function returns a result dict with
    "report" set to a descriptive error message and empty "files" / "usage" —
    it NEVER raises.

    Cost / latency note
    -------------------
    A typical run costs ~$0.44 and takes ~80 seconds.
    Gate calls behind  os.environ.get("ENABLE_CODE_EXEC") == "1".
    """

    _EMPTY = {"report": "", "files": [], "usage": {}}

    # ── Guard: check feature flag (belt-and-suspenders; caller should also check) ──
    if os.environ.get("ENABLE_CODE_EXEC") != "1":
        return {
            **_EMPTY,
            "report": (
                "⚠️ Code-execution engine is disabled.\n\n"
                "Set `ENABLE_CODE_EXEC=1` as an environment variable to enable it."
            ),
        }

    # ── Guard: API key ────────────────────────────────────────────────────────
    api_key = _get_anthropic_key()
    if not api_key:
        return {
            **_EMPTY,
            "report": (
                "⚠️ `ANTHROPIC_API_KEY` is not set.\n\n"
                "Add it via env var or Streamlit secrets (see .env.example)."
            ),
        }

    # ── Guard: anthropic package available ───────────────────────────────────
    try:
        import anthropic  # noqa: PLC0415  (lazy import — optional dependency)
    except ImportError:
        return {
            **_EMPTY,
            "report": (
                "⚠️ The `anthropic` package is not installed.\n\n"
                "Run `pip install anthropic` or add it to requirements.txt."
            ),
        }

    # ── Build client and stream ───────────────────────────────────────────────
    client = anthropic.Anthropic(api_key=api_key)

    report_parts: list[str] = []
    files:        list[dict] = []
    usage:        dict       = {}

    try:
        with client.messages.stream(
            model=model,
            max_tokens=4096,
            system=PLAYBOOK,
            tools=[{
                "type": "code_execution_20250522",
                "name": "code_execution",
            }],
            messages=[{
                "role":    "user",
                "content": user_prompt,
            }],
        ) as stream:

            # ── Accumulate text deltas ────────────────────────────────────────
            for event in stream:
                # RawContentBlockDeltaEvent carries text or JSON input chunks
                if (
                    hasattr(event, "type")
                    and event.type == "content_block_delta"
                    and hasattr(event, "delta")
                    and hasattr(event.delta, "text")
                ):
                    report_parts.append(event.delta.text)

            # ── Collect usage and output files from the final message ─────────
            final = stream.get_final_message()

            # Token usage
            if hasattr(final, "usage") and final.usage:
                usage = {
                    "input_tokens":  getattr(final.usage, "input_tokens",  0),
                    "output_tokens": getattr(final.usage, "output_tokens", 0),
                }

            # Files: walk every content block looking for image / document items
            # inside tool_result blocks (code execution output).
            for block in getattr(final, "content", []):
                block_type = getattr(block, "type", "")

                if block_type == "tool_result":
                    for item in getattr(block, "content", []) or []:
                        item_type = getattr(item, "type", "")

                        if item_type == "image":
                            # item.source has {type, media_type, data (base64 str)}
                            src = getattr(item, "source", None)
                            if src:
                                import base64  # noqa: PLC0415
                                raw = getattr(src, "data", "") or ""
                                files.append({
                                    "name":      "output_image.png",
                                    "mime_type": getattr(src, "media_type",
                                                         "image/png"),
                                    "data":      base64.b64decode(raw),
                                })

                        elif item_type == "document":
                            # Some models return CSVs / text files as documents
                            src = getattr(item, "source", None)
                            if src:
                                import base64  # noqa: PLC0415
                                raw = getattr(src, "data", "") or ""
                                files.append({
                                    "name":      getattr(item, "title",
                                                         "output.csv"),
                                    "mime_type": getattr(src, "media_type",
                                                         "text/csv"),
                                    "data":      base64.b64decode(raw),
                                })

    except Exception as exc:  # noqa: BLE001
        # Return a descriptive error; never propagate
        return {
            "report": (
                f"⚠️ Code-execution API error: {type(exc).__name__}: {exc}\n\n"
                "Check your ANTHROPIC_API_KEY, network, and model name."
            ),
            "files": [],
            "usage": usage,
        }

    return {
        "report": "".join(report_parts),
        "files":  files,
        "usage":  usage,
    }
"""
analyst.py — Sharpened Data Analyst Engine
===========================================
Exposes three public functions:

    run_analysis(df_or_path, question) -> dict
    export_report_pdf(result, out_path=None) -> str
    analyze_with_code_execution(user_prompt, model) -> dict  ← feature-flagged

The function executes the full LOAD → CLEAN → PROFILE → ANALYZE →
VISUALIZE → REPORT playbook and returns a structured result dict:

    {
        "summary":      str,          # plain-language headline + narrative
        "stats":        dict,         # shape, dtypes, null counts, profiles
        "chart_paths":  list[str],    # absolute paths of saved PNG charts
        "cleaning_log": list[str],    # one entry per cleaning action taken
        "caveats":      list[str],    # data-quality / methodology warnings
    }

Import and call directly, or drive from the Streamlit front-end (app.py).
"""

from __future__ import annotations

import io
import os
import textwrap
import warnings
from pathlib import Path
from typing import Union

import matplotlib
matplotlib.use("Agg")                         # non-interactive backend for servers
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ── Output directory ─────────────────────────────────────────────────────────
_HERE        = Path(__file__).parent
OUTPUTS_DIR  = _HERE / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Colour palette ────────────────────────────────────────────────────────────
PALETTE = ["#4361EE", "#3A0CA3", "#7209B7", "#F72585",
           "#4CC9F0", "#4CAF50", "#FF9800", "#E91E63"]
BG      = "#f4f4f8"
DARK    = "#1a1a2e"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — LOAD
# ─────────────────────────────────────────────────────────────────────────────

def _load(df_or_path: Union[pd.DataFrame, str, Path, io.IOBase]) -> dict:
    """
    Accept a DataFrame, file path, or file-like object.
    Returns {'df': DataFrame, 'load_notes': list[str]}.
    """
    notes: list[str] = []

    if isinstance(df_or_path, pd.DataFrame):
        df = df_or_path.copy()
        notes.append("Source: in-memory DataFrame")

    elif isinstance(df_or_path, (str, Path)):
        path = Path(df_or_path)
        ext  = path.suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(path)
        elif ext in (".xls", ".xlsx"):
            df = pd.read_excel(path)
        elif ext == ".parquet":
            df = pd.read_parquet(path)
        elif ext == ".json":
            df = pd.read_json(path)
        else:
            raise ValueError(f"Unsupported file type: {ext!r}")
        notes.append(f"Source: file — {path.name} ({ext})")

    else:
        # file-like (e.g. Streamlit UploadedFile)
        df = pd.read_csv(df_or_path)
        notes.append("Source: uploaded file-like object")

    # Try to parse any column that looks like a date
    for col in df.columns:
        if df[col].dtype == object and "date" in col.lower():
            try:
                df[col] = pd.to_datetime(df[col], infer_datetime_format=True)
                notes.append(f"Auto-parsed '{col}' as datetime")
            except Exception:
                pass

    load_info = {
        "df":         df,
        "shape":      df.shape,
        "columns":    df.columns.tolist(),
        "dtypes":     df.dtypes.astype(str).to_dict(),
        "null_counts": df.isnull().sum().to_dict(),
        "sample":     df.head(5).to_dict(orient="records"),
        "load_notes": notes,
    }
    return load_info


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — CLEAN
# ─────────────────────────────────────────────────────────────────────────────

def _clean(df: pd.DataFrame) -> dict:
    """
    Fix nulls, duplicates, and type mismatches.
    Returns {'df': cleaned DataFrame, 'log': list[str]}.
    """
    log: list[str] = []
    original_len = len(df)

    # 1. Strip leading/trailing whitespace from string columns
    str_cols = df.select_dtypes(include="object").columns
    for col in str_cols:
        before = df[col].str.strip() if df[col].dtype == object else df[col]
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)
    if len(str_cols):
        log.append(f"Stripped whitespace from {len(str_cols)} string column(s): {list(str_cols)}")

    # 2. Drop fully-empty columns
    empty_cols = [c for c in df.columns if df[c].isnull().all()]
    if empty_cols:
        df.drop(columns=empty_cols, inplace=True)
        log.append(f"Dropped {len(empty_cols)} fully-empty column(s): {empty_cols}")

    # 3. Remove exact duplicate rows
    dup_count = df.duplicated().sum()
    if dup_count:
        df.drop_duplicates(inplace=True)
        df.reset_index(drop=True, inplace=True)
        log.append(f"Dropped {dup_count:,} exact duplicate rows")

    # 4. For numeric columns: fill isolated nulls with column median
    # Exclude bool columns — median-imputing booleans is meaningless and
    # triggers numpy 2.x boolean-subtraction errors during quantile computation.
    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns
                if df[c].dtype != bool]
    for col in num_cols:
        n_null = df[col].isnull().sum()
        if 0 < n_null <= max(5, int(0.05 * len(df))):   # ≤5% missing → impute
            median = df[col].median()
            df[col].fillna(median, inplace=True)
            log.append(f"Imputed {n_null} missing value(s) in '{col}' with median ({median:.4g})")
        elif n_null > 0:
            log.append(f"Left {n_null:,} missing value(s) in '{col}' (>{5}% threshold — review manually)")

    # 5. For string columns: fill nulls with "(unknown)"
    for col in df.select_dtypes(include="object").columns:
        n_null = df[col].isnull().sum()
        if n_null:
            df[col].fillna("(unknown)", inplace=True)
            log.append(f"Filled {n_null} null(s) in '{col}' with '(unknown)'")

    net_removed = original_len - len(df)
    if net_removed:
        log.append(f"Net rows removed: {net_removed:,}  ({original_len:,} → {len(df):,})")
    else:
        log.append("No rows removed — data was already clean")

    return {"df": df, "log": log}


# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — PROFILE
# ─────────────────────────────────────────────────────────────────────────────

def _profile(df: pd.DataFrame) -> dict:
    """
    Compute per-column summary stats and flag outliers (IQR method for numerics).
    Returns a profile dict keyed by column name.
    """
    profile: dict = {}

    for col in df.columns:
        col_info: dict = {"dtype": str(df[col].dtype), "n_unique": df[col].nunique(),
                          "null_count": df[col].isnull().sum()}

        if pd.api.types.is_numeric_dtype(df[col]) and df[col].dtype != bool:
            desc = df[col].describe()
            q1, q3 = df[col].quantile(0.25), df[col].quantile(0.75)
            iqr    = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            outliers = df[(df[col] < lo) | (df[col] > hi)][col]
            col_info.update({
                "mean":       round(float(desc["mean"]), 4),
                "median":     round(float(desc["50%"]),  4),
                "std":        round(float(desc["std"]),  4),
                "min":        round(float(desc["min"]),  4),
                "max":        round(float(desc["max"]),  4),
                "q1":         round(float(q1), 4),
                "q3":         round(float(q3), 4),
                "n_outliers": int(len(outliers)),
                "outlier_pct": round(len(outliers) / len(df) * 100, 2),
            })

        elif pd.api.types.is_datetime64_any_dtype(df[col]):
            col_info.update({
                "min_date": str(df[col].min()),
                "max_date": str(df[col].max()),
                "range_days": (df[col].max() - df[col].min()).days,
            })

        else:
            top5 = df[col].value_counts().head(5).to_dict()
            col_info.update({
                "top_values": {str(k): int(v) for k, v in top5.items()},
                "coverage_pct": round(df[col].value_counts().head(5).sum() / len(df) * 100, 1),
            })

        profile[col] = col_info

    return profile


# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — ANALYZE
# ─────────────────────────────────────────────────────────────────────────────

def _analyze(df: pd.DataFrame, question: str) -> dict:
    """
    Route the question to the most appropriate analysis strategy.
    Detects intent from keywords and column types.
    Returns an 'analysis' dict with findings and intermediate tables.
    """
    q_lower   = question.lower()
    findings  = {}

    # ── Detect column roles ───────────────────────────────────────────────
    date_cols  = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    # Exclude bool columns from numeric paths — numpy 2.x dropped boolean subtraction
    num_cols   = [c for c in df.select_dtypes(include=[np.number]).columns
                  if df[c].dtype != bool]
    cat_cols   = df.select_dtypes(include="object").columns.tolist()

    # ── Always: overall descriptive stats for numeric columns ─────────────
    if num_cols:
        findings["numeric_summary"] = df[num_cols].describe().round(3).to_dict()

    # ── Top-N / volume / frequency queries ───────────────────────────────
    if any(kw in q_lower for kw in ["top", "most", "popular", "volume", "frequency",
                                     "count", "rank", "highest", "largest"]):
        for col in cat_cols:
            vc = df[col].value_counts().head(10)
            findings[f"top_values_{col}"] = vc.to_dict()

    # ── Trend / time-series queries ───────────────────────────────────────
    if date_cols and any(kw in q_lower for kw in ["trend", "over time", "daily",
                                                    "weekly", "monthly", "time"]):
        dcol = date_cols[0]
        if num_cols:
            daily = df.groupby(dcol)[num_cols].sum()
            findings["time_series"] = daily.tail(30).to_dict()
        elif cat_cols:
            daily_counts = df.groupby(dcol).size().rename("count")
            findings["daily_counts"] = daily_counts.tail(30).to_dict()

    # ── Distribution queries ───────────────────────────────────────────────
    if any(kw in q_lower for kw in ["distribution", "histogram", "spread", "range"]):
        for col in num_cols[:3]:
            hist_vals, hist_bins = np.histogram(df[col].dropna(), bins=20)
            findings[f"histogram_{col}"] = {
                "counts": hist_vals.tolist(),
                "bin_edges": [round(b, 4) for b in hist_bins.tolist()],
            }

    # ── Correlation queries ───────────────────────────────────────────────
    if any(kw in q_lower for kw in ["correlat", "relationship", "vs", "versus",
                                      "compare", "against"]):
        if len(num_cols) >= 2:
            corr = df[num_cols].corr().round(3)
            findings["correlation_matrix"] = corr.to_dict()

    # ── Segment / group queries ───────────────────────────────────────────
    if any(kw in q_lower for kw in ["segment", "group", "by", "breakdown", "category",
                                      "cohort", "split", "per"]):
        for cat in cat_cols[:2]:
            if num_cols:
                grouped = df.groupby(cat)[num_cols[0]].agg(["mean","sum","count"]).round(3)
                findings[f"group_by_{cat}"] = grouped.to_dict()
            else:
                findings[f"group_by_{cat}"] = df[cat].value_counts().head(10).to_dict()

    # ── Fallback: always include value counts for every categorical column ─
    if not findings:
        for col in cat_cols[:3]:
            findings[f"value_counts_{col}"] = df[col].value_counts().head(10).to_dict()
        if num_cols:
            findings["numeric_summary"] = df[num_cols].describe().round(3).to_dict()

    return findings


# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — VISUALIZE
# ─────────────────────────────────────────────────────────────────────────────

def _visualize(df: pd.DataFrame, question: str, run_id: str) -> list[str]:
    """
    Generate up to 3 charts tailored to the data and question.
    Saves PNGs to OUTPUTS_DIR and returns their file paths.
    """
    q_lower   = question.lower()
    chart_paths: list[str] = []

    date_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
    # Exclude bool columns — numpy 2.x does not support boolean subtraction (quantile/hist)
    num_cols  = [c for c in df.select_dtypes(include=[np.number]).columns
                 if df[c].dtype != bool]
    cat_cols  = df.select_dtypes(include="object").columns.tolist()

    def _save(fig: plt.Figure, name: str) -> str:
        path = str(OUTPUTS_DIR / f"{run_id}_{name}.png")
        fig.savefig(path, dpi=140, bbox_inches="tight", facecolor=BG)
        plt.close(fig)
        return path

    # ── Chart A: Top-N bar chart (categorical column) ─────────────────────
    if cat_cols:
        best_cat = max(cat_cols, key=lambda c: df[c].nunique() if df[c].nunique() <= 30 else 0,
                       default=cat_cols[0])
        vc = df[best_cat].value_counts().head(10)

        fig, ax = plt.subplots(figsize=(10, 5), facecolor=BG)
        colors  = (PALETTE * 3)[:len(vc)]
        bars    = ax.barh(vc.index[::-1], vc.values[::-1], color=colors[::-1],
                          height=0.6, edgecolor="none")
        for bar, val in zip(bars, vc.values[::-1]):
            ax.text(bar.get_width() + vc.max() * 0.01,
                    bar.get_y() + bar.get_height() / 2,
                    f"{val:,}", va="center", ha="left", fontsize=9,
                    fontweight="bold", color=DARK)
        ax.set_title(f"Top Values — {best_cat}", fontsize=13, fontweight="bold",
                     color=DARK, pad=12)
        ax.set_xlabel("Count", fontsize=10, color="#555")
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
        ax.set_xlim(0, vc.max() * 1.18)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.xaxis.grid(True, linestyle="--", alpha=0.35, color="#ccc")
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=9)
        ax.set_facecolor(BG)
        chart_paths.append(_save(fig, "bar_top_values"))

    # ── Chart B: Time-series line chart ───────────────────────────────────
    if date_cols:
        dcol = date_cols[0]
        if num_cols:
            # Daily sum of first numeric col
            ts = df.groupby(dcol)[num_cols[0]].sum().rename("value")
        else:
            ts = df.groupby(dcol).size().rename("value")

        fig, ax = plt.subplots(figsize=(10, 4), facecolor=BG)
        ax.plot(ts.index, ts.values, color=PALETTE[0], linewidth=2.2, marker="o",
                markersize=4)
        ax.fill_between(ts.index, ts.values, alpha=0.12, color=PALETTE[0])
        ax.set_title(f"Daily Trend — {num_cols[0] if num_cols else 'Event Count'}",
                     fontsize=13, fontweight="bold", color=DARK, pad=12)
        ax.set_xlabel("Date", fontsize=10, color="#555")
        ax.set_ylabel("Value", fontsize=10, color="#555")
        ax.spines[["top", "right"]].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.35, color="#ccc")
        ax.tick_params(axis="x", rotation=30, labelsize=8)
        ax.set_facecolor(BG)
        chart_paths.append(_save(fig, "line_trend"))

    # ── Chart C: Numeric distribution histogram ───────────────────────────
    if num_cols:
        col = num_cols[0]
        fig, ax = plt.subplots(figsize=(8, 4), facecolor=BG)
        ax.hist(df[col].dropna(), bins=30, color=PALETTE[2], edgecolor="white",
                linewidth=0.5, alpha=0.85)
        ax.axvline(df[col].mean(),   color=PALETTE[3], linestyle="--",
                   linewidth=1.6, label=f"Mean  {df[col].mean():.2f}")
        ax.axvline(df[col].median(), color=PALETTE[0], linestyle=":",
                   linewidth=1.6, label=f"Median {df[col].median():.2f}")
        ax.set_title(f"Distribution — {col}", fontsize=13, fontweight="bold",
                     color=DARK, pad=12)
        ax.set_xlabel(col, fontsize=10, color="#555")
        ax.set_ylabel("Frequency", fontsize=10, color="#555")
        ax.spines[["top", "right"]].set_visible(False)
        ax.yaxis.grid(True, linestyle="--", alpha=0.35, color="#ccc")
        ax.legend(fontsize=9)
        ax.set_facecolor(BG)
        chart_paths.append(_save(fig, "hist_distribution"))

    # ── Chart D: Correlation heatmap (if ≥2 numeric cols) ────────────────
    if len(num_cols) >= 2 and "correlat" in q_lower:
        corr = df[num_cols].corr()
        n    = len(num_cols)
        fig, ax = plt.subplots(figsize=(max(6, n), max(5, n - 1)), facecolor=BG)
        im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1, vmax=1, aspect="auto")
        ax.set_xticks(range(n)); ax.set_yticks(range(n))
        ax.set_xticklabels(num_cols, rotation=45, ha="right", fontsize=9)
        ax.set_yticklabels(num_cols, fontsize=9)
        for i in range(n):
            for j in range(n):
                ax.text(j, i, f"{corr.values[i,j]:.2f}", ha="center", va="center",
                        fontsize=8, color="white" if abs(corr.values[i,j]) > 0.5 else DARK)
        plt.colorbar(im, ax=ax, shrink=0.8)
        ax.set_title("Correlation Matrix", fontsize=13, fontweight="bold",
                     color=DARK, pad=12)
        ax.set_facecolor(BG)
        chart_paths.append(_save(fig, "heatmap_correlation"))

    return chart_paths


# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — REPORT
# ─────────────────────────────────────────────────────────────────────────────

def _report(df: pd.DataFrame, question: str, profile: dict,
            findings: dict, cleaning_log: list[str]) -> tuple[str, list[str]]:
    """
    Produce a plain-language summary and a list of caveats.
    """
    n_rows, n_cols = df.shape
    null_total     = sum(df.isnull().sum())
    num_cols       = df.select_dtypes(include=[np.number]).columns.tolist()
    cat_cols       = df.select_dtypes(include="object").columns.tolist()

    # ── Headline: biggest finding from the data ───────────────────────────
    headline_parts: list[str] = []

    # Top categorical value
    for col in cat_cols[:1]:
        vc = df[col].value_counts()
        top_val = vc.index[0]
        top_pct = vc.iloc[0] / len(df) * 100
        headline_parts.append(
            f"**'{top_val}'** is the most frequent value in **{col}** "
            f"({vc.iloc[0]:,} occurrences, {top_pct:.1f}% of rows)."
        )

    # Numeric range
    for col in num_cols[:1]:
        mn, mx = df[col].min(), df[col].max()
        headline_parts.append(
            f"**{col}** ranges from {mn:,.2f} to {mx:,.2f} "
            f"(mean: {df[col].mean():,.2f}, median: {df[col].median():,.2f})."
        )

    headline = "  ".join(headline_parts) if headline_parts else \
        f"Dataset has {n_rows:,} rows and {n_cols} columns — see profile for details."

    # ── Supporting narrative ──────────────────────────────────────────────
    support_lines: list[str] = [
        f"- Dataset shape: **{n_rows:,} rows × {n_cols} columns**.",
        f"- Cleaning applied: {len(cleaning_log)} action(s). "
        f"Remaining nulls after cleaning: **{null_total}**.",
    ]

    if num_cols:
        outlier_info = [
            f"{col} ({profile[col]['n_outliers']} outliers)"
            for col in num_cols
            if profile.get(col, {}).get("n_outliers", 0) > 0
        ]
        if outlier_info:
            support_lines.append(f"- Outliers detected in: {', '.join(outlier_info)}.")
        else:
            support_lines.append("- No statistical outliers detected in numeric columns.")

    if "time_series" in findings or "daily_counts" in findings:
        support_lines.append("- Time-series trend chart generated — inspect for seasonality or spikes.")

    body = "\n".join(support_lines)

    # ── Caveats ───────────────────────────────────────────────────────────
    caveats: list[str] = []
    if n_rows < 100:
        caveats.append(f"Small sample ({n_rows} rows) — conclusions may not generalise.")
    if null_total > 0:
        caveats.append(f"{null_total} null value(s) remain after cleaning — review manually.")
    if num_cols and any(profile.get(c, {}).get("outlier_pct", 0) > 5 for c in num_cols):
        caveats.append("Some numeric columns have >5% outliers — verify they are real data, not errors.")
    caveats.append("Correlation does not imply causation.")
    caveats.append("Analysis is descriptive; statistical significance was not tested.")

    summary = f"### Headline\n{headline}\n\n### Supporting Facts\n{body}"
    return summary, caveats


# ─────────────────────────────────────────────────────────────────────────────
# SAMPLE DATASET GENERATORS
# ─────────────────────────────────────────────────────────────────────────────

def generate_sample_dataset(name: str = "ecommerce") -> pd.DataFrame:
    """
    Return a realistic sample DataFrame.
    Options: 'ecommerce', 'events', 'sales', 'users'.
    """
    rng = np.random.default_rng(42)

    if name == "ecommerce":
        n = 2_000
        dates = pd.date_range("2025-01-01", periods=n, freq="h")
        return pd.DataFrame({
            "order_date":   dates,
            "product":      rng.choice(["Laptop","Phone","Tablet","Watch","Headphones",
                                        "Keyboard","Monitor","Camera"], n,
                                        p=[.15,.20,.12,.10,.18,.08,.10,.07]),
            "category":     rng.choice(["Electronics","Accessories","Wearables"], n,
                                        p=[.5,.3,.2]),
            "country":      rng.choice(["US","UK","DE","FR","JP","CA","AU"], n,
                                        p=[.35,.15,.12,.10,.08,.12,.08]),
            "quantity":     rng.integers(1, 6, n),
            "unit_price":   np.round(rng.uniform(29, 1499, n), 2),
            "revenue":      None,          # will be derived during analysis
            "rating":       np.round(rng.uniform(2.5, 5.0, n), 1),
        }).assign(revenue=lambda d: np.round(d["quantity"] * d["unit_price"], 2))

    elif name == "events":
        n = 10_000
        event_names = ["Page Viewed","Button Clicked","Session Started",
                        "Search Performed","Item Added to Cart","Purchase Completed"]
        weights     = [0.30, 0.22, 0.18, 0.13, 0.10, 0.07]
        dates = pd.date_range("2025-06-20", "2025-06-26", freq="min")[:n]
        return pd.DataFrame({
            "timestamp":  pd.to_datetime(rng.choice(dates.astype(np.int64), n)).floor("min"),
            "event_name": rng.choice(event_names, n, p=weights),
            "user_id":    [f"u{rng.integers(1,2001)}" for _ in range(n)],
            "platform":   rng.choice(["web","ios","android"], n, p=[.55,.25,.20]),
            "country":    rng.choice(["US","UK","DE","FR","CA"], n,
                                      p=[.40,.18,.14,.12,.16]),
        })

    elif name == "sales":
        n = 1_500
        dates = pd.date_range("2024-01-01", "2024-12-31", periods=n)
        return pd.DataFrame({
            "date":        dates,
            "rep":         rng.choice([f"Rep_{i}" for i in range(1,11)], n),
            "region":      rng.choice(["North","South","East","West"], n),
            "deal_value":  np.round(rng.lognormal(8, 1, n), 2),
            "won":         rng.choice([True, False], n, p=[.35,.65]),
            "days_to_close": rng.integers(7, 180, n),
        })

    elif name == "users":
        n = 3_000
        return pd.DataFrame({
            "signup_date":   pd.date_range("2024-01-01", periods=n, freq="6h"),
            "plan":          rng.choice(["free","starter","pro","enterprise"], n,
                                         p=[.50,.25,.15,.10]),
            "country":       rng.choice(["US","UK","IN","DE","BR","JP"], n,
                                         p=[.30,.12,.20,.10,.15,.13]),
            "age":           rng.integers(18, 65, n),
            "sessions_30d":  rng.integers(0, 120, n),
            "revenue_ltv":   np.round(rng.exponential(120, n), 2),
            "churned":       rng.choice([True, False], n, p=[.22,.78]),
        })

    else:
        raise ValueError(f"Unknown sample dataset: {name!r}. "
                         "Choose from: ecommerce, events, sales, users.")


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def run_analysis(
    df_or_path: Union[pd.DataFrame, str, Path, io.IOBase],
    question:   str = "What are the most important patterns in this data?",
    run_id:     str | None = None,
) -> dict:
    """
    Execute the full LOAD → CLEAN → PROFILE → ANALYZE → VISUALIZE → REPORT
    playbook on *df_or_path* guided by *question*.

    Parameters
    ----------
    df_or_path : DataFrame | str | Path | file-like
        The dataset to analyse.
    question : str
        Plain-language question to guide the analysis.
    run_id : str | None
        Optional identifier for output filenames (auto-generated if None).

    Returns
    -------
    dict with keys:
        summary      – str, plain-language headline + supporting facts
        stats        – dict, shape / dtypes / profiles per column
        chart_paths  – list[str], absolute paths of saved PNG charts
        cleaning_log – list[str], one entry per cleaning action
        caveats      – list[str], data-quality / methodology warnings
    """
    import uuid, time

    run_id = run_id or f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"

    # ── 1. LOAD ──────────────────────────────────────────────────────────────
    load_result = _load(df_or_path)
    df_raw      = load_result["df"]

    # ── 2. CLEAN ─────────────────────────────────────────────────────────────
    clean_result  = _clean(df_raw)
    df_clean      = clean_result["df"]
    cleaning_log  = load_result["load_notes"] + clean_result["log"]

    # ── 3. PROFILE ───────────────────────────────────────────────────────────
    profile = _profile(df_clean)

    # ── 4. ANALYZE ───────────────────────────────────────────────────────────
    findings = _analyze(df_clean, question)

    # ── 5. VISUALIZE ─────────────────────────────────────────────────────────
    chart_paths = _visualize(df_clean, question, run_id)

    # ── 6. REPORT ────────────────────────────────────────────────────────────
    summary, caveats = _report(df_clean, question, profile, findings, cleaning_log)

    # ── Assemble stats dict ───────────────────────────────────────────────────
    stats = {
        "shape":      {"rows": df_clean.shape[0], "cols": df_clean.shape[1]},
        "columns":    load_result["columns"],
        "dtypes":     load_result["dtypes"],
        "null_counts": {k: int(v) for k, v in df_clean.isnull().sum().items()},
        "profile":    profile,
        "findings":   findings,
        "sample":     df_clean.head(5).to_dict(orient="records"),
    }

    return {
        "summary":      summary,
        "stats":        stats,
        "chart_paths":  chart_paths,
        "cleaning_log": cleaning_log,
        "caveats":      caveats,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PDF EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def export_report_pdf(
    result:   dict,
    out_path: str | Path | None = None,
) -> str:
    """
    Render the dict returned by ``run_analysis()`` into a clean, multi-page PDF.

    Pages produced
    --------------
    1. Cover — title, timestamp, question, shape pill
    2. Headline & Report — markdown-stripped summary paragraphs
    3. Caveats — bullet list
    4. Stats table — per-column dtype / unique / null / key stats
    5. Cleaning log — bullet list
    6+. Charts — one chart per page, centred with a caption

    Parameters
    ----------
    result   : dict returned by run_analysis()
    out_path : destination path (str or Path).
               Defaults to OUTPUTS_DIR / "report_<timestamp>.pdf".

    Returns
    -------
    str — absolute path of the saved PDF.
    """
    from datetime import datetime

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (
        HRFlowable,
        Image as RLImage,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    # ── Output path ───────────────────────────────────────────────────────────
    if out_path is None:
        ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = OUTPUTS_DIR / f"report_{ts}.pdf"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # ── Page geometry ─────────────────────────────────────────────────────────
    PAGE_W, PAGE_H = A4                        # 595 × 842 pt
    MARGIN         = 2.2 * cm
    CONTENT_W      = PAGE_W - 2 * MARGIN

    # ── Colour palette (ReportLab HexColor) ──────────────────────────────────
    C_BRAND   = colors.HexColor("#4361EE")     # indigo
    C_DARK    = colors.HexColor("#1a1a2e")     # near-black
    C_MID     = colors.HexColor("#555555")
    C_LIGHT   = colors.HexColor("#f4f4f8")     # page background tint
    C_WARN    = colors.HexColor("#FF9800")     # amber for caveats
    C_SUCCESS = colors.HexColor("#4CAF50")
    C_ROW_ODD = colors.HexColor("#EEF0FF")
    C_WHITE   = colors.white

    # ── Typography ────────────────────────────────────────────────────────────
    base   = getSampleStyleSheet()

    def _style(name, **kwargs) -> ParagraphStyle:
        """Helper: clone base['Normal'] and apply overrides."""
        return ParagraphStyle(name, parent=base["Normal"], **kwargs)

    S = {
        # Cover
        "cover_title": _style("cover_title", fontSize=28, leading=34,
                               textColor=C_DARK, alignment=TA_CENTER,
                               fontName="Helvetica-Bold", spaceAfter=8),
        "cover_sub":   _style("cover_sub",   fontSize=12, leading=16,
                               textColor=C_MID, alignment=TA_CENTER,
                               spaceAfter=4),
        "cover_pill":  _style("cover_pill",  fontSize=10, leading=13,
                               textColor=C_BRAND, alignment=TA_CENTER,
                               spaceAfter=4),
        # Body
        "section":     _style("section",     fontSize=14, leading=18,
                               textColor=C_BRAND, fontName="Helvetica-Bold",
                               spaceBefore=14, spaceAfter=6),
        "body":        _style("body",        fontSize=10, leading=15,
                               textColor=C_DARK, spaceAfter=4),
        "bullet":      _style("bullet",      fontSize=10, leading=15,
                               textColor=C_DARK, leftIndent=14,
                               bulletIndent=4,  spaceAfter=3),
        "caveat":      _style("caveat",      fontSize=10, leading=15,
                               textColor=colors.HexColor("#7B3F00"),
                               leftIndent=14, bulletIndent=4, spaceAfter=3),
        "caption":     _style("caption",     fontSize=9,  leading=12,
                               textColor=C_MID, alignment=TA_CENTER,
                               spaceAfter=6),
        "table_hdr":   _style("table_hdr",   fontSize=9,  leading=11,
                               textColor=C_WHITE, fontName="Helvetica-Bold",
                               alignment=TA_CENTER),
        "table_cell":  _style("table_cell",  fontSize=9,  leading=11,
                               textColor=C_DARK),
    }

    # ── Helper: strip markdown bold/header markers ─────────────────────────
    def _clean(text: str) -> str:
        import re
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)   # **bold**
        text = re.sub(r"#{1,4}\s*",    "",    text)     # ## headers
        text = text.strip()
        return text

    # ── Helper: HR divider ─────────────────────────────────────────────────
    def _hr(color=C_BRAND, thickness=0.5) -> HRFlowable:
        return HRFlowable(width="100%", thickness=thickness,
                          color=color, spaceAfter=8, spaceBefore=4)

    # ─────────────────────────────────────────────────────────────────────────
    # Build the story (list of Flowables)
    # ─────────────────────────────────────────────────────────────────────────
    story: list = []

    timestamp = datetime.now().strftime("%d %B %Y, %H:%M")
    shape      = result["stats"]["shape"]

    # ── PAGE 1: Cover ─────────────────────────────────────────────────────────
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("AI-mazing Data Analyst", S["cover_title"]))
    story.append(Paragraph("Automated Analysis Report", S["cover_sub"]))
    story.append(Spacer(1, 0.4 * cm))
    story.append(_hr(C_BRAND, thickness=1.5))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(f"Generated: {timestamp}", S["cover_pill"]))
    story.append(Paragraph(
        f"Dataset: {shape['rows']:,} rows × {shape['cols']} columns",
        S["cover_pill"],
    ))

    # Embed question if present in findings (passed via summary header)
    # Extract question line from cleaning_log or summary if available
    story.append(Spacer(1, 1.5 * cm))

    # Mini stats table on cover
    cover_data = [
        [Paragraph("Metric", S["table_hdr"]),
         Paragraph("Value",  S["table_hdr"])],
        ["Rows",    f"{shape['rows']:,}"],
        ["Columns", str(shape["cols"])],
        ["Nulls remaining",
         str(sum(result["stats"]["null_counts"].values()))],
        ["Charts generated", str(len(result["chart_paths"]))],
        ["Cleaning actions", str(len(result["cleaning_log"]))],
    ]
    cover_tbl = Table(cover_data, colWidths=[CONTENT_W * 0.45, CONTENT_W * 0.45])
    cover_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C_BRAND),
        ("TEXTCOLOR",  (0, 0), (-1, 0), C_WHITE),
        ("BACKGROUND", (0, 1), (-1, -1), C_LIGHT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_ROW_ODD]),
        ("FONTNAME",   (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 1), (-1, -1), 10),
        ("ALIGN",      (1, 1), (1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ROWHEIGHT",  (0, 0), (-1, -1), 22),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.HexColor("#CCCCCC")),
        ("ROUNDEDCORNERS", [4, 4, 4, 4]),
    ]))
    story.append(cover_tbl)

    # ── PAGE 2: Headline & Report Summary ────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Headline Finding", S["section"]))
    story.append(_hr())

    for line in result["summary"].split("\n"):
        line = _clean(line).strip()
        if not line or line in ("Headline", "Supporting Facts"):
            continue
        # Bullet lines start with "- "
        if line.startswith("- "):
            story.append(Paragraph(
                f"\u2022  {line[2:]}", S["bullet"]
            ))
        else:
            story.append(Paragraph(line, S["body"]))
        story.append(Spacer(1, 0.1 * cm))

    # ── PAGE 3: Caveats ───────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Caveats & Methodology Notes", S["section"]))
    story.append(_hr(C_WARN))

    for caveat in result["caveats"]:
        story.append(Paragraph(f"\u26a0  {_clean(caveat)}", S["caveat"]))

    # ── PAGE 4: Stats Table ───────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Column Profile", S["section"]))
    story.append(_hr())

    # Build header + one row per column
    tbl_header = [
        Paragraph(h, S["table_hdr"])
        for h in ["Column", "dtype", "Unique", "Nulls", "Key Stats"]
    ]
    tbl_rows = [tbl_header]

    for col_name, info in result["stats"]["profile"].items():
        if "mean" in info:
            key_stats = (f"μ={info['mean']:,}  med={info['median']:,}  "
                         f"σ={info['std']:,}  "
                         f"outliers={info['n_outliers']}")
        elif "top_values" in info:
            top3 = list(info["top_values"].items())[:2]
            key_stats = "  |  ".join(f"{k} ({v})" for k, v in top3)
        elif "range_days" in info:
            key_stats = (f"{info['min_date'][:10]} → {info['max_date'][:10]} "
                         f"({info['range_days']} days)")
        else:
            key_stats = "—"

        tbl_rows.append([
            Paragraph(col_name,          S["table_cell"]),
            Paragraph(info["dtype"],     S["table_cell"]),
            Paragraph(str(info["n_unique"]),   S["table_cell"]),
            Paragraph(str(info["null_count"]), S["table_cell"]),
            Paragraph(key_stats,         S["table_cell"]),
        ])

    col_widths = [
        CONTENT_W * 0.18,
        CONTENT_W * 0.14,
        CONTENT_W * 0.10,
        CONTENT_W * 0.09,
        CONTENT_W * 0.49,
    ]
    stats_tbl = Table(tbl_rows, colWidths=col_widths, repeatRows=1)
    stats_tbl.setStyle(TableStyle([
        # Header
        ("BACKGROUND",    (0, 0), (-1, 0), C_BRAND),
        ("TEXTCOLOR",     (0, 0), (-1, 0), C_WHITE),
        # Alternating body rows
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_ROW_ODD]),
        # Typography
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ROWHEIGHT",     (0, 0), (-1, -1), 18),
        # Grid
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
        ("LINEBELOW",     (0, 0), (-1, 0),  0.8, C_BRAND),
    ]))
    story.append(stats_tbl)

    # ── PAGE 5: Cleaning Log ──────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Cleaning Log", S["section"]))
    story.append(_hr(C_SUCCESS))

    for entry in result["cleaning_log"]:
        story.append(Paragraph(f"\u2713  {_clean(entry)}", S["bullet"]))

    # ── PAGES 6+: Charts (one per page) ──────────────────────────────────────
    for i, chart_path in enumerate(result["chart_paths"]):
        chart_path = Path(chart_path)
        if not chart_path.exists():
            continue

        story.append(PageBreak())
        story.append(Paragraph(f"Chart {i + 1} of {len(result['chart_paths'])}",
                                S["section"]))
        story.append(_hr())
        story.append(Spacer(1, 0.3 * cm))

        # Scale image to fill content width while keeping aspect ratio
        from PIL import Image as PILImage
        with PILImage.open(chart_path) as pil_img:
            img_w_px, img_h_px = pil_img.size

        max_w  = CONTENT_W
        max_h  = PAGE_H - 6 * cm           # leave room for header + caption
        scale  = min(max_w / img_w_px, max_h / img_h_px)
        draw_w = img_w_px * scale
        draw_h = img_h_px * scale

        story.append(RLImage(str(chart_path), width=draw_w, height=draw_h))
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(chart_path.stem.replace("_", " ").title(),
                                S["caption"]))

    # ─────────────────────────────────────────────────────────────────────────
    # Build PDF
    # ─────────────────────────────────────────────────────────────────────────
    def _page_footer(canvas, doc):
        """Draw a slim footer on every page."""
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(C_MID)
        canvas.drawString(
            MARGIN,
            0.8 * cm,
            f"AI-mazing Analyst  ·  Generated {timestamp}",
        )
        canvas.drawRightString(
            PAGE_W - MARGIN,
            0.8 * cm,
            f"Page {doc.page}",
        )
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=1.6 * cm,         # room for footer
        title="AI-mazing Analyst Report",
        author="analyst.py",
    )
    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)

    return str(out_path)


# ═════════════════════════════════════════════════════════════════════════════
# FEATURE-FLAGGED: CODE-EXECUTION ENGINE
# ─────────────────────────────────────────────────────────────────────────────
# This section adds an *optional* second analysis engine that delegates the
# entire LOAD→CLEAN→PROFILE→ANALYZE→VISUALIZE→REPORT playbook to a Claude
# model via Anthropic's server-side code_execution tool.
#
# ACTIVATION:  set env var ENABLE_CODE_EXEC=1  (see .env.example)
# API KEY:     set ANTHROPIC_API_KEY via env var or st.secrets
# COST NOTE:   ~$0.44 / ~80 s per run on claude-fable-5
#
# The local pipeline (run_analysis / export_report_pdf) is entirely unchanged.
# ═════════════════════════════════════════════════════════════════════════════

# ── Playbook system prompt sent to the model ──────────────────────────────────
PLAYBOOK: str = """
You are a sharpened Data Analyst. For every task, use the code_execution tool to
run all computation. Follow these six steps IN ORDER and show your work at each step.

STEP 1 — LOAD
• Read the dataset with pandas (CSV / DataFrame passed as a variable or path).
• Print: shape (rows × cols), column names, dtypes, null counts per column,
  and a 5-row sample with df.head(5).
• Auto-parse any column whose name contains 'date' to datetime.

STEP 2 — CLEAN
• Strip whitespace from all string columns.
• Drop columns that are 100 % null.
• Drop exact duplicate rows and print the count removed.
• For numeric columns (EXCLUDING bool dtype — numpy 2.x does not support boolean
  subtraction): impute isolated nulls (≤ 5 % of column) with the column median.
• Fill remaining string nulls with "(unknown)".
• Log every action taken with a "✓ " prefix.

STEP 3 — PROFILE
• For each numeric column (bool excluded): print mean, median, std, min, max,
  Q1, Q3, and IQR-based outlier count.
• For each datetime column: print min date, max date, and span in days.
• For each categorical / string column: print top-5 value counts and coverage %.
• Include all concrete numbers — no vague statements.

STEP 4 — ANALYZE
• Route to the strategy that best fits the user's question:
  - Top-N / volume   → value_counts(), groupby sum, sort descending
  - Trend over time  → groupby date then plot
  - Distribution     → histogram + mean/median lines
  - Correlation      → corr() heatmap (numeric cols only, bool excluded)
  - Segment/cohort   → groupby + agg
• Show intermediate DataFrames and concrete numbers at every step.

STEP 5 — VISUALIZE
• Generate at least one chart that directly answers the question.
• Use matplotlib with Agg backend; set a clear title and labelled axes.
• Save every chart to /tmp/ with a descriptive filename, e.g.:
    plt.savefig('/tmp/top_events_bar.png', dpi=140, bbox_inches='tight')
• Print the saved path for each file so the caller can collect it.

STEP 6 — REPORT
• Write a plain-language Markdown report with:
    ### Headline finding  (one bold sentence with the key number)
    ### Supporting facts  (2-3 bullet points with concrete values)
    ### Caveats           (sample size, missing data, correlation ≠ causation)
• Do NOT hedge without data — back every claim with a number from the analysis.
""".strip()


# ── Anthropic API key resolver ────────────────────────────────────────────────

def _get_anthropic_key() -> str:
    """
    Resolve the Anthropic API key using the same two-layer lookup as
    amplitude_source._get_secret():

      1. st.secrets["ANTHROPIC_API_KEY"]  (Streamlit Cloud / secrets.toml)
      2. os.environ["ANTHROPIC_API_KEY"]  (shell export / Render env panel)

    Returns an empty string — never raises — if neither source has the key.
    """
    # Layer 1: Streamlit secrets (no-op outside Streamlit context)
    try:
        import streamlit as st  # noqa: PLC0415
        val = st.secrets.get("ANTHROPIC_API_KEY", "")
        if val:
            return str(val).strip()
    except Exception:
        pass
    # Layer 2: environment variable
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


# ── Main feature-flagged function ─────────────────────────────────────────────

def analyze_with_code_execution(
    user_prompt: str,
    model: str = "claude-fable-5",
) -> dict:
    """
    Run the LOAD→CLEAN→PROFILE→ANALYZE→VISUALIZE→REPORT playbook by streaming
    a request to Anthropic with the server-side code_execution tool.

    Parameters
    ----------
    user_prompt : str
        The full prompt sent to the model — typically the user's question plus
        a serialised snapshot of the DataFrame (e.g. df.to_csv()).
    model : str
        Anthropic model ID.  Defaults to 'claude-fable-5'.

    Returns
    -------
    dict with keys:
        "report"  str            — accumulated markdown text from the model
        "files"   list[dict]     — collected output files, each:
                                     {"name": str, "mime_type": str,
                                      "data": bytes}
        "usage"   dict           — token counts from the final message
                                     {"input_tokens": int,
                                      "output_tokens": int}

    Error handling
    --------------
    If ANTHROPIC_API_KEY is absent, or if *anthropic* is not installed, or if
    any network/API error occurs, the function returns a result dict with
    "report" set to a descriptive error message and empty "files" / "usage" —
    it NEVER raises.

    Cost / latency note
    -------------------
    A typical run costs ~$0.44 and takes ~80 seconds.
    Gate calls behind  os.environ.get("ENABLE_CODE_EXEC") == "1".
    """

    _EMPTY = {"report": "", "files": [], "usage": {}}

    # ── Guard: check feature flag (belt-and-suspenders; caller should also check) ──
    if os.environ.get("ENABLE_CODE_EXEC") != "1":
        return {
            **_EMPTY,
            "report": (
                "⚠️ Code-execution engine is disabled.\n\n"
                "Set `ENABLE_CODE_EXEC=1` as an environment variable to enable it."
            ),
        }

    # ── Guard: API key ────────────────────────────────────────────────────────
    api_key = _get_anthropic_key()
    if not api_key:
        return {
            **_EMPTY,
            "report": (
                "⚠️ `ANTHROPIC_API_KEY` is not set.\n\n"
                "Add it via env var or Streamlit secrets (see .env.example)."
            ),
        }

    # ── Guard: anthropic package available ───────────────────────────────────
    try:
        import anthropic  # noqa: PLC0415  (lazy import — optional dependency)
    except ImportError:
        return {
            **_EMPTY,
            "report": (
                "⚠️ The `anthropic` package is not installed.\n\n"
                "Run `pip install anthropic` or add it to requirements.txt."
            ),
        }

    # ── Build client and stream ───────────────────────────────────────────────
    client = anthropic.Anthropic(api_key=api_key)

    report_parts: list[str] = []
    files:        list[dict] = []
    usage:        dict       = {}

    try:
        with client.messages.stream(
            model=model,
            max_tokens=4096,
            system=PLAYBOOK,
            tools=[{
                "type": "code_execution_20250522",
                "name": "code_execution",
            }],
            messages=[{
                "role":    "user",
                "content": user_prompt,
            }],
        ) as stream:

            # ── Accumulate text deltas ────────────────────────────────────────
            for event in stream:
                # RawContentBlockDeltaEvent carries text or JSON input chunks
                if (
                    hasattr(event, "type")
                    and event.type == "content_block_delta"
                    and hasattr(event, "delta")
                    and hasattr(event.delta, "text")
                ):
                    report_parts.append(event.delta.text)

            # ── Collect usage and output files from the final message ─────────
            final = stream.get_final_message()

            # Token usage
            if hasattr(final, "usage") and final.usage:
                usage = {
                    "input_tokens":  getattr(final.usage, "input_tokens",  0),
                    "output_tokens": getattr(final.usage, "output_tokens", 0),
                }

            # Files: walk every content block looking for image / document items
            # inside tool_result blocks (code execution output).
            for block in getattr(final, "content", []):
                block_type = getattr(block, "type", "")

                if block_type == "tool_result":
                    for item in getattr(block, "content", []) or []:
                        item_type = getattr(item, "type", "")

                        if item_type == "image":
                            # item.source has {type, media_type, data (base64 str)}
                            src = getattr(item, "source", None)
                            if src:
                                import base64  # noqa: PLC0415
                                raw = getattr(src, "data", "") or ""
                                files.append({
                                    "name":      "output_image.png",
                                    "mime_type": getattr(src, "media_type",
                                                         "image/png"),
                                    "data":      base64.b64decode(raw),
                                })

                        elif item_type == "document":
                            # Some models return CSVs / text files as documents
                            src = getattr(item, "source", None)
                            if src:
                                import base64  # noqa: PLC0415
                                raw = getattr(src, "data", "") or ""
                                files.append({
                                    "name":      getattr(item, "title",
                                                         "output.csv"),
                                    "mime_type": getattr(src, "media_type",
                                                         "text/csv"),
                                    "data":      base64.b64decode(raw),
                                })

    except Exception as exc:  # noqa: BLE001
        # Return a descriptive error; never propagate
        return {
            "report": (
                f"⚠️ Code-execution API error: {type(exc).__name__}: {exc}\n\n"
                "Check your ANTHROPIC_API_KEY, network, and model name."
            ),
            "files": [],
            "usage": usage,
        }

    return {
        "report": "".join(report_parts),
        "files":  files,
        "usage":  usage,
    }
