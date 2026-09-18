import os
import sys

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from scipy import stats as sstats

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from db import get_engine  # noqa: E402

st.set_page_config(page_title="FleetGuard", layout="wide")

engine = get_engine()


@st.cache_data(ttl=300)
def load_table(query, params=None):
    return pd.read_sql(query, engine, params=params)


@st.cache_data(ttl=300)
def load_lineage_md():
    path = os.path.join(os.path.dirname(__file__), "..", "docs", "lineage.md")
    with open(path) as f:
        return f.read()


st.title("FleetGuard — Field Reliability & Data Quality Platform")
st.caption(
    "Integrated view across service tickets, telemetry, and warranty claims — "
    "every number here traces back to source. See the Lineage tab."
)

tab_overview, tab_component, tab_dq, tab_lineage = st.tabs(
    ["Overview", "Component Deep Dive", "Data Quality", "Lineage"]
)

# ---------------------------------------------------------------- Overview --
with tab_overview:
    events = load_table(
        "SELECT asset_id, event_date, component, data_quality_flag, source_systems_present "
        "FROM fact_failure_events"
    )
    events["event_date"] = pd.to_datetime(events["event_date"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reconciled failure events", f"{len(events):,}")
    c2.metric("Assets affected", f"{events['asset_id'].nunique():,}")
    c3.metric(
        "Events flagged by DQ",
        f"{(events['data_quality_flag'] != 'ok').sum():,}",
        help="orphan_claim, unmapped_taxonomy, or missing_component",
    )
    single_source = events["source_systems_present"].apply(lambda s: len(s) == 1)
    c4.metric("Single-source events", f"{single_source.sum():,}", help="Only one system had evidence")

    st.subheader("Top components by failure count")
    top_components = (
        events[events["component"] != "Unclassified"]
        .groupby("component")
        .size()
        .reset_index(name="failure_count")
        .sort_values("failure_count", ascending=False)
    )
    chart = (
        alt.Chart(top_components)
        .mark_bar(color="#3b6fd4")
        .encode(
            x=alt.X("failure_count:Q", title="Failure events"),
            y=alt.Y("component:N", sort="-x", title=None),
            tooltip=["component", "failure_count"],
        )
        .properties(height=320)
    )
    st.altair_chart(chart, use_container_width=True)

    st.subheader("Fleet-wide failure trend")
    monthly = (
        events.set_index("event_date")
        .resample("MS")
        .size()
        .reset_index(name="failure_count")
        .rename(columns={"event_date": "month"})
    )
    trend = (
        alt.Chart(monthly)
        .mark_line(point=True, color="#3b6fd4")
        .encode(x="month:T", y=alt.Y("failure_count:Q", title="Failure events / month"), tooltip=["month:T", "failure_count"])
        .properties(height=280)
    )
    st.altair_chart(trend, use_container_width=True)

# ------------------------------------------------------- Component Deep Dive --
with tab_component:
    rel = load_table("SELECT * FROM component_reliability_stats ORDER BY n_events DESC")
    components = rel["component"].tolist()
    selected = st.selectbox("Component", components)
    row = rel[rel["component"] == selected].iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Failure events", f"{int(row['n_events']):,}")
    c2.metric("Assets affected", f"{int(row['n_assets_affected']):,}")
    c3.metric("MTBF (days)", f"{row['mtbf_days']:.0f}" if pd.notna(row["mtbf_days"]) else "n/a")
    c4.metric("Failure rate / asset-year", f"{row['failure_rate_per_asset_year']:.3f}")

    events = load_table(
        "SELECT event_date FROM fact_failure_events WHERE component = %(c)s",
        params={"c": selected},
    )
    events["event_date"] = pd.to_datetime(events["event_date"])
    monthly = (
        events.set_index("event_date")
        .resample("MS")
        .size()
        .reset_index(name="failure_count")
        .rename(columns={"event_date": "month"})
    )
    st.subheader(f"{selected} — failure trend")
    st.altair_chart(
        alt.Chart(monthly)
        .mark_line(point=True, color="#d4703b")
        .encode(x="month:T", y="failure_count:Q", tooltip=["month:T", "failure_count"])
        .properties(height=260),
        use_container_width=True,
    )

    st.subheader(f"{selected} — Weibull survival curve")
    if row["fit_eligible"] and pd.notna(row["weibull_shape_k"]):
        k, lam = row["weibull_shape_k"], row["weibull_scale_lambda_days"]
        t = np.linspace(0, lam * 3, 200)
        survival = 1 - sstats.weibull_min.cdf(t, k, scale=lam)
        curve_df = pd.DataFrame({"days": t, "survival_probability": survival})
        pattern = "wear-out" if k > 1.1 else ("early-life" if k < 0.9 else "random / constant-rate")
        st.caption(f"Shape k = {k:.2f}, scale λ = {lam:.0f} days → failure pattern: **{pattern}**")
        st.altair_chart(
            alt.Chart(curve_df)
            .mark_line(color="#3bb273")
            .encode(x=alt.X("days:Q", title="Days since prior failure"), y=alt.Y("survival_probability:Q", scale=alt.Scale(domain=[0, 1])))
            .properties(height=260),
            use_container_width=True,
        )
    else:
        st.info("Not enough reconciled events for this component to fit a reliable Weibull curve.")

# --------------------------------------------------------------- Data Quality --
with tab_dq:
    st.subheader("Data quality check log")
    st.caption("Every pipeline run logs each check here — flagged rows are visible, never silently dropped.")

    log = load_table(
        "SELECT check_run_id, check_name, table_name, rows_checked, rows_flagged, run_at, sample_flagged "
        "FROM dq_check_log ORDER BY run_at DESC"
    )
    if log.empty:
        st.warning("No DQ runs logged yet — run scripts/dq_checks.py.")
    else:
        latest_run = log["check_run_id"].iloc[0]
        latest = log[log["check_run_id"] == latest_run].copy()
        latest["pct_flagged"] = (latest["rows_flagged"] / latest["rows_checked"] * 100).round(2)
        st.write(f"Latest run: `{latest_run}` at {latest['run_at'].iloc[0]}")

        st.dataframe(
            latest[["check_name", "table_name", "rows_checked", "rows_flagged", "pct_flagged"]],
            use_container_width=True,
            hide_index=True,
        )

        check_choice = st.selectbox("Inspect flagged rows for check", latest["check_name"].tolist())
        sample_json = latest[latest["check_name"] == check_choice]["sample_flagged"].iloc[0]
        import json

        sample = json.loads(sample_json) if isinstance(sample_json, str) else sample_json
        if sample:
            st.dataframe(pd.DataFrame(sample), use_container_width=True, hide_index=True)
        else:
            st.success("No flagged rows in the sample for this check.")

# ------------------------------------------------------------------ Lineage --
with tab_lineage:
    st.caption("Rendered from mappings.yml — the source-to-target spec maintained alongside the transform code.")
    st.markdown(load_lineage_md())
