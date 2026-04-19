from pathlib import Path

EMAIL = "nucleusshrestha6@gmail.com"
API_KEY = "ochrebird79"
STATE_CODE = "17"
PARAM_CODE = "44201"
START_YEAR = 2020
END_YEAR = 2025
OUTPUT_DIR = Path.cwd() / "air_quality_construction_outputs"

import sys
import warnings
from typing import Dict, Optional, Tuple

warnings.filterwarnings(
    "ignore",
    message="urllib3 v2 only supports OpenSSL 1.1.1+",
    category=Warning,
)

import matplotlib.pyplot as plt
import pandas as pd
import requests


API_URL = "https://aqs.epa.gov/data/api/dailyData/byState"
REQUEST_TIMEOUT = 60
REFRESH_API = False
FIGURE_OUTPUT_DIR = Path.cwd() / "outputs"
WITHOUT_MITIGATION_UPLIFT = 0.08
WITH_PLANNING_REDUCTION_FROM_BASELINE = 0.05

# 2025 baseline comes from a separate point-in-time export rather than the EPA AQS cache.
# The file covers January 1 – June 30, 2025 and is treated as partial-year data.
TABLE_EXPORT_2025_PATH = Path(__file__).parent.parent / "table_export-2 (1).csv"
SUPPLEMENT_2025_LABEL = "table_export-2 (1).csv"

# These assumptions are editable by design. Only baseline values come from measured data.
# The two scenario lines are simple decision-support models to show how construction choices
# could shift ozone pressure through equipment exhaust, diesel traffic, site activity,
# and other urban disturbance that can increase ozone-forming emissions.

MONTH_LABELS = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}

COLORS = {
    "baseline": "#1f77b4",
    "without_mitigation": "#d62728",
    "with_planning": "#2ca02c",
}
LINE_WIDTH = 3.4
MARKER_SIZE = 7
LINE_STYLE = "-"


