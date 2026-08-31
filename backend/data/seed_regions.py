"""Seeds the region_snapshots Firestore collection.

Usage (from the backend/ directory, with a Firestore connection configured):

    python -m data.seed_regions            # upsert all regions
    python -m data.seed_regions --clear    # wipe the collection first

Data sources:
  * 10 hand-authored synthetic REGIONS (kept unchanged below) for fleshed-out
    scenario control.
  * The 30-region survey dataset packaged at the repository root under data/,
    parsed from these CSVs:
      - regional_survey_data.csv         - one row per (region, disease) pair
      - hiv_ebola_lassa_survey_data.csv  - the synthetic HIV / Ebola / Lassa
        fever rows; merged in and deduped against the main file
      - hospital_admissions.csv          - 14 days per region (region-level, not
                                           disease-specific)
      - resource_allocation.csv          - one row per region (region-level)
    One region_snapshots document is created per (region, disease) pair; the
    region-level admissions series and funding/staffing/vaccine values are
    joined in by exact region name, so different diseases for the same region
    reuse the same non-disease-specific signals.
"""

from __future__ import annotations

import csv
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure the backend/ directory (parent of data/) is importable so that the
# `agents` package resolves when this module runs as `python -m data.seed_regions`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.tools import firestore_tool  # noqa: E402  (path bootstrap first)

# Source CSVs live at the repository root under data/.
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SURVEY_CSV = DATA_DIR / "regional_survey_data.csv"
SYNTHETIC_SURVEY_CSV = DATA_DIR / "hiv_ebola_lassa_survey_data.csv"
ADMISSIONS_CSV = DATA_DIR / "hospital_admissions.csv"
ALLOCATION_CSV = DATA_DIR / "resource_allocation.csv"

# Baseline regional-average funding used by the existing REGIONS entries.
REGIONAL_AVG_FUNDING_USD = 100000.0

# Each region defines one mandatory date anchor (last_survey_days_ago); the
# remaining fields are stored explicitly for full control of the scenario.
REGIONS = [
    {
        "region_id": "region-lusaka-01",
        "country": "Zambia",
        "last_survey_days_ago": 47,
        "admissions_last_14d": [5, 6, 5, 7, 8, 9, 10, 11, 12, 12, 14, 15, 16, 18],
        "admissions_pct_change": 21.0,
        "funding_usd": 41000.0,
        "staffing_count": 12,
        "supply_stock_units": 85,
        "regional_avg_funding_usd": 100000.0,
    },
    {
        "region_id": "region-kathmandu-01",
        "country": "Nepal",
        "last_survey_days_ago": 88,
        "admissions_last_14d": [4, 4, 5, 4, 5, 6, 6, 7, 8, 8, 9, 9, 10, 12],
        "admissions_pct_change": 13.0,
        "funding_usd": 63500.0,
        "staffing_count": 46,
        "supply_stock_units": 210,
        "regional_avg_funding_usd": 100000.0,
    },
    {
        "region_id": "region-kampala-01",
        "country": "Uganda",
        "last_survey_days_ago": 35,
        "admissions_last_14d": [6, 6, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13],
        "admissions_pct_change": 8.0,
        "funding_usd": 84000.0,
        "staffing_count": 55,
        "supply_stock_units": 300,
        "regional_avg_funding_usd": 100000.0,
    },
    {
        "region_id": "region-manaus-01",
        "country": "Brazil",
        "last_survey_days_ago": 9,
        "admissions_last_14d": [3, 3, 2, 3, 4, 3, 3, 4, 3, 3, 2, 3, 3, 3],
        "admissions_pct_change": -2.0,
        "funding_usd": 121000.0,
        "staffing_count": 82,
        "supply_stock_units": 540,
        "regional_avg_funding_usd": 100000.0,
    },
    {
        "region_id": "region-nairobi-01",
        "country": "Kenya",
        "last_survey_days_ago": 15,
        "admissions_last_14d": [7, 7, 8, 8, 9, 9, 9, 10, 10, 10, 11, 11, 12, 12],
        "admissions_pct_change": 6.0,
        "funding_usd": 96000.0,
        "staffing_count": 61,
        "supply_stock_units": 420,
        "regional_avg_funding_usd": 100000.0,
    },
    {
        "region_id": "region-jakarta-01",
        "country": "Indonesia",
        "last_survey_days_ago": 20,
        "admissions_last_14d": [9, 8, 9, 10, 9, 10, 9, 10, 10, 9, 9, 10, 10, 11],
        "admissions_pct_change": 4.0,
        "funding_usd": 118000.0,
        "staffing_count": 88,
        "supply_stock_units": 610,
        "regional_avg_funding_usd": 100000.0,
    },
    {
        "region_id": "region-tijuana-01",
        "country": "Mexico",
        "last_survey_days_ago": 27,
        "admissions_last_14d": [4, 4, 5, 5, 4, 5, 5, 6, 5, 6, 6, 5, 6, 6],
        "admissions_pct_change": 3.0,
        "funding_usd": 104000.0,
        "staffing_count": 70,
        "supply_stock_units": 470,
        "regional_avg_funding_usd": 100000.0,
    },
    {
        "region_id": "region-accra-01",
        "country": "Ghana",
        "last_survey_days_ago": 31,
        "admissions_last_14d": [5, 5, 6, 7, 7, 8, 9, 9, 10, 11, 12, 13, 14, 15],
        "admissions_pct_change": 17.0,
        "funding_usd": 52000.0,
        "staffing_count": 38,
        "supply_stock_units": 160,
        "regional_avg_funding_usd": 100000.0,
    },
    {
        "region_id": "region-lima-01",
        "country": "Peru",
        "last_survey_days_ago": 12,
        "admissions_last_14d": [6, 6, 7, 7, 7, 6, 7, 7, 8, 7, 7, 8, 8, 8],
        "admissions_pct_change": 1.0,
        "funding_usd": 98000.0,
        "staffing_count": 75,
        "supply_stock_units": 380,
        "regional_avg_funding_usd": 100000.0,
    },
    {
        "region_id": "region-bangalore-01",
        "country": "India",
        "last_survey_days_ago": 6,
        "admissions_last_14d": [2, 2, 3, 2, 2, 3, 2, 2, 2, 3, 2, 2, 2, 2],
        "admissions_pct_change": 0.0,
        "funding_usd": 99000.0,
        "staffing_count": 90,
        "supply_stock_units": 700,
        "regional_avg_funding_usd": 100000.0,
    },
]


