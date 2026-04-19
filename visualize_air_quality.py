import argparse
from pathlib import Path
import sys

try:
    import pandas as pd
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns
except ImportError as exc:
    missing = exc.name if hasattr(exc, "name") else "required packages"
    raise SystemExit(
        f"Missing dependency: {missing}\n"
        "Install with: python3 -m pip install pandas matplotlib seaborn"
    )


INPUT_CSV = Path("/Users/nucleusshrestha/Downloads/table_export.csv")
OUTPUT_DIR = Path("outputs/air_quality_viz")
AQS_DATA_DIR = Path("data/aqs_ozone")
MIN_SITE_OBSERVATIONS = 1000


def load_challenge_data(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    df = df.rename(
        columns={
            "Site ID": "site_id",
            "Ozone": "ozone",
            "Units": "units",
            "QA Code": "qa_code",
            "Update_Date": "update_date",
            "Ozone F": "ozone_flag",
            "Selected Date_Time": "selected_datetime",
        }
    )

    df["source"] = "challenge_csv"
    df["selected_datetime"] = pd.to_datetime(
        df["selected_datetime"], format="%m/%d/%Y %I:%M:%S %p", errors="coerce"
    )
    df["update_date"] = pd.to_datetime(
        df["update_date"], format="%m/%d/%Y %I:%M:%S %p", errors="coerce"
    )
    df["ozone"] = pd.to_numeric(df["ozone"], errors="coerce")

    clean = df.dropna(subset=["selected_datetime", "ozone", "site_id"]).copy()
    clean["date"] = clean["selected_datetime"].dt.date
    clean["month_name"] = clean["selected_datetime"].dt.strftime("%b")
    clean["month_num"] = clean["selected_datetime"].dt.month
    clean["year"] = clean["selected_datetime"].dt.year

    return clean


def load_aqs_data(aqs_dir: Path) -> pd.DataFrame:
    csv_paths = sorted(aqs_dir.glob("illinois_ozone_*.csv"))
    if not csv_paths:
        return pd.DataFrame()

    frames = []
    for path in csv_paths:
        df = pd.read_csv(path)
        if df.empty:
            continue

        df["selected_datetime"] = pd.to_datetime(df["selected_datetime"], errors="coerce")
        df["ozone"] = pd.to_numeric(df["ozone"], errors="coerce")
        clean = df.dropna(subset=["selected_datetime", "ozone", "site_id"]).copy()
        clean["date"] = clean["selected_datetime"].dt.date
        clean["month_name"] = clean["selected_datetime"].dt.strftime("%b")
        clean["month_num"] = clean["selected_datetime"].dt.month
        clean["year"] = clean["selected_datetime"].dt.year
        frames.append(clean)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def load_and_clean_data(csv_path: Path, include_aqs: bool, aqs_dir: Path) -> pd.DataFrame:
    frames = [load_challenge_data(csv_path)]

    if include_aqs:
        aqs_df = load_aqs_data(aqs_dir)
        if not aqs_df.empty:
            frames.append(aqs_df)

    return pd.concat(frames, ignore_index=True)


def build_summary_tables(df: pd.DataFrame):
    challenge_df = df[df["source"] == "challenge_csv"].copy()
    aqs_df = df[df["source"] == "epa_aqs_api"].copy()

    daily_source = challenge_df if not challenge_df.empty else df
    daily_avg = (
        daily_source.groupby("date", as_index=False)
        .agg(avg_ozone=("ozone", "mean"), readings=("ozone", "size"))
        .sort_values("date")
    )

    period_source = aqs_df if aqs_df["year"].nunique() > 1 else df

    if period_source["year"].nunique() > 1:
        period_avg = (
            period_source.groupby("year", as_index=False)
            .agg(avg_ozone=("ozone", "mean"), readings=("ozone", "size"))
            .sort_values("year")
        )
        period_label = "Year"
        period_title = "Illinois Ozone by Year (EPA AQS)"
        period_x = "year"
        period_source_label = "epa_aqs_api"
    else:
        period_avg = (
            period_source.groupby(["month_num", "month_name"], as_index=False)
            .agg(avg_ozone=("ozone", "mean"), readings=("ozone", "size"))
            .sort_values("month_num")
        )
        period_label = "Month"
        period_title = "Average Ozone by Month"
        period_x = "month_name"
        period_source_label = sorted(period_source["source"].dropna().unique())[0]

    top_site_source = challenge_df if not challenge_df.empty else df
    site_summary = (
        top_site_source.groupby("site_id", as_index=False)
        .agg(avg_ozone=("ozone", "mean"), readings=("ozone", "size"))
        .query("readings >= @MIN_SITE_OBSERVATIONS")
        .sort_values("avg_ozone", ascending=False)
    )

    top_sites = site_summary.head(10).sort_values("avg_ozone", ascending=True)

    daily_title = (
        "2025 Challenge Dataset Daily Average Ozone"
        if not challenge_df.empty
        else "Daily Average Ozone Over Time"
    )
    daily_source_label = "challenge_csv" if not challenge_df.empty else "mixed"
    top_sites_title = (
        f"Top 10 Challenge Sites by Average Ozone\n(min {MIN_SITE_OBSERVATIONS} readings)"
        if not challenge_df.empty
        else f"Top 10 Sites by Average Ozone\n(min {MIN_SITE_OBSERVATIONS} readings)"
    )
    top_sites_source_label = "challenge_csv" if not challenge_df.empty else "mixed"

    return (
        daily_avg,
        period_avg,
        top_sites,
        period_x,
        period_label,
        period_title,
        daily_title,
        top_sites_title,
        daily_source_label,
        period_source_label,
        top_sites_source_label,
    )


def save_dashboard(
    daily_avg: pd.DataFrame,
    period_avg: pd.DataFrame,
    top_sites: pd.DataFrame,
    df: pd.DataFrame,
    period_x: str,
    period_label: str,
    period_title: str,
    daily_title: str,
    top_sites_title: str,
    daily_source_label: str,
    period_source_label: str,
    top_sites_source_label: str,
) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sns.set_theme(style="whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle("Ozone Trend Dashboard", fontsize=18, fontweight="bold")

    sns.lineplot(
        data=daily_avg,
        x="date",
        y="avg_ozone",
        ax=axes[0, 0],
        color="#176087",
        linewidth=2,
    )
    axes[0, 0].set_title(daily_title)
    axes[0, 0].set_xlabel("Date")
    axes[0, 0].set_ylabel("Average Ozone (PPB)")

    sns.barplot(
        data=period_avg,
        x=period_x,
        y="avg_ozone",
        ax=axes[0, 1],
        color="#4c956c",
    )
    axes[0, 1].set_title(period_title)
    axes[0, 1].set_xlabel(period_label)
    axes[0, 1].set_ylabel("Average Ozone (PPB)")

    sns.barplot(
        data=top_sites,
        x="avg_ozone",
        y="site_id",
        hue="site_id",
        ax=axes[1, 0],
        palette="rocket",
        dodge=False,
        legend=False,
    )
    axes[1, 0].set_title(top_sites_title)
    axes[1, 0].set_xlabel("Average Ozone (PPB)")
    axes[1, 0].set_ylabel("Site ID")

    axes[1, 1].axis("off")
    min_date = pd.to_datetime(df["date"]).min().strftime("%Y-%m-%d")
    max_date = pd.to_datetime(df["date"]).max().strftime("%Y-%m-%d")
    summary_text = "\n".join(
        [
            "Dataset summary",
            f"Date range: {min_date} to {max_date}",
            f"Total valid ozone readings: {len(df):,}",
            f"Monitoring sites: {df['site_id'].nunique()}",
            f"Data sources: {', '.join(sorted(df['source'].dropna().unique()))}",
            f"Daily chart source: {daily_source_label}",
            f"Period chart source: {period_source_label}",
            f"Top sites source: {top_sites_source_label}",
            f"Highest period avg: {period_avg.loc[period_avg['avg_ozone'].idxmax(), period_x]} "
            f"({period_avg['avg_ozone'].max():.2f} PPB)",
            f"Top high-sample site: {top_sites.iloc[-1]['site_id']} "
            f"({top_sites.iloc[-1]['avg_ozone']:.2f} PPB)",
            "",
            "Pitch angle",
            "Ozone is not flat across time or place.",
            "That makes forecasting, alerts, and local response",
            "tools easier to justify with data.",
        ]
    )
    axes[1, 1].text(
        0.02,
        0.98,
        summary_text,
        va="top",
        ha="left",
        fontsize=12,
        linespacing=1.5,
        bbox={"boxstyle": "round,pad=0.8", "facecolor": "#f4f1ea", "edgecolor": "#d8d1c5"},
    )

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(OUTPUT_DIR / "air_quality_dashboard.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def save_individual_charts(
    daily_avg: pd.DataFrame,
    period_avg: pd.DataFrame,
    top_sites: pd.DataFrame,
    period_x: str,
    period_label: str,
    period_title: str,
    daily_title: str,
    top_sites_title: str,
) -> None:
    sns.set_theme(style="whitegrid")

    plt.figure(figsize=(12, 5))
    sns.lineplot(data=daily_avg, x="date", y="avg_ozone", color="#176087", linewidth=2)
    plt.title(daily_title)
    plt.xlabel("Date")
    plt.ylabel("Average Ozone (PPB)")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "daily_avg_ozone.png", dpi=300, bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(8, 5))
    sns.barplot(data=period_avg, x=period_x, y="avg_ozone", color="#4c956c")
    plt.title(period_title)
    plt.xlabel(period_label)
    plt.ylabel("Average Ozone (PPB)")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "period_avg_ozone.png", dpi=300, bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(10, 6))
    sns.barplot(
        data=top_sites,
        x="avg_ozone",
        y="site_id",
        hue="site_id",
        palette="rocket",
        dodge=False,
        legend=False,
    )
    plt.title(top_sites_title.replace("\n", " "))
    plt.xlabel("Average Ozone (PPB)")
    plt.ylabel("Site ID")
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "top_sites_avg_ozone.png", dpi=300, bbox_inches="tight")
    plt.close()


def print_summary(
    period_avg: pd.DataFrame,
    top_sites: pd.DataFrame,
    df: pd.DataFrame,
    period_x: str,
    period_label: str,
    daily_source_label: str,
    period_source_label: str,
    top_sites_source_label: str,
) -> None:
    print("\nCleaned dataset summary")
    print(f"Valid ozone rows: {len(df):,}")
    print(f"Sites: {df['site_id'].nunique()}")
    print(f"Sources: {', '.join(sorted(df['source'].dropna().unique()))}")
    print(f"Daily chart source: {daily_source_label}")
    print(f"{period_label} chart source: {period_source_label}")
    print(f"Top sites chart source: {top_sites_source_label}")
    print(
        f"Date range: {pd.to_datetime(df['date']).min().strftime('%Y-%m-%d')} "
        f"to {pd.to_datetime(df['date']).max().strftime('%Y-%m-%d')}"
    )

    print(f"\nAverage ozone by {period_label.lower()} (PPB)")
    print(period_avg[[period_x, "avg_ozone", "readings"]].round({"avg_ozone": 2}).to_string(index=False))

    print("\nTop 10 high-sample sites by average ozone (PPB)")
    print(top_sites[["site_id", "avg_ozone", "readings"]].round({"avg_ozone": 2}).to_string(index=False))

    print(f"\nSaved charts to: {OUTPUT_DIR.resolve()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visualize challenge ozone data with optional AQS cache.")
    parser.add_argument("csv_path", nargs="?", default=str(INPUT_CSV))
    parser.add_argument(
        "--include-aqs",
        action="store_true",
        help="Include cached Illinois AQS ozone files from data/aqs_ozone.",
    )
    parser.add_argument(
        "--aqs-dir",
        default=str(AQS_DATA_DIR),
        help="Directory containing cached AQS CSV files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        raise SystemExit(f"CSV file not found: {csv_path}")

    df = load_and_clean_data(csv_path, include_aqs=args.include_aqs, aqs_dir=Path(args.aqs_dir))
    (
        daily_avg,
        period_avg,
        top_sites,
        period_x,
        period_label,
        period_title,
        daily_title,
        top_sites_title,
        daily_source_label,
        period_source_label,
        top_sites_source_label,
    ) = build_summary_tables(df)

    if top_sites.empty:
        raise SystemExit(
            "No site met the minimum observation threshold. Lower MIN_SITE_OBSERVATIONS and try again."
        )

    save_dashboard(
        daily_avg,
        period_avg,
        top_sites,
        df,
        period_x,
        period_label,
        period_title,
        daily_title,
        top_sites_title,
        daily_source_label,
        period_source_label,
        top_sites_source_label,
    )
    save_individual_charts(
        daily_avg,
        period_avg,
        top_sites,
        period_x,
        period_label,
        period_title,
        daily_title,
        top_sites_title,
    )
    print_summary(
        period_avg,
        top_sites,
        df,
        period_x,
        period_label,
        daily_source_label,
        period_source_label,
        top_sites_source_label,
    )


if __name__ == "__main__":
    main()