def ensure_directories() -> None:
    """Create data and figure output folders if they do not already exist."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    FIGURE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def build_params(year: int) -> Dict[str, str]:
    """Build query parameters for a single-year EPA AQS request."""
    return {
        "email": EMAIL,
        "key": API_KEY,
        "param": PARAM_CODE,
        "bdate": f"{year}0101",
        "edate": f"{year}1231",
        "state": STATE_CODE,
    }


def raw_cache_path(year: int) -> Path:
    """Return the cached raw CSV path for a given year."""
    return OUTPUT_DIR / f"aqs_ozone_il_{year}_raw.csv"


def fetch_year_from_api(year: int) -> Optional[pd.DataFrame]:
    """Fetch one year of ozone records from the EPA AQS API and cache the raw response."""
    try:
        response = requests.get(API_URL, params=build_params(year), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        print(f"Warning: request failed for {year}: {exc}")
        return None
    except ValueError as exc:
        print(f"Warning: response parsing failed for {year}: {exc}")
        return None

    header = payload.get("Header", [])
    body = payload.get("Body", [])
    status = ""
    rows = 0
    errors = []

    if isinstance(header, list) and header:
        header_row = header[0]
        status = str(header_row.get("status", "")).strip()
        rows = int(header_row.get("rows", 0) or 0)
        errors = header_row.get("error", []) or header_row.get("errors", []) or []

    if errors:
        print(f"Warning: EPA API returned errors for {year}: {errors}")

    if not isinstance(body, list) or not body or rows == 0 or "No data matched" in status:
        print(f"Warning: no records returned for {year}.")
        return None

    year_df = pd.DataFrame(body)
    year_df.to_csv(raw_cache_path(year), index=False)
    print(f"{year}: fetched {len(year_df):,} rows from live API")
    return year_df


def load_cached_year(year: int) -> Optional[pd.DataFrame]:
    """Load a previously cached raw yearly CSV if it exists."""
    cache_file = raw_cache_path(year)
    if not cache_file.exists():
        return None

    cached_df = pd.read_csv(cache_file)
    print(f"{year}: loaded {len(cached_df):,} rows from cache")
    return cached_df


def load_or_fetch_year(year: int, refresh_api: bool) -> Optional[pd.DataFrame]:
    """Load data from cache by default, or refresh from the API when requested."""
    if not refresh_api:
        cached_df = load_cached_year(year)
        if cached_df is not None:
            return cached_df

    return fetch_year_from_api(year)


def load_or_fetch_all_years(start_year: int, end_year: int, refresh_api: bool) -> pd.DataFrame:
    """Load or fetch all requested years and combine them into one dataframe."""
    frames = []
    for year in range(start_year, end_year + 1):
        year_df = load_or_fetch_year(year, refresh_api)
        if year_df is not None and not year_df.empty:
            frames.append(year_df)

    if not frames:
        raise RuntimeError(
            "No ozone records were available from cache or the EPA API for the selected years."
        )

    combined_df = pd.concat(frames, ignore_index=True)
    print(f"Total combined rows (EPA AQS): {len(combined_df):,}")
    return combined_df


def load_supplement_2025_average() -> Tuple[float, bool, str]:
    """
    Load 2025 ozone data from the separate point-in-time export file.

    Returns (avg_ppb, is_partial, date_range_label).
    is_partial is True when the file does not cover a full calendar year.
    """
    if not TABLE_EXPORT_2025_PATH.exists():
        raise FileNotFoundError(
            f"2025 supplement file not found at: {TABLE_EXPORT_2025_PATH}\n"
            "Please ensure 'table_export-2 (1).csv' is in the parent directory."
        )

    df = pd.read_csv(TABLE_EXPORT_2025_PATH)
    ozone_num = pd.to_numeric(df["Ozone"], errors="coerce")
    valid_mask = ozone_num.notna() & (df["Units"].fillna("").str.upper() == "PPB")
    ozone_values = ozone_num[valid_mask]

    dates = pd.to_datetime(df["Selected Date_Time"], errors="coerce", dayfirst=False)
    min_date = dates.min()
    max_date = dates.max()
    is_partial = (min_date.month != 1 or min_date.day != 1) or (
        max_date.month != 12 or max_date.day != 31
    )

    avg_ppb = float(ozone_values.mean())
    date_label = f"{min_date.strftime('%b %d')} – {max_date.strftime('%b %d, %Y')}"
    partial_note = " (partial year)" if is_partial else ""
    print(
        f"2025 supplement: {len(ozone_values):,} valid PPB readings | "
        f"coverage {date_label}{partial_note} | mean {avg_ppb:.2f} ppb"
    )
    return avg_ppb, is_partial, date_label


def append_supplement_2025(yearly_summary: pd.DataFrame, avg_ppb: float) -> pd.DataFrame:
    """Append the 2025 supplement average to the 2020-2024 yearly summary."""
    row_2025 = pd.DataFrame({"year": [2025], "baseline_ppb": [avg_ppb]})
    combined = pd.concat([yearly_summary, row_2025], ignore_index=True)
    return combined.sort_values("year").reset_index(drop=True)


def keep_relevant_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only the columns needed for analysis and presentation outputs."""
    wanted_columns = [
        "date_local",
        "arithmetic_mean",
        "state_name",
        "county_name",
        "site_number",
        "parameter_code",
        "parameter",
        "units_of_measure",
    ]
    available_columns = [column for column in wanted_columns if column in df.columns]
    return df.loc[:, available_columns].copy()