def _snapshot(region: dict) -> dict:
    survey_at = datetime.now(timezone.utc) - timedelta(days=region["last_survey_days_ago"])
    snapshot = {
        "region_id": region["region_id"],
        "country": region["country"],
        "last_survey_at": survey_at.isoformat(),
        "days_since_survey": region["last_survey_days_ago"],
        "admissions_last_14d": region["admissions_last_14d"],
        "admissions_pct_change": region["admissions_pct_change"],
        "funding_usd": region["funding_usd"],
        "staffing_count": region["staffing_count"],
        "supply_stock_units": region["supply_stock_units"],
        "regional_avg_funding_usd": region["regional_avg_funding_usd"],
    }
    if region.get("disease"):
        # Imported rows carry the surveyed disease; the hand-authored REGIONS
        # deliberately do not. The data steward reads disease generically
        # (None when absent).
        snapshot["disease"] = region["disease"]
    return snapshot


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _slugify(text: str) -> str:
    """Lowercase alphanumeric slug used by the region-<slug>-01 id convention.

    e.g. "Nigeria" + "COVID-19" -> "region-nigeria-covid19-01" and
         "Nigeria" + "HIV"      -> "region-nigeria-hiv-01": two distinct ids
         for the two disease rows, never merged into one.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _region_id(region: str, disease: str) -> str:
    return f"region-{_slugify(region)}-{_slugify(disease)}-01"


def _pct_change_from_first_to_last(series: list[int]) -> float:
    """Percent change across the 14-day series, mirroring the REGIONS fields."""
    first = series[0]
    if first == 0:
        return 0.0  # no baseline; treat as flat rather than dividing by zero
    return round((series[-1] - first) / first * 100.0, 1)


def _load_admissions(rows: list[dict]) -> dict[str, list[int]]:
    """region -> 14-day admission counts in date order (region-level)."""
    by_region: dict[str, list[tuple[str, int]]] = {}
    for row in rows:
        region = row["region"].strip()
        if not region:
            raise ValueError("hospital_admissions.csv contains a row with an empty region")
        try:
            count = int(row["admission_count"])
        except (TypeError, ValueError):
            raise ValueError(
                f"hospital_admissions.csv: non-integer admission_count for {region} "
                f"on {row['date']!r}: {row['admission_count']!r}"
            ) from None
        if count < 0:
            raise ValueError(f"hospital_admissions.csv: negative admission_count for {region}")
        by_region.setdefault(region, []).append((row["date"].strip(), count))

    series_by_region: dict[str, list[int]] = {}
    for region, pairs in by_region.items():
        if len(pairs) != 14:
            raise ValueError(
                f"hospital_admissions.csv: region '{region}' has {len(pairs)} rows, expected 14"
            )
        if len({date for date, _ in pairs}) != len(pairs):
            raise ValueError(f"hospital_admissions.csv: region '{region}' has duplicate dates")
        series_by_region[region] = [count for _, count in sorted(pairs)]
    return series_by_region


def _load_allocation(rows: list[dict]) -> dict[str, dict]:
    """region -> funding_usd / staffing_count / supply_stock_units (region-level)."""
    by_region: dict[str, dict] = {}
    for row in rows:
        region = row["region"].strip()
        if not region:
            raise ValueError("resource_allocation.csv contains a row with an empty region")
        pct = float(row["funding_level_pct_of_avg"])
        # The CSV stores funding as a PERCENT of the regional average, not a
        # dollar amount; convert using the same 100,000 baseline as the
        # hand-authored REGIONS entries.
        by_region[region] = {
            "funding_usd": round((pct / 100.0) * REGIONAL_AVG_FUNDING_USD, 1),
            "staffing_count": int(row["staff_count"]),
            "supply_stock_units": int(row["vaccine_stock_units"]),
        }
    return by_region


def _merge_survey_files(primary: list[dict], supplement: list[dict]) -> list[dict]:
    """Merge two survey CSVs on (region, disease), refusing to guess on conflicts.

    The synthetic HIV / Ebola / Lassa fever rows are duplicated between the
    main file and the supplement; identical rows are deduped. A (region,
    disease) pair that differs between the two files is a data inconsistency
    and raises rather than silently picking a side.
    """
    merged: dict[tuple[str, str], dict] = {}
    for row in primary + supplement:
        key = (row["region"].strip(), row["disease"].strip())
        if key in merged and merged[key] != row:
            raise ValueError(
                f"STOP: survey CSVs disagree on {key}:\n  {merged[key]!r}\n  {row!r}"
            )
        merged[key] = row
    return list(merged.values())


def _build_imported() -> tuple[list[dict], int, int]:
    """One region_snapshots entry per (region, disease) survey row.

    Returns (imported_regions, real_row_count, synthetic_row_count).
    STOPS (raises) instead of silently dropping data if any survey region name
    fails to join to hospital_admissions.csv or resource_allocation.csv.
    """
    survey = _read_csv(SURVEY_CSV)
    if SYNTHETIC_SURVEY_CSV.exists():
        survey = _merge_survey_files(survey, _read_csv(SYNTHETIC_SURVEY_CSV))
    admissions = _load_admissions(_read_csv(ADMISSIONS_CSV))
    allocation = _load_allocation(_read_csv(ALLOCATION_CSV))

    survey_regions = {row["region"].strip() for row in survey if row["region"].strip()}
    missing_admissions = sorted(survey_regions - set(admissions))
    missing_allocation = sorted(survey_regions - set(allocation))
    if missing_admissions or missing_allocation:
        details = []
        if missing_admissions:
            details.append(f"no hospital_admissions row: {', '.join(missing_admissions)}")
        if missing_allocation:
            details.append(f"no resource_allocation row: {', '.join(missing_allocation)}")
        raise ValueError(
            "STOP: region join failure between survey data and region-level files - "
            + "; ".join(details) + ". Refusing to seed rather than drop/fabricate data."
        )

    imported: list[dict] = []
    seen_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    real_count = 0
    synthetic_count = 0

    for row in survey:
        region = row["region"].strip()
        country = row["country"].strip()
        disease = row["disease"].strip()

        pair = (region, disease)
        if pair in seen_pairs:
            raise ValueError(f"regional_survey_data.csv: duplicate (region, disease) row {pair}")
        seen_pairs.add(pair)

        region_id = _region_id(region, disease)
        if region_id in seen_ids:
            raise ValueError(f"region_id collision for {pair} -> {region_id}")
        seen_ids.add(region_id)

        try:
            last_survey = datetime.strptime(row["last_survey_date"].strip()[:10], "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"regional_survey_data.csv: bad last_survey_date {row['last_survey_date']!r} "
                f"for {pair}"
            ) from None

        # last_survey_days_ago is computed relative to TODAY's actual date, not
        # the date the prior project was built. Regions that were already stale
        # in the source dataset therefore seed as even more stale now - this is
        # expected, correct behavior, not a bug.
        days_ago = max((datetime.now(timezone.utc).date() - last_survey.date()).days, 0)

        data_source = row["data_source"].strip().lower()
        if data_source == "real":
            real_count += 1
        elif data_source == "synthetic":
            synthetic_count += 1
        else:
            raise ValueError(
                f"regional_survey_data.csv: unexpected data_source {row['data_source']!r} "
                f"for {pair}"
            )

        series = admissions[region]  # same series reused across every disease row
        imported.append(
            {
                "region_id": region_id,
                "country": country,
                "disease": disease,
                "last_survey_days_ago": days_ago,
                "admissions_last_14d": series,
                "admissions_pct_change": _pct_change_from_first_to_last(series),
                **allocation[region],  # funding_usd / staffing_count / supply_stock_units
                "regional_avg_funding_usd": REGIONAL_AVG_FUNDING_USD,
            }
        )

    return imported, real_count, synthetic_count


def main() -> None:
    clear = "--clear" in sys.argv
    client = firestore_tool._client()
    collection = client.collection("region_snapshots")
    if clear:
        for doc in collection.stream():
            doc.reference.delete()
        print("Cleared existing region_snapshots.")

    imported, real_count, synthetic_count = _build_imported()
    all_regions = REGIONS + imported

    for region in all_regions:
        firestore_tool.write_document("region_snapshots", region["region_id"], _snapshot(region))
        label = region["country"]
        if region.get("disease"):
            label += f" / {region['disease']}"
        print(f"seeded {region['region_id']} ({label})")

    print(
        f"Done. {len(all_regions)} region snapshots in Firestore "
        f"({len(REGIONS)} hand-authored + {len(imported)} imported; "
        f"{real_count} real, {synthetic_count} synthetic survey rows)."
    )


if __name__ == "__main__":
    main()