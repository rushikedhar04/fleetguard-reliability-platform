"""
Phase 4: reliability statistics per component.

- failure_rate: failures per asset-year in service, per component
- MTBF: mean time between consecutive failures on the same asset, per component
- Weibull fit (shape k, scale lambda) on inter-failure intervals per component,
  via scipy.stats.weibull_min — characterizes early-life (k<1), random (k~1),
  or wear-out (k>1) failure patterns.

Only components with >= MIN_EVENTS_FOR_FIT reconciled events (data_quality_flag
in ('ok','unmapped_taxonomy') — i.e. excluding events with no real component
signal) are fit; components below the threshold get failure_rate only, since a
Weibull fit on a handful of points is not trustworthy.

Writes results to component_reliability_stats.
"""
import os

import numpy as np
import pandas as pd
from scipy import stats
from sqlalchemy import text

from db import get_engine

MIN_EVENTS_FOR_FIT = 20


def compute_stats(engine):
    events = pd.read_sql(
        text(
            """
            SELECT asset_id, event_date, component
            FROM fact_failure_events
            WHERE data_quality_flag IN ('ok', 'unmapped_taxonomy')
              AND component NOT LIKE 'Unclassified'
            """
        ),
        engine,
    )
    events["event_date"] = pd.to_datetime(events["event_date"])

    assets = pd.read_sql(text("SELECT asset_id, model FROM dim_asset"), engine)

    results = []
    for component, cdf in events.groupby("component"):
        n_events = len(cdf)
        n_assets_affected = cdf["asset_id"].nunique()

        # inter-failure intervals, computed per asset then pooled
        intervals = []
        for _, g in cdf.groupby("asset_id"):
            dates = g["event_date"].sort_values()
            if len(dates) > 1:
                intervals.extend(dates.diff().dropna().dt.days.tolist())

        mtbf_days = float(np.mean(intervals)) if intervals else None

        # failure rate: events per asset-year across the whole fleet exposure window
        exposure_days = (events["event_date"].max() - events["event_date"].min()).days or 1
        exposure_years = max(exposure_days / 365.25, 0.01)
        failure_rate_per_asset_year = n_events / (len(assets) * exposure_years)

        weibull_shape = weibull_scale = None
        if len(intervals) >= MIN_EVENTS_FOR_FIT:
            intervals_arr = np.array([i for i in intervals if i > 0])
            if len(intervals_arr) >= MIN_EVENTS_FOR_FIT:
                shape, loc, scale = stats.weibull_min.fit(intervals_arr, floc=0)
                weibull_shape, weibull_scale = float(shape), float(scale)

        results.append(
            {
                "component": component,
                "n_events": n_events,
                "n_assets_affected": n_assets_affected,
                "mtbf_days": mtbf_days,
                "failure_rate_per_asset_year": failure_rate_per_asset_year,
                "weibull_shape_k": weibull_shape,
                "weibull_scale_lambda_days": weibull_scale,
                "fit_eligible": len(intervals) >= MIN_EVENTS_FOR_FIT,
            }
        )

    return pd.DataFrame(results).sort_values("n_events", ascending=False)


def main():
    engine = get_engine()
    stats_df = compute_stats(engine)

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS component_reliability_stats"))
    stats_df.to_sql("component_reliability_stats", engine, if_exists="replace", index=False)

    print(stats_df.to_string(index=False))
    print(f"\nWrote {len(stats_df)} rows to component_reliability_stats")


if __name__ == "__main__":
    main()