def convert_to_ppb(df: pd.DataFrame) -> pd.Series:
    """Convert ozone values to ppb for easier presentation."""
    if "units_of_measure" not in df.columns:
        return df["arithmetic_mean"] * 1000

    units = df["units_of_measure"].fillna("").astype(str).str.lower()
    ppm_mask = units.str.contains("million")
    ozone_ppb = df["arithmetic_mean"].copy()
    ozone_ppb.loc[ppm_mask] = ozone_ppb.loc[ppm_mask] * 1000
    return ozone_ppb


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Clean the raw ozone data and add date parts used in summaries and charts."""
    cleaned_df = df.copy()
    cleaned_df["date_local"] = pd.to_datetime(cleaned_df["date_local"], errors="coerce")
    cleaned_df["arithmetic_mean"] = pd.to_numeric(cleaned_df["arithmetic_mean"], errors="coerce")
    cleaned_df = cleaned_df.dropna(subset=["date_local", "arithmetic_mean"]).copy()
    cleaned_df = cleaned_df.sort_values("date_local").reset_index(drop=True)

    cleaned_df["ozone_ppb"] = convert_to_ppb(cleaned_df)
    cleaned_df["year"] = cleaned_df["date_local"].dt.year
    cleaned_df["month"] = cleaned_df["date_local"].dt.month
    cleaned_df["month_name"] = cleaned_df["month"].map(MONTH_LABELS)
    cleaned_df["month_name"] = pd.Categorical(
        cleaned_df["month_name"],
        categories=[MONTH_LABELS[i] for i in range(1, 13)],
        ordered=True,
    )
    return cleaned_df


def create_yearly_summary(clean_df: pd.DataFrame) -> pd.DataFrame:
    """Create yearly average ozone summary in ppb."""
    yearly_summary = (
        clean_df.groupby("year", as_index=False)["ozone_ppb"]
        .mean()
        .rename(columns={"ozone_ppb": "baseline_ppb"})
        .sort_values("year")
        .reset_index(drop=True)
    )
    return yearly_summary


def create_monthly_summary(clean_df: pd.DataFrame) -> pd.DataFrame:
    """Create monthly average ozone summary across the full case-study period."""
    monthly_summary = (
        clean_df.groupby("month", as_index=False)["ozone_ppb"]
        .mean()
        .rename(columns={"ozone_ppb": "baseline_ppb"})
        .sort_values("month")
        .reset_index(drop=True)
    )
    monthly_summary["month_name"] = monthly_summary["month"].map(MONTH_LABELS)
    return monthly_summary


def create_monthly_scenarios(monthly_summary: pd.DataFrame) -> pd.DataFrame:
    """Build monthly modeled scenarios for construction without mitigation and with planning."""
    scenario_df = monthly_summary.copy()
    scenario_df["without_mitigation_ppb"] = scenario_df["baseline_ppb"] * (
        1 + WITHOUT_MITIGATION_UPLIFT
    )
    scenario_df["with_planning_ppb"] = scenario_df["baseline_ppb"] * (
        1 - WITH_PLANNING_REDUCTION_FROM_BASELINE
    )
    return scenario_df


def create_yearly_scenarios(yearly_summary: pd.DataFrame) -> pd.DataFrame:
    """Build yearly scenario metrics so average results can be exported cleanly."""
    scenario_df = yearly_summary.copy()
    scenario_df["without_mitigation_ppb"] = scenario_df["baseline_ppb"] * (
        1 + WITHOUT_MITIGATION_UPLIFT
    )
    scenario_df["with_planning_ppb"] = scenario_df["baseline_ppb"] * (
        1 - WITH_PLANNING_REDUCTION_FROM_BASELINE
    )
    return scenario_df


def save_data_outputs(
    clean_df: pd.DataFrame,
    yearly_summary: pd.DataFrame,
    monthly_summary: pd.DataFrame,
    monthly_scenarios: pd.DataFrame,
    yearly_scenarios: pd.DataFrame,
) -> None:
    """Save cleaned data and analysis tables for reuse."""
    clean_df.to_csv(OUTPUT_DIR / "ozone_illinois_2020_2025_clean.csv", index=False)
    yearly_summary.to_csv(OUTPUT_DIR / "ozone_yearly_summary_2020_2025.csv", index=False)
    monthly_summary.to_csv(OUTPUT_DIR / "ozone_monthly_summary_2020_2025.csv", index=False)
    monthly_scenarios.to_csv(OUTPUT_DIR / "ozone_monthly_scenarios.csv", index=False)
    yearly_scenarios.to_csv(OUTPUT_DIR / "ozone_yearly_scenarios.csv", index=False)


def style_axes(ax: plt.Axes) -> None:
    """Apply consistent styling to presentation charts."""
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=10)


def save_figure(fig: plt.Figure, filename: str) -> None:
    """Save a figure at presentation quality and confirm the saved path."""
    output_path = FIGURE_OUTPUT_DIR / filename
    fig.savefig(output_path, dpi=300, bbox_inches="tight")
    print(f"Saved figure to {output_path}")


def plot_monthly_baseline(monthly_summary: pd.DataFrame) -> None:
    """Plot the measured baseline trend used as the decision-support starting point."""
    fig, ax = plt.subplots(figsize=(10, 5.8))
    x_positions = monthly_summary["month"].to_list()
    x_labels = monthly_summary["month_name"].astype(str).to_list()
    ax.plot(
        x_positions,
        monthly_summary["baseline_ppb"],
        color=COLORS["baseline"],
        linewidth=LINE_WIDTH,
        linestyle=LINE_STYLE,
        marker="o",
        markersize=MARKER_SIZE,
        markeredgecolor="white",
        markeredgewidth=1.1,
        zorder=3,
    )
    fig.suptitle("Measured Ozone Baseline", fontsize=18, fontweight="bold", y=0.98)
    ax.set_title(
        "Illinois EPA AQS monthly averages, 2020-2025 case study",
        fontsize=11,
        color="#444444",
        pad=10,
    )
    ax.set_xlabel("Month", fontsize=11)
    ax.set_ylabel("Average Ozone (ppb)", fontsize=11)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_labels)
    style_axes(ax)
    fig.text(
        0.01,
        0.01,
        "Measured baseline only. Illinois is used here as a practical case study for broader air-quality pressure.",
        fontsize=9,
        color="#444444",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.92])
    save_figure(fig, "monthly_ozone_baseline.png")
    plt.show()


def plot_scenario_comparison(
    yearly_scenarios: pd.DataFrame,
    is_2025_partial: bool = True,
    supplement_date_range: str = "Jan 01 – Jun 30, 2025",
) -> None:
    """
    Plot yearly baseline plus modeled construction and planning scenarios.

    We started with real ozone data as our baseline.
    Then, for each year, we modeled an unmitigated construction scenario by increasing
    ozone by 8 percent to represent added emissions.
    We also modeled an Earth Twin planning scenario by reducing ozone by 5 percent to
    represent better decision-making.
    This allows us to directly compare how different choices affect environmental impact.

    2020-2024 baseline: EPA AQS measured data (Illinois, param 44201).
    2025 baseline: table_export-2 (1).csv — point-in-time site export.
    """
    fig, ax = plt.subplots(figsize=(11, 6.8))
    x_positions = yearly_scenarios["year"].to_list()
    year_labels = [str(year) for year in x_positions]

    ax.plot(
        x_positions,
        yearly_scenarios["baseline_ppb"],
        color=COLORS["baseline"],
        linewidth=LINE_WIDTH,
        linestyle=LINE_STYLE,
        marker="o",
        markersize=MARKER_SIZE,
        markeredgecolor="white",
        markeredgewidth=1.1,
        label="Baseline (Measured Data)",
        zorder=3,
    )
    ax.plot(
        x_positions,
        yearly_scenarios["without_mitigation_ppb"],
        color=COLORS["without_mitigation"],
        linewidth=LINE_WIDTH,
        linestyle=LINE_STYLE,
        marker="o",
        markersize=MARKER_SIZE,
        markeredgecolor="white",
        markeredgewidth=1.1,
        label=f"Without Mitigation (Modeled: baseline +{WITHOUT_MITIGATION_UPLIFT * 100:.0f}%)",
        zorder=3,
    )
    ax.plot(
        x_positions,
        yearly_scenarios["with_planning_ppb"],
        color=COLORS["with_planning"],
        linewidth=LINE_WIDTH,
        linestyle=LINE_STYLE,
        marker="o",
        markersize=MARKER_SIZE,
        markeredgecolor="white",
        markeredgewidth=1.1,
        label=f"With Planning — Earth Twin (Modeled: baseline \u2212{WITH_PLANNING_REDUCTION_FROM_BASELINE * 100:.0f}%)",
        zorder=3,
    )

    # Mark the 2025 data point with a visual indicator since it comes from a different source.
    idx_2025 = x_positions.index(2025) if 2025 in x_positions else None
    if idx_2025 is not None:
        partial_tag = " (partial)" if is_2025_partial else ""
        ax.axvline(x=2025, color="#888888", linewidth=1.0, linestyle=":", alpha=0.6, zorder=1)
        ax.text(
            2025,
            ax.get_ylim()[0] if ax.get_ylim()[0] > 0 else yearly_scenarios["baseline_ppb"].min() - 1,
            f"2025{partial_tag}\n{SUPPLEMENT_2025_LABEL}",
            ha="center",
            va="bottom",
            fontsize=7.5,
            color="#666666",
            style="italic",
        )

    fig.suptitle("Ozone Risk Under Construction Choices", fontsize=18, fontweight="bold", y=0.99)
    ax.set_title(
        "Baseline is measured EPA AQS yearly ozone (2020–2024) + site export (2025).\n"
        "Red and green lines are scenario models derived directly from each year's baseline value.",
        fontsize=10.5,
        color="#444444",
        pad=10,
    )
    ax.set_xlabel("Year", fontsize=11)
    ax.set_ylabel("Average Ozone (ppb)", fontsize=11)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(year_labels)
    style_axes(ax)
    ax.legend(frameon=False, fontsize=10, loc="upper left")

    gap_series = (
        yearly_scenarios["without_mitigation_ppb"] - yearly_scenarios["with_planning_ppb"]
    )
    max_gap_index = int(gap_series.idxmax())
    max_gap_year = year_labels[max_gap_index]
    max_gap_value = gap_series.iloc[max_gap_index]
    max_gap_y = yearly_scenarios["without_mitigation_ppb"].iloc[max_gap_index]

    ax.annotate(
        f"Largest planning benefit: {max_gap_value:.1f} ppb in {max_gap_year}",
        xy=(x_positions[max_gap_index], max_gap_y),
        xytext=(x_positions[max_gap_index] - 1.1, max_gap_y + 4),
        textcoords="data",
        arrowprops=dict(arrowstyle="->", color="#444444", lw=1.2),
        fontsize=10,
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#cccccc"),
    )

    partial_note = ""
    if is_2025_partial:
        partial_note = f" | 2025 from {SUPPLEMENT_2025_LABEL}: {supplement_date_range} (partial year)"

    assumption_note = (
        f"Data sources: 2020–2024 = EPA AQS (Illinois, param 44201){partial_note}\n"
        f"Scenario model: without mitigation = baseline +{WITHOUT_MITIGATION_UPLIFT * 100:.0f}% | "
        f"with planning = baseline \u2212{WITH_PLANNING_REDUCTION_FROM_BASELINE * 100:.0f}%   "
        "Rationale: construction adds ozone-forming emissions through equipment use, diesel traffic, and site activity."
    )
    fig.text(0.01, 0.01, assumption_note, fontsize=8.5, color="#444444")
    fig.tight_layout(rect=[0, 0.09, 1, 0.93])
    save_figure(fig, "ozone_scenario_comparison.png")
    plt.show()


def plot_impact_summary(monthly_scenarios: pd.DataFrame) -> Tuple[float, float]:
    """Plot a three-bar summary comparing average ozone across scenarios."""
    baseline_avg = monthly_scenarios["baseline_ppb"].mean()
    unmitigated_avg = monthly_scenarios["without_mitigation_ppb"].mean()
    planning_avg = monthly_scenarios["with_planning_ppb"].mean()
    planning_benefit_ppb = unmitigated_avg - planning_avg
    reduction_pct = (planning_benefit_ppb / unmitigated_avg) * 100

    labels = [
        "Baseline",
        "Without\nMitigation",
        "With\nPlanning",
    ]
    values = [baseline_avg, unmitigated_avg, planning_avg]
    colors = [
        COLORS["baseline"],
        COLORS["without_mitigation"],
        COLORS["with_planning"],
    ]

    fig, ax = plt.subplots(figsize=(9.4, 6.2))
    bars = ax.bar(labels, values, color=colors, width=0.65)
    fig.suptitle("Average Ozone Impact Summary", fontsize=18, fontweight="bold", y=0.97)
    ax.set_title(
        "Only the baseline is measured. The other bars are scenario estimates for planning decisions.",
        fontsize=11,
        color="#444444",
        pad=10,
    )
    ax.set_ylabel("Average Ozone (ppb)", fontsize=11)
    style_axes(ax)

    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.35,
            f"{value:.1f}",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

    ax.text(
        1.02,
        max(values) * 0.88,
        f"Planning reduces ozone by {planning_benefit_ppb:.1f} ppb\nvs. unmitigated construction",
        fontsize=10.5,
        bbox=dict(boxstyle="round,pad=0.35", fc="#f7f7f7", ec="#cccccc"),
    )

    fig.text(
        0.01,
        0.01,
        "Interpretation: modeled planning support lowers ozone pressure compared with an unmitigated construction path.",
        fontsize=9,
        color="#444444",
    )
    fig.tight_layout(rect=[0, 0.05, 1, 0.92])
    save_figure(fig, "ozone_impact_summary.png")
    plt.show()
    return planning_benefit_ppb, reduction_pct


def build_presentation_caption() -> str:
    """Generate a reusable caption for slides or demo notes."""
    return (
        "Using EPA AQS ozone observations as the baseline, we modeled how an unmitigated "
        "construction scenario could increase ozone exposure and how Earth Twin-supported "
        "planning could reduce that impact before construction begins."
    )


def save_presentation_caption(caption_text: str) -> None:
    """Save the reusable presentation caption to the presentation output folder."""
    caption_path = FIGURE_OUTPUT_DIR / "presentation_caption.txt"
    caption_path.write_text(caption_text + "\n", encoding="utf-8")
    print(f"Saved presentation caption to {caption_path}")


def print_console_summary(
    clean_df: pd.DataFrame,
    yearly_scenarios: pd.DataFrame,
    monthly_scenarios: pd.DataFrame,
    is_2025_partial: bool = True,
    supplement_date_range: str = "Jan 01 – Jun 30, 2025",
) -> None:
    """Print a concise console summary for the hackathon workflow."""
    print("\n" + "=" * 66)
    print("OZONE SCENARIO SUMMARY  |  2020 – 2025")
    print("=" * 66)
    print(f"\nEPA AQS data year range: {int(clean_df['year'].min())}–{int(clean_df['year'].max())}")
    if is_2025_partial:
        print(
            f"2025 source: {SUPPLEMENT_2025_LABEL}  "
            f"[{supplement_date_range}] — partial year"
        )

    print(
        "\n{:<6}  {:>14}  {:>22}  {:>16}".format(
            "Year", "Baseline (ppb)", "Without Mitigation (ppb)", "With Planning (ppb)"
        )
    )
    print("-" * 66)
    for _, row in yearly_scenarios.iterrows():
        year = int(row["year"])
        suffix = f"  <- {SUPPLEMENT_2025_LABEL} (partial)" if year == 2025 and is_2025_partial else ""
        print(
            "{:<6}  {:>14.2f}  {:>22.2f}  {:>16.2f}{}".format(
                year,
                row["baseline_ppb"],
                row["without_mitigation_ppb"],
                row["with_planning_ppb"],
                suffix,
            )
        )

    baseline_avg = monthly_scenarios["baseline_ppb"].mean()
    unmitigated_avg = monthly_scenarios["without_mitigation_ppb"].mean()
    planning_avg = monthly_scenarios["with_planning_ppb"].mean()
    difference_ppb = unmitigated_avg - planning_avg
    reduction_pct = (difference_ppb / unmitigated_avg) * 100

    print("\nMonthly average summary (2020–2024 EPA data)")
    print(f"  Baseline:                 {baseline_avg:.2f} ppb")
    print(f"  Without mitigation:       {unmitigated_avg:.2f} ppb")
    print(f"  With planning:            {planning_avg:.2f} ppb")
    print(f"  Difference (benefit):     {difference_ppb:.2f} ppb")
    print(f"  Reduction vs unmitigated: {reduction_pct:.2f}%")
    print("=" * 66)


def main() -> None:
    """Run the full air-quality workflow with caching, scenarios, and presentation-ready outputs."""
    ensure_directories()

    if REFRESH_API:
        print("Data source mode: refreshing from live EPA AQS API where possible.")
    else:
        print("Data source mode: using cached EPA AQS files by default.")

    # Load 2020-2024 from EPA AQS cached files.
    raw_df = load_or_fetch_all_years(START_YEAR, END_YEAR - 1, REFRESH_API)
    trimmed_df = keep_relevant_columns(raw_df)
    clean_df = clean_data(trimmed_df)

    if clean_df.empty:
        raise RuntimeError("The cleaned ozone dataset is empty after parsing and validation.")

    yearly_summary_2020_2024 = create_yearly_summary(clean_df)
    monthly_summary = create_monthly_summary(clean_df)
    monthly_scenarios = create_monthly_scenarios(monthly_summary)

    # Load 2025 from the separate site-level export and append to the yearly series.
    avg_2025_ppb, is_2025_partial, supplement_date_range = load_supplement_2025_average()
    yearly_summary = append_supplement_2025(yearly_summary_2020_2024, avg_2025_ppb)
    yearly_scenarios = create_yearly_scenarios(yearly_summary)

    save_data_outputs(
        clean_df=clean_df,
        yearly_summary=yearly_summary,
        monthly_summary=monthly_summary,
        monthly_scenarios=monthly_scenarios,
        yearly_scenarios=yearly_scenarios,
    )

    plot_monthly_baseline(monthly_summary)
    plot_scenario_comparison(
        yearly_scenarios,
        is_2025_partial=is_2025_partial,
        supplement_date_range=supplement_date_range,
    )
    plot_impact_summary(monthly_scenarios)

    caption_text = build_presentation_caption()
    save_presentation_caption(caption_text)
    print_console_summary(
        clean_df,
        yearly_scenarios,
        monthly_scenarios,
        is_2025_partial=is_2025_partial,
        supplement_date_range=supplement_date_range,
    )

    print("\nReusable presentation caption")
    print(caption_text)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
