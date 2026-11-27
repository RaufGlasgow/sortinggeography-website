#!/usr/bin/env python3
"""Generate and verify the English country sheets (Story 18.6, launch slice).

Reads the game repo via `git show <ref>:<path>` (nothing checked out) and
generates static HTML sheets at `countries/<iso>/index.html` for the 20 launch
countries, styled with the site's existing `style.css` and self-hosted fonts
(no Google Fonts, no third-party scripts).

Usage:
    python3 scripts/build_sheets.py --game ../Sorting-Geography [--ref origin/main]
    python3 scripts/build_sheets.py --check
    python3 scripts/build_sheets.py --check --game ../Sorting-Geography [--ref origin/main] [--countries-ref REF]

Modes:
  - Build (`--game PATH`): reads dataset.json, axes.yaml, fields.yaml,
    fact_consistency_allowlist.yaml, roster/countries.json, capital_name.csv,
    ne_50m_admin_0_countries.geojson, puzzle.dart, app_en.arb, version-log.json,
    and flag SVGs from the game repo at `--ref`; writes `countries/<iso>/index.html`,
    `images/flags/<iso>.svg`, and `src/sheets_manifest.json`. Refuses (exit 1)
    if any axis to be published is not `web_republish: allowed` or is in
    `src/sheet_deny_axes.json`.
  - Offline check (`--check`, used in CI): verifies every sheet against
    COUNTRIES, `src/sheet_deny_axes.json`, `src/sheets_manifest.json`, and
    `sitemap.xml` (allowed-only axes, exact dataset values, FR-55 notes,
    noindex,follow, self-canonical, no third-party scripts/fonts, no Daily).
  - Live game check (`--check --game PATH`): runs all offline checks plus
    re-checks against the game repo at `--ref` and compares COUNTRIES against
    `kCountrySheetCountries` in `app/lib/play/country_sheet_url.dart`.
"""
from __future__ import annotations

import csv
import datetime
import html
import io
import json
import math
import pathlib
import re
import subprocess
import sys
from urllib.parse import urlparse

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import build_launch  # noqa: E402
import build_seo  # noqa: E402

SITE = "https://sortinggeography.com"
DENY_FILE = "src/sheet_deny_axes.json"
MANIFEST_FILE = "src/sheets_manifest.json"
SHEET_URL_DART = "app/lib/play/country_sheet_url.dart"

# The ONE place the 20 launch countries live on the website (Story 18.6).
# `--check --game` compares this set with `kCountrySheetCountries` on the game
# repo and fails on any difference.
COUNTRIES: tuple[str, ...] = (
    "au", "br", "ca", "ch", "cn", "de", "eg", "fr", "gb", "il",
    "in", "it", "jp", "mx", "nl", "ru", "tr", "ua", "us", "za",
)

# Section layout for all 140 allowed, non-denied axes (Direction A).
SECTIONS: list[tuple[str, str, list[str]]] = [
    ("size", "Size, sea and borders", [
        "land_area_km2", "eez_area", "coastline_km", "coastline_per_land_area",
        "land_boundary_km", "land_neighbour_count", "time_zone_count",
    ]),
    ("height-water", "Height and water", [
        "highest_point_m", "mean_elevation_m", "mountain_share_pct", "mountain_area_km2",
        "max_distance_from_the_sea_km", "capital_distance_to_sea_km", "longest_river_km",
        "annual_precipitation", "renewable_water_internal", "freshwater_per_capita",
        "water_withdrawal_km3", "water_stress_pct", "water_used_for_farming_pct",
        "water_for_industry_pct",
    ]),
    ("land", "Land, forest and farming", [
        "forest_pct", "forest_area_km2", "primary_forest_area", "planted_forest_area_km2",
        "protected_forest_area_km2", "mangrove_area_km2", "grassland_share_pct",
        "herbaceous_wetland_area_km2", "barren_land_share", "built_up_area_share",
        "agricultural_land_pct", "arable_land_pct", "arable_land_per_person_ha",
        "permanent_cropland_pct", "pasture_share_of_land",
    ]),
    ("people", "People and cities", [
        "population", "population_density", "population_growth_rate", "pop_multiple_since_1950",
        "median_age", "life_expectancy", "life_expectancy_gap_fm", "fertility_rate",
        "birth_rate", "death_rate", "adolescent_fertility_rate", "mean_age_at_childbearing",
        "under5_mortality", "age_dependency_ratio", "female_share_of_population",
        "avg_household_size", "mean_years_schooling", "urban_population_pct",
        "urban_growth_rate", "capital_population_proper", "largest_city_population",
        "largest_city_share_of_population", "migrant_stock_total", "foreign_born_share_pct",
        "emigrants_abroad_total", "emigrants_abroad_pct_of_pop", "net_migration",
    ]),
    ("economy", "Economy and work", [
        "gdp_total_usd", "gdp_per_capita_usd", "gdp_growth_pct", "price_level_gdp_icp",
        "healthy_diet_cost_ppp", "bank_account_ownership_pct", "natural_resource_rents_pct",
        "forest_rents_pct", "labour_force_participation_pct", "female_share_of_workforce",
        "unemployment_pct", "youth_unemployment_pct", "self_employed_pct",
        "employment_in_agriculture", "employment_in_industry",
    ]),
    ("farming", "Farming and fishing", [
        "cereal_production_t", "cereal_yield_kg_ha", "fertiliser_use_kg_ha",
        "wheat_production_t", "maize_production_t", "potato_production_t",
        "tomato_production_t", "milk_production_t", "chicken_meat_t",
        "fish_capture_t", "fish_farmed_t", "cattle_count", "cattle_per_person",
        "pig_count", "goat_count", "duck_count", "sheep_per_person", "horses_per_person",
    ]),
    ("food", "Food supply", [
        "daily_calorie_supply", "meat_supply_kg", "pork_supply_kg", "poultry_supply_kg",
        "fish_seafood_kg", "milk_supply_kg", "eggs_supply_kg", "wheat_supply_kg",
        "rice_supply_kg", "maize_supply_kg", "potato_supply_kg", "vegetable_supply_kg",
        "fruit_supply_kg", "peanut_supply_kg", "sugar_supply_kg", "beer_supply_kg",
    ]),
    ("energy", "Energy and emissions", [
        "electricity_access_pct", "electricity_generated_kwh_per_person", "electricity_lost_pct",
        "energy_self_sufficiency_pct", "coal_share_of_electricity", "gas_share_of_electricity",
        "nuclear_share_of_electricity", "hydro_share_of_electricity", "wind_share_of_electricity",
        "solar_watts_per_person", "crude_oil_production_kbd", "gas_production_bcm",
        "petrol_litres_per_person_year", "co2_per_capita",
    ]),
    ("transport", "Transport", [
        "airports_count", "highest_airport_m", "roadways_km", "road_density_km_per_100km2",
        "railways_km", "rail_density_km_per_1000km2", "waterways_km", "merchant_marine_ships",
    ]),
    ("play", "Football and chess", [
        "football_matches_all_time", "football_home_win_pct", "football_goal_difference",
        "football_opponents_faced", "football_years_playing", "chess_grandmasters",
    ]),
]

# Rule ID -> axes involved, mirroring pipeline/src/sorting_geography_content/fact_consistency.py.
# Prefix rules `share_gt_100:<axis>` and `area_gt_land:<axis>` are resolved dynamically.
RULE_AXES: dict[str, tuple[str, ...]] = {
    "forest_plus_agri_gt_100": ("forest_pct", "agricultural_land_pct"),
    "forest_plus_agri_plus_barren_gt_102": ("forest_pct", "agricultural_land_pct", "barren_land_share"),
    "agri_plus_barren_gt_102": ("agricultural_land_pct", "barren_land_share"),
    "pasture_plus_barren_gt_102": ("pasture_share_of_land", "barren_land_share"),
    "land_cover_sum_gt_102": ("barren_land_share", "grassland_share_pct", "built_up_area_share"),
    "forest_plus_barren_gt_102": ("forest_pct", "barren_land_share"),
    "forest_plus_grassland_plus_barren_gt_102": ("forest_pct", "grassland_share_pct", "barren_land_share"),
    "agri_parts_vs_total": ("arable_land_pct", "permanent_cropland_pct", "pasture_share_of_land", "agricultural_land_pct"),
    "arable_gt_agri": ("arable_land_pct", "agricultural_land_pct"),
    "pasture_gt_agri": ("pasture_share_of_land", "agricultural_land_pct"),
    "arable_plus_permcrop_gt_agri": ("arable_land_pct", "permanent_cropland_pct", "agricultural_land_pct"),
    "planted_forest_gt_forest": ("planted_forest_area_km2", "forest_area_km2"),
    "primary_forest_gt_forest": ("primary_forest_area", "forest_area_km2"),
    "primary_plus_planted_gt_forest": ("primary_forest_area", "planted_forest_area_km2", "forest_area_km2"),
    "protected_forest_gt_forest": ("protected_forest_area_km2", "forest_area_km2"),
    "forest_pct_vs_area_over_land": ("forest_pct", "forest_area_km2", "land_area_km2"),
    "mountain_share_vs_area_over_land": ("mountain_share_pct", "mountain_area_km2", "land_area_km2"),
    "mangrove_gt_forest": ("mangrove_area_km2", "forest_area_km2"),
    "largest_city_gt_population": ("largest_city_population", "population"),
    "largest_city_gt_urban_pop": ("largest_city_population", "population", "urban_population_pct"),
    "capital_gt_population": ("capital_population_proper", "population"),
    "capital_gt_largest_city": ("capital_population_proper", "largest_city_population"),
    "capital_gt_urban_pop": ("capital_population_proper", "population", "urban_population_pct"),
    "migrant_stock_gt_population": ("migrant_stock_total", "population"),
    "foreign_born_share_vs_stock_over_pop": ("foreign_born_share_pct", "migrant_stock_total", "population"),
    "emigrants_pct_vs_total_over_pop": ("emigrants_abroad_pct_of_pop", "emigrants_abroad_total", "population"),
    "refugees_gt_migrant_stock": ("refugees_hosted", "migrant_stock_total"),
    "refugees_gt_10pct_pop": ("refugees_hosted", "population"),
    "cyclone_exposed_gt_population": ("cyclone_wind_exposed_people", "population"),
    "largest_city_share_vs_city_over_pop": ("largest_city_share_of_population", "largest_city_population", "population"),
    "density_vs_pop_over_land": ("population_density", "population", "land_area_km2"),
    "gdp_pc_vs_total_over_pop": ("gdp_per_capita_usd", "gdp_total_usd", "population"),
    "co2_pc_vs_total_over_pop": ("co2_per_capita", "co2_total_mt", "population"),
    "cattle_pp_vs_count_over_pop": ("cattle_per_person", "cattle_count", "population"),
    "arable_pp_vs_arable_pct_land_over_pop": ("arable_land_per_person_ha", "arable_land_pct", "land_area_km2", "population"),
    "freshwater_pc_vs_internal_over_pop": ("freshwater_per_capita", "renewable_water_internal", "population"),
    "road_density_vs_roads_over_land": ("road_density_km_per_100km2", "roadways_km", "land_area_km2"),
    "rail_density_vs_rail_over_land": ("rail_density_km_per_1000km2", "railways_km", "land_area_km2"),
    "coast_per_land_vs_coast_over_land": ("coastline_per_land_area", "coastline_km", "land_area_km2"),
    "pop_growth_vs_components": ("population_growth_rate", "birth_rate", "death_rate", "net_migration", "population"),
    "urban_99_growth_vs_pop_growth": ("urban_population_pct", "urban_growth_rate", "population_growth_rate"),
    "female_share_outside_40_60": ("female_share_of_population",),
    "eia_electricity_shares_gt_101": (
        "coal_share_of_electricity", "gas_share_of_electricity", "hydro_share_of_electricity",
        "nuclear_share_of_electricity", "wind_share_of_electricity",
    ),
    "hydro_plus_wind_gt_renewable_plus_10": ("hydro_share_of_electricity", "wind_share_of_electricity", "renewable_electricity_pct"),
    "fossil_nuclear_plus_renewable_gt_110": (
        "coal_share_of_electricity", "gas_share_of_electricity", "nuclear_share_of_electricity",
        "renewable_electricity_pct",
    ),
    "water_industry_plus_farming_gt_100_5": ("water_for_industry_pct", "water_used_for_farming_pct"),
    "employment_agri_plus_industry_gt_100": ("employment_in_agriculture", "employment_in_industry"),
    "land_neighbours_0_but_boundary_gt_0": ("land_neighbour_count", "land_boundary_km"),
    "land_neighbours_gt_0_but_boundary_0": ("land_neighbour_count", "land_boundary_km"),
    "maize_plus_wheat_gt_cereal": ("maize_production_t", "wheat_production_t", "cereal_production_t"),
    "maize_gt_cereal": ("maize_production_t", "cereal_production_t"),
    "wheat_gt_cereal": ("wheat_production_t", "cereal_production_t"),
    "pork_plus_poultry_gt_meat": ("pork_supply_kg", "poultry_supply_kg", "meat_supply_kg"),
    "football_opponents_gt_matches": ("football_opponents_faced", "football_matches_all_time"),
    "youth_unemployment_lt_0_8x_unemployment": ("youth_unemployment_pct", "unemployment_pct"),
}

# Plain-English FR-55 notes shown alongside clashing DEFINITION / YEAR measures
# (no internal axis ids shown to players). Falls back to the allowlist's `reason`
# if a future rule is added.
PLAIN_CONSISTENCY_NOTES: dict[str, tuple[str, str]] = {
    "forest_plus_agri_plus_barren_gt_102": (
        "Different definitions",
        "Forest cover and agricultural land (FAO land use, where agricultural land includes arid grazing land as permanent pasture) overlap with desert and bare rock (ESA WorldCover 2021 satellite land cover), so their shares can add to more than 100%.",
    ),
    "agri_plus_barren_gt_102": (
        "Different definitions",
        "Agricultural land (FAO land use, which includes arid grazing land as permanent pasture) overlaps with desert and bare rock (ESA WorldCover 2021 satellite land cover), so the same arid land is counted in both.",
    ),
    "pasture_plus_barren_gt_102": (
        "Different definitions",
        "Land used for grazing (FAOSTAT land use, which includes arid grazing land) overlaps with desert and bare rock (ESA WorldCover 2021 satellite land cover).",
    ),
    "share_gt_100:water_stress_pct": (
        "Why this can exceed 100%",
        "Fresh water already used up compares withdrawals with internal renewable water; it exceeds 100% where desalination, groundwater or water reuse supply demand.",
    ),
    "share_gt_100:energy_self_sufficiency_pct": (
        "Why this exceeds 100",
        "Energy made at home per 100 used divides total primary energy production by total consumption, so net energy exporters score above 100.",
    ),
    "foreign_born_share_vs_stock_over_pop": (
        "Different years",
        "People born abroad (%) divides UN DESA mid-2020 migrant stock by UN mid-2020 resident population, whereas Population is World Bank WDI 2023.",
    ),
    "emigrants_pct_vs_total_over_pop": (
        "Different years",
        "Share of its people living abroad (%) divides UN DESA mid-2020 emigrants by UN mid-2020 resident population, whereas Population is World Bank WDI 2023.",
    ),
    "pop_growth_vs_components": (
        "Different sources and years",
        "Births and deaths come from CIA World Factbook 2024 (2023 estimates), while population growth and net migration come from UN World Population Prospects 2024 via World Bank WDI (2023).",
    ),
    "largest_city_gt_urban_pop": (
        "Different definitions",
        "Biggest city uses UN DESA 2025 Degree of Urbanisation city boundaries, whereas urban population (%) uses the country's own national administrative definition (World Bank WDI 2023).",
    ),
    "capital_gt_urban_pop": (
        "Different definitions",
        "Capital population uses UN DESA 2025 Degree of Urbanisation city boundaries (mid-2025), whereas urban population (%) uses national statistical definitions (World Bank WDI 2023).",
    ),
    "land_neighbours_0_but_boundary_gt_0": (
        "Different definitions",
        "Land borders (km) from CIA World Factbook 2024 counts boundaries with non-sovereign territories, whereas Number of land borders from GeoNames counts sovereign neighbours only.",
    ),
    "forest_pct_vs_area_over_land": (
        "Different years",
        "Forest cover (%) and forest area are FAO 2020 figures using 2020 land area, whereas Land area is World Bank WDI 2023.",
    ),
    "maize_plus_wheat_gt_cereal": (
        "Different years",
        "Wheat grown is from 2022 while corn grown and cereal production are from 2023, so their sum can exceed 2023 total cereals.",
    ),
    "wheat_gt_cereal": (
        "Different years",
        "Wheat grown is from 2022 while cereal production is from 2023.",
    ),
}

SOURCE_RULES: list[tuple[str, str]] = [
    (r"^CIA World Factbook 2024", "CIA World Factbook, 2024 edition"),
    (r"^Derived: CIA World Factbook 2024", "CIA World Factbook and World Bank (derived)"),
    (r"^Derived: GeoNames capital", "GeoNames and Natural Earth (derived)"),
    (r"^Derived: Natural Earth", "Natural Earth (derived)"),
    (r"^Derived: UN WUP 2025", "UN DESA WUP 2025 and World Bank (derived)"),
    (r"^ESA WorldCover 2021", "ESA WorldCover 2021, via FAOSTAT"),
    (r"^FAO 20\d\d \(via World Bank WDI", "FAO, via World Bank WDI"),
    (r"^FAO AQUASTAT", "FAO AQUASTAT, via World Bank WDI"),
    (r"^FAO Food Balance Sheets.*via Our World in Data", "FAO Food Balance Sheets, via Our World in Data"),
    (r"^FAO Food Balance Sheets", "FAO Food Balance Sheets"),
    (r"^FAO Global Forest Resources Assessment 2025", "FAO Global Forest Resources Assessment 2025"),
    (r"^FAO Global Forest Resources Assessment 2020", "FAO Global Forest Resources Assessment 2020"),
    (r"^FAOSTAT Environment/Land Cover.*ESA WorldCover", "ESA WorldCover 2021, via FAOSTAT"),
    (r"^FAOSTAT QCL.*via Our World in Data", "FAOSTAT, via Our World in Data"),
    (r"^FAOSTAT", "FAO, FAOSTAT"),
    (r"^GeoNames", "GeoNames"),
    (r"^IANA Time Zone Database", "IANA Time Zone Database 2026a"),
    (r"^ILO\b.*via World Bank WDI", "ILO, via World Bank WDI"),
    (r"^JRC Global Human Settlement Layer", "EU JRC Global Human Settlement Layer"),
    (r"^Marine Regions World EEZ v12", "Marine Regions, World EEZ v12"),
    (r"^Men's international football results", "International football results (martj42)"),
    (r"^Natural Earth 1:50m", "Natural Earth 1:50m"),
    (r"^Our World in Data \(Global Carbon Project\)", "Global Carbon Project, via Our World in Data"),
    (r"^OurAirports", "OurAirports"),
    (r"^UN DESA International Migrant Stock 2024", "UN DESA International Migrant Stock 2024"),
    (r"^UN DESA Population Division, Database on Household Size", "UN DESA Household Size and Composition"),
    (r"^UN DESA World Urbanization Prospects 2025", "UN DESA World Urbanization Prospects 2025"),
    (r"^UN IGME", "UN IGME, via World Bank WDI"),
    (r"^UN WPP 2024 via Our World in Data", "UN World Population Prospects 2024, via Our World in Data"),
    (r"^UN World Population Prospects 2024.*via World Bank WDI", "UN World Population Prospects 2024, via World Bank WDI"),
    (r"^UN World Population Prospects 2024", "UN World Population Prospects 2024"),
    (r"^UN World Urbanization Prospects 2025.*via World Bank WDI", "UN DESA WUP 2025, via World Bank WDI"),
    (r"^UNDP Human Development Report 2025", "UNDP Human Development Report 2025"),
    (r"^US Energy Information Administration", "US Energy Information Administration"),
    (r"^Wikidata", "Wikidata"),
    (r"^World Bank / ESMAP", "World Bank / ESMAP, via World Bank WDI"),
    (r"^World Bank Food Prices for Nutrition", "World Bank Food Prices for Nutrition"),
    (r"^World Bank Global Findex 2024", "World Bank Global Findex 2024"),
    (r"^World Bank International Comparison Program 2021", "World Bank ICP 2021"),
    (r"^World Bank\b", "World Bank, World Development Indicators"),
]

# Custom locator map frames for countries with distant overseas territories or
# antimeridian crossings so every map is well-framed and honest in its caption.
# Format: ISO -> (lon0, lon1, lat0, lat1, shift_mode, caption_note)
# shift_mode: None | "east" (lon < -30 -> +360, for RU) | "west" (lon > 100 -> -360, for US)
MAP_FRAMES: dict[str, tuple[float, float, float, float, str | None, str]] = {
    "AU": (108.0, 159.0, -45.5, -8.5, None, "Mainland Australia and Tasmania shown."),
    "CA": (-146.0, -48.0, 40.0, 84.0, None, "Canada as the game counts it."),
    "FR": (-8.5, 13.0, 40.5, 52.2, None, "Metropolitan France and Corsica shown; figures count the whole country."),
    "NL": (1.5, 9.0, 49.8, 54.5, None, "European Netherlands shown."),
    "RU": (14.0, 196.0, 38.0, 80.5, "east", "Russia as the game counts it."),
    "US": (-172.0, -62.0, 17.0, 73.0, "west", "The 50 US states shown."),
    "ZA": (12.0, 37.5, -36.5, -20.5, None, "Mainland South Africa shown."),
}

COUNTRY_CONST = re.compile(
    r"^\s*const\s+Set<String>\s+kCountrySheetCountries\s*=\s*<String>\{([^}]*)\}\s*;",
    re.M,
)
ISO_RE = re.compile(r"[a-z]{2}")
THIRD_PARTY_FONT_RE = re.compile(
    r"fonts\.googleapis\.com|fonts\.gstatic\.com|use\.typekit\.net|fonts\.bunny\.net",
    re.I,
)
DAILY_LEAK_RE = re.compile(
    r"\btoday'?s\s+daily\b|\bdaily\s+(?:answer|question|puzzle|challenge)\b",
    re.I,
)


class SheetError(Exception):
    pass


# ---------------------------------------------------------------------------
# Git helpers (read game repo without checking anything out)
# ---------------------------------------------------------------------------

def require_ref(game: pathlib.Path, ref: str) -> None:
    r = subprocess.run(
        ["git", "-C", str(game), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise SheetError(f"{game}: not a git repo with a commit at {ref!r}")


def game_show(game: pathlib.Path, ref: str, path: str) -> str | None:
    r = subprocess.run(["git", "-C", str(game), "show", f"{ref}:{path}"], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def game_show_bytes(game: pathlib.Path, ref: str, path: str) -> bytes | None:
    r = subprocess.run(["git", "-C", str(game), "show", f"{ref}:{path}"], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def parse_game_countries(dart: str) -> list[str] | None:
    """Parse `const Set<String> kCountrySheetCountries = <String>{'au', ...};`."""
    found = COUNTRY_CONST.findall(dart)
    if len(found) != 1:
        return None
    body = found[0].strip()
    if not body:
        return []
    parts = [p.strip() for p in body.rstrip(",").split(",")]
    isos: list[str] = []
    for p in parts:
        m = re.fullmatch(r"'([^']*)'", p)
        if not m or not ISO_RE.fullmatch(m.group(1)) or m.group(1) in isos:
            return None
        isos.append(m.group(1))
    return isos


# ---------------------------------------------------------------------------
# Stdlib YAML parsers for axes.yaml, fields.yaml and fact_consistency_allowlist.yaml
# (no PyYAML required in CI)
# ---------------------------------------------------------------------------

def _strip_yaml_scalar(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('"'):
        m = re.match(r'^"((?:[^"\\]|\\.)*)"', raw)
        return m.group(1) if m else raw
    if raw.startswith("'"):
        m = re.match(r"^'([^']*)'", raw)
        return m.group(1) if m else raw
    return raw.split("#", 1)[0].strip()


def parse_yaml_top_entries(text: str, section: str) -> dict[str, dict[str, str]]:
    """Parse top-level entries under `section:` in axes.yaml or fields.yaml."""
    out: dict[str, dict[str, str]] = {}
    in_sec = False
    cur: str | None = None
    for line in text.splitlines():
        if not in_sec:
            if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", line):
                in_sec = True
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:\s*", line):
            break
        m = re.match(r"^  ([A-Za-z0-9_]+):\s*(#.*)?$", line)
        if m:
            name = m.group(1)
            if name.startswith("_"):
                cur = None
            else:
                cur = name
                out[cur] = {}
            continue
        if cur is not None:
            kv = re.match(r"^    ([a-z_]+):\s*(.*)$", line)
            if kv:
                out[cur][kv.group(1)] = _strip_yaml_scalar(kv.group(2))
    return out


def parse_web_republish(axes_yaml: str, fields_yaml: str) -> dict[str, str]:
    """Return axis_id -> web_republish ('allowed' | 'flag' | 'forbidden'). Fail closed."""
    axes = parse_yaml_top_entries(axes_yaml, "axes")
    fields = {
        k: v for k, v in parse_yaml_top_entries(fields_yaml, "fields").items()
        if v.get("role") == "sort_axis"
    }
    overlap = set(axes) & set(fields)
    if overlap:
        raise SheetError(f"duplicate sort axes across axes.yaml and fields.yaml: {sorted(overlap)}")
    combined = {**axes, **fields}
    if not combined:
        raise SheetError("no sort axes found in axes.yaml / fields.yaml")
    policy: dict[str, str] = {}
    for ax, cfg in sorted(combined.items()):
        wr = cfg.get("web_republish", "")
        if wr not in {"allowed", "flag", "forbidden"}:
            raise SheetError(f"{ax}: missing or invalid web_republish={wr!r} (Story 18.7)")
        policy[ax] = wr
    return policy


def parse_allowlist_yaml(text: str) -> list[dict]:
    """Parse pipeline/fact_consistency_allowlist.yaml entries using stdlib only."""
    entries: list[dict] = []
    in_entries = False
    cur: dict | None = None
    block_key: str | None = None
    block_lines: list[str] = []

    def finish_block() -> None:
        nonlocal block_key, block_lines
        if cur is not None and block_key is not None:
            cur[block_key] = " ".join(ln.strip() for ln in block_lines if ln.strip())
        block_key = None
        block_lines = []

    for line in text.splitlines():
        if not in_entries:
            if re.match(r"^entries:\s*(#.*)?$", line):
                in_entries = True
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:\s*", line):
            finish_block()
            break
        if block_key is not None:
            if line.startswith("      ") or not line.strip():
                block_lines.append(line)
                continue
            finish_block()
        m_item = re.match(r"^  -\s+([a-z_]+):\s*(.*)$", line)
        if m_item:
            if cur is not None:
                entries.append(cur)
            cur = {}
            k, v = m_item.group(1), m_item.group(2)
            cur[k] = _strip_yaml_scalar(v)
            continue
        if cur is not None:
            m_kv = re.match(r"^    ([a-z_]+):\s*(.*)$", line)
            if m_kv:
                k, raw_v = m_kv.group(1), m_kv.group(2).strip()
                if raw_v in (">-", ">", "|-", "|"):
                    block_key = k
                    block_lines = []
                elif raw_v.startswith("[") and raw_v.endswith("]"):
                    inner = raw_v[1:-1].strip()
                    cur[k] = [p.strip().strip("'\"") for p in inner.split(",") if p.strip()] if inner else []
                else:
                    cur[k] = _strip_yaml_scalar(raw_v)
    finish_block()
    if cur is not None:
        entries.append(cur)

    for e in entries:
        verdict = e.get("verdict")
        if verdict not in {"DEFINITION", "YEAR"}:
            raise SheetError(f"fact_consistency_allowlist.yaml: invalid verdict {verdict!r} on rule {e.get('rule')!r}")
        if not e.get("reason"):
            raise SheetError(f"fact_consistency_allowlist.yaml: missing reason on rule {e.get('rule')!r}")
    return entries


def axes_for_rule(rule_id: str) -> tuple[str, ...]:
    if rule_id in RULE_AXES:
        return RULE_AXES[rule_id]
    if rule_id.startswith("share_gt_100:"):
        return (rule_id.split(":", 1)[1],)
    if rule_id.startswith("area_gt_land:"):
        return (rule_id.split(":", 1)[1], "land_area_km2")
    raise SheetError(f"fact_consistency_allowlist.yaml: unknown rule_id {rule_id!r}; add it to RULE_AXES")


def load_deny_list(root: pathlib.Path = ROOT) -> dict[str, str]:
    p = root / DENY_FILE
    if not p.is_file():
        raise SheetError(f"{DENY_FILE} is missing")
    data = json.loads(p.read_text(encoding="utf-8"))
    denied = data.get("denied")
    if not isinstance(denied, list):
        raise SheetError(f"{DENY_FILE}: 'denied' must be a list")
    out: dict[str, str] = {}
    for item in denied:
        if not isinstance(item, dict) or not item.get("axis") or not item.get("reason"):
            raise SheetError(f"{DENY_FILE}: each entry needs 'axis' and 'reason'")
        out[str(item["axis"])] = str(item["reason"])
    return out


# ---------------------------------------------------------------------------
# Formatting & metadata helpers (matching Sally's Direction A)
# ---------------------------------------------------------------------------

def ordinal(n: int) -> str:
    s = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{s}"


def split_name(label: str) -> tuple[str, str]:
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", label)
    return (m.group(1), m.group(2)) if m else (label, "")


def fmt_plain(v: float | int, unit: str) -> str:
    """Plain-text formatted value (uses ASCII '-' before HTML conversion to &minus;)."""
    if unit.startswith("%"):
        if v == 0:
            return "0%"
        if abs(v) < 0.01:
            return f"{v:.3f}%"
        if abs(v) < 0.1:
            return f"{v:.2f}%"
        return f"{v:.1f}%"
    if abs(v) >= 1_000_000_000_000:
        return f"{v / 1e12:,.2f} trillion"
    if abs(v) >= 10_000_000_000 and unit == "US$":
        return f"{v / 1e9:,.1f} billion"
    if isinstance(v, int) or float(v).is_integer():
        return f"{int(round(v)):,}"
    if abs(v) >= 100:
        return f"{round(v):,}"
    if unit == "$ a person":
        return f"{v:.2f}"
    if 0 < abs(v) < 0.01:
        return f"{v:.4f}".rstrip("0").rstrip(".")
    if 0 < abs(v) < 0.1:
        return f"{v:.3f}".rstrip("0").rstrip(".")
    if 0 < abs(v) < 1:
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return f"{v:.1f}"


def fmt_html(v: float | int, unit: str) -> str:
    return fmt_plain(v, unit).replace("-", "&minus;")


def short_source(decl: str) -> str:
    for pat, name in SOURCE_RULES:
        if re.search(pat, decl):
            return name
    raise SheetError(f"no short source mapping for declared_source: {decl!r}")


def host_label(url: str) -> str:
    h = urlparse(url).netloc.replace("www.", "")
    if h == "web.archive.org":
        return "web.archive.org (cia.gov)"
    return h


def format_version_date(iso_date: str) -> str:
    d = datetime.date.fromisoformat(iso_date)
    return f"{d.day} {d.strftime('%B')} {d.year}"


def ic_globe(cls: str = "ic") -> str:
    return (
        f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">'
        '<circle cx="12" cy="12" r="9.5"></circle>'
        '<path d="M2.5 12h19M12 2.5c2.6 2.8 3.9 6 3.9 9.5s-1.3 6.7-3.9 9.5c-2.6-2.8-3.9-6-3.9-9.5s1.3-6.7 3.9-9.5z"></path>'
        '</svg>'
    )


def ic_back() -> str:
    return (
        '<svg viewBox="0 0 24 24" class="ic" aria-hidden="true">'
        '<path d="M15 6l-6 6 6 6" fill="none" stroke="currentColor" stroke-width="2" '
        'stroke-linecap="round" stroke-linejoin="round"></path></svg>'
    )


def flag_img(iso: str, cls: str = "", w: int = 32, h: int = 24, lazy: bool = True) -> str:
    extra = f" {cls}" if cls else ""
    ld = ' loading="lazy"' if lazy else ""
    return f'<img class="flag{extra}" src="../../images/flags/{iso.lower()}.svg" alt="" width="{w}" height="{h}"{ld}>'


# ---------------------------------------------------------------------------
# Locator map SVG from Natural Earth 1:50m (public domain)
# ---------------------------------------------------------------------------

def _shift_lon(lon: float, mode: str | None) -> float:
    if mode == "east" and lon < -30.0:
        return lon + 360.0
    if mode == "west" and lon > 100.0:
        return lon - 360.0
    return lon


def _feature_polys(feat: dict) -> list:
    g = feat["geometry"]
    return g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]


def _auto_frame(feats: list[dict], iso: str) -> tuple[float, float, float, float, str | None, str]:
    if iso in MAP_FRAMES:
        return MAP_FRAMES[iso]
    # Pick non-dependency features when available, and frame around the main
    # landmass + nearby islands within 15 deg.
    primary = [f for f in feats if f["properties"].get("TYPE") != "Dependency"] or feats
    all_polys = [poly for f in primary for poly in _feature_polys(f)]
    bboxes = []
    for poly in all_polys:
        ring = poly[0]
        lons = [pt[0] for pt in ring]
        lats = [pt[1] for pt in ring]
        span = (max(lons) - min(lons)) * (max(lats) - min(lats))
        bboxes.append((span, min(lons), max(lons), min(lats), max(lats)))
    bboxes.sort(reverse=True)
    _, m_lon0, m_lon1, m_lat0, m_lat1 = bboxes[0]
    keep = [b for b in bboxes if b[1] <= m_lon1 + 12 and b[2] >= m_lon0 - 12 and b[3] <= m_lat1 + 12 and b[4] >= m_lat0 - 12]
    lon0 = min(b[1] for b in keep)
    lon1 = max(b[2] for b in keep)
    lat0 = min(b[3] for b in keep)
    lat1 = max(b[4] for b in keep)
    mid_lat = (lat0 + lat1) / 2.0
    cos_lat = max(0.25, math.cos(math.radians(mid_lat)))
    w_deg = max(lon1 - lon0, 3.0)
    h_deg = max(lat1 - lat0, 2.0)
    pad_lon = max(w_deg * 0.35, 2.0)
    pad_lat = max(h_deg * 0.35, 1.5)
    lon0 -= pad_lon
    lon1 += pad_lon
    lat0 = max(-85.0, lat0 - pad_lat)
    lat1 = min(85.0, lat1 + pad_lat)
    # Adjust aspect ratio to ~1.85:1 (560x300) matching Sally's locator map.
    target = 560.0 / 300.0
    cur_w = (lon1 - lon0) * cos_lat
    cur_h = lat1 - lat0
    if cur_w / cur_h < target:
        need = target * cur_h / cos_lat
        delta = (need - (lon1 - lon0)) / 2.0
        lon0 -= delta
        lon1 += delta
    else:
        need = cur_w / target
        delta = (need - (lat1 - lat0)) / 2.0
        lat0 = max(-85.0, lat0 - delta)
        lat1 = min(85.0, lat1 + delta)
    return (lon0, lon1, lat0, lat1, None, "")


def render_locator_map(
    iso: str,
    cname: str,
    capital: str | None,
    cap_lat: float | None,
    cap_lon: float | None,
    geo: dict,
) -> str:
    iso_feats = [f for f in geo["features"] if f["properties"].get("ISO_A2_EH") == iso]
    if not iso_feats:
        raise SheetError(f"{iso}: no feature in Natural Earth GeoJSON")
    lon0, lon1, lat0, lat1, shift_mode, frame_note = _auto_frame(iso_feats, iso)
    mid_lat = (lat0 + lat1) / 2.0
    cos_lat = max(0.25, math.cos(math.radians(mid_lat)))
    raw_w = (lon1 - lon0) * cos_lat
    raw_h = lat1 - lat0
    W = 560.0
    H = max(220.0, min(360.0, round(W * raw_h / raw_w)))
    sx = W / (lon1 - lon0)
    sy = H / (lat1 - lat0)

    def proj(lon: float, lat: float) -> tuple[float, float]:
        slon = _shift_lon(lon, shift_mode)
        return ((slon - lon0) * sx, (lat1 - lat) * sy)

    def ring_d(ring: list) -> str:
        pts: list[tuple[float, float]] = []
        last: tuple[float, float] | None = None
        for lon, lat in ring:
            x, y = proj(lon, lat)
            in_view = -20.0 <= x <= W + 20.0 and -20.0 <= y <= H + 20.0
            tol = 1.4 if in_view else 18.0
            if last is not None and abs(x - last[0]) < tol and abs(y - last[1]) < tol:
                continue
            pts.append((x, y))
            last = (x, y)
        if len(pts) < 3:
            return ""
        return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"

    def feat_d(feat: dict) -> str:
        out = []
        for poly in _feature_polys(feat):
            ring = poly[0]
            slons = [_shift_lon(pt[0], shift_mode) for pt in ring]
            lats = [pt[1] for pt in ring]
            # Skip rings that wrap across the frame edges due to antimeridian jump.
            if max(slons) - min(slons) > 180.0:
                continue
            if max(slons) < lon0 - 2 or min(slons) > lon1 + 2 or max(lats) < lat0 - 2 or min(lats) > lat1 + 2:
                continue
            d = ring_d(ring)
            if d:
                out.append(d)
        return "".join(out)

    others: list[str] = []
    target_paths: list[str] = []
    for feat in geo["features"]:
        code = feat["properties"].get("ISO_A2_EH")
        d = feat_d(feat)
        if not d:
            continue
        if code == iso and (feat["properties"].get("TYPE") != "Dependency" or iso not in {"AU"}):
            target_paths.append(d)
        else:
            others.append(d)

    # Graticule lines spaced cleanly for the frame size.
    step = 20 if (lon1 - lon0) > 70 else 10 if (lon1 - lon0) > 25 else 5 if (lon1 - lon0) > 10 else 2
    grat: list[str] = []
    g_lon = int(math.floor(lon0 / step) * step)
    while g_lon <= lon1:
        x = (g_lon - lon0) * sx
        if 0 < x < W:
            grat.append(f"M{x:.1f} 0V{H:.0f}")
        g_lon += step
    g_lat = int(math.floor(lat0 / step) * step)
    while g_lat <= lat1:
        y = (lat1 - g_lat) * sy
        if 0 < y < H:
            grat.append(f"M0 {y:.1f}H{W:.0f}")
        g_lat += step

    cap_svg = ""
    if capital and cap_lat is not None and cap_lon is not None:
        cx, cy = proj(cap_lon, cap_lat)
        if 8 <= cx <= W - 8 and 8 <= cy <= H - 8:
            anchor = "end" if cx > W * 0.65 else "start"
            dx = -8 if anchor == "end" else 8
            cap_svg = (
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4" '
                'style="fill:var(--map-sea);stroke:var(--map-pt);stroke-width:2"></circle>'
                f'<text x="{cx + dx:.1f}" y="{cy + 4:.1f}" text-anchor="{anchor}" '
                f'class="m-lab m-small">{html.escape(capital)}</text>'
            )

    cap_text = f"{frame_note} " if frame_note else f"{cname} as the game counts it. "
    aria = f"Locator map of {cname}" + (f" showing {capital}" if capital else "") + "."
    return (
        f'<figure class="map a-map">'
        f'<svg viewBox="0 0 {W:.0f} {H:.0f}" role="img" aria-label="{html.escape(aria, quote=True)}">'
        f'<rect width="{W:.0f}" height="{H:.0f}" style="fill:var(--map-sea)"></rect>'
        f'<path d="{"".join(grat)}" style="fill:none;stroke:var(--map-grid);stroke-width:.8"></path>'
        f'<path d="{"".join(others)}" style="fill:var(--map-land);stroke:var(--map-edge);stroke-width:.8;stroke-linejoin:round"></path>'
        f'<path d="{"".join(target_paths)}" style="fill:var(--map-pt);stroke:var(--map-pt);stroke-width:1.2;stroke-linejoin:round"></path>'
        f'{cap_svg}'
        '</svg>'
        f'<figcaption class="mapcap">{html.escape(cap_text)}Map: Natural Earth 1:50m, public domain.</figcaption>'
        '</figure>'
    )


# ---------------------------------------------------------------------------
# Game bundle loader + fact / ranking computation
# ---------------------------------------------------------------------------

def load_game_bundle(game: pathlib.Path, ref: str, deny_list: dict[str, str]) -> dict:
    require_ref(game, ref)
    required_paths = [
        "pipeline/content/dataset.json",
        "pipeline/content/version-log.json",
        "pipeline/roster/countries.json",
        "pipeline/axes.yaml",
        "pipeline/fields.yaml",
        "pipeline/fact_consistency_allowlist.yaml",
        "pipeline/sources/geometry/ne_50m_admin_0_countries.geojson",
        "pipeline/sources/geonames/capital_name.csv",
        "app/lib/play/puzzle.dart",
        "packages/sort_platform/l10n/app_en.arb",
    ]
    raw: dict[str, str] = {}
    for p in required_paths:
        txt = game_show(game, ref, p)
        if txt is None:
            raise SheetError(f"{game}: cannot read {p} at {ref}")
        raw[p] = txt

    dataset = json.loads(raw["pipeline/content/dataset.json"])
    version_log = json.loads(raw["pipeline/content/version-log.json"])
    roster = json.loads(raw["pipeline/roster/countries.json"])["countries"]
    policy = parse_web_republish(raw["pipeline/axes.yaml"], raw["pipeline/fields.yaml"])
    allowlist = parse_allowlist_yaml(raw["pipeline/fact_consistency_allowlist.yaml"])
    geo = json.loads(raw["pipeline/sources/geometry/ne_50m_admin_0_countries.geojson"])
    capitals = {row["iso_alpha2"]: row["value"] for row in csv.DictReader(io.StringIO(raw["pipeline/sources/geonames/capital_name.csv"]))}
    arb = json.loads(raw["packages/sort_platform/l10n/app_en.arb"])
    axis_keys = dict(re.findall(
        r"'([a-z0-9_]+)':\s*PuzzleAxis\(\s*nameUnitsKey:\s*'([A-Za-z0-9]+)'",
        raw["app/lib/play/puzzle.dart"],
    ))

    # Every dataset axis must have a policy entry (fail closed).
    ds_axes = set(dataset["axes"])
    missing_policy = sorted(ds_axes - set(policy))
    if missing_policy:
        raise SheetError(f"dataset axes missing web_republish policy at {ref}: {missing_policy}")

    # Resolve dataset version number and date from version-log.json.
    version = dataset["version"]
    vm = re.search(r"v(\d+)", version)
    if not vm:
        raise SheetError(f"unreadable dataset version: {version!r}")
    vnum = int(vm.group(1))
    vlog_match = [e for e in version_log if e.get("version") == version]
    if not vlog_match:
        raise SheetError(f"version-log.json has no entry for {version!r}")
    vdate = format_version_date(vlog_match[-1]["at"])

    # Validate allowlist rule IDs up front (fail closed).
    for entry in allowlist:
        axes_for_rule(entry["rule"])

    # Determine published axes: strictly web_republish == "allowed" and not denied.
    published_axes = sorted(
        ax for ax in ds_axes
        if policy[ax] == "allowed" and ax not in deny_list
    )

    # Check every published axis has a display title in app_en.arb.
    for ax in published_axes:
        key = axis_keys.get(ax)
        if not key or key not in arb:
            raise SheetError(f"{ax}: missing display label in puzzle.dart / app_en.arb")

    return {
        "dataset": dataset,
        "version": version,
        "vnum": vnum,
        "vdate": vdate,
        "roster": roster,
        "policy": policy,
        "allowlist": allowlist,
        "geo": geo,
        "capitals": capitals,
        "arb": arb,
        "axis_keys": axis_keys,
        "published_axes": published_axes,
        "deny_list": deny_list,
    }


def _axis_default_ver(axis_recs: dict) -> dict:
    for rec in axis_recs.values():
        if isinstance(rec, dict) and rec.get("verification"):
            return rec["verification"]
    raise SheetError("axis has no verification receipt")


def compute_axis_facts(bundle: dict, iso_upper: str) -> dict[str, dict]:
    """Compute value, rank, ties, source, year and URL for every published axis."""
    ds_axes = bundle["dataset"]["axes"]
    policy = bundle["policy"]
    deny_list = bundle["deny_list"]
    arb = bundle["arb"]
    axis_keys = bundle["axis_keys"]

    facts: dict[str, dict] = {}
    for ax in bundle["published_axes"]:
        # Hard refusal guard: never render an unallowed or denied axis.
        if policy.get(ax) != "allowed":
            raise SheetError(f"refusing to publish axis {ax!r}: web_republish={policy.get(ax)!r} (must be 'allowed')")
        if ax in deny_list:
            raise SheetError(f"refusing to publish denied axis {ax!r}: {deny_list[ax]}")

        cs = ds_axes[ax]
        label = arb[axis_keys[ax]]
        name, unit = split_name(label)
        unit_txt = unit[1:].strip() if unit.startswith("%") else unit
        vals = sorted(
            (c["sort_value"] for c in cs.values() if isinstance(c, dict) and not isinstance(c.get("sort_value"), dict)),
            reverse=True,
        )
        rec = cs.get(iso_upper)
        default_ver = _axis_default_ver(cs)
        if rec is None or isinstance(rec.get("sort_value"), dict):
            ver = default_ver
            facts[ax] = {
                "ax": ax,
                "name": name,
                "unit": unit,
                "unit_txt": unit_txt,
                "n": len(vals),
                "nodata": True,
                "val_plain": "No data",
                "val_html": "No data",
                "rank": None,
                "tied": 0,
                "rank_txt": "Not ranked",
                "src": short_source(ver["declared_source"]),
                "year": str(ver.get("vintage", "")),
                "url": str(ver.get("source_url", "")),
            }
            continue

        v = rec["sort_value"]
        ver = rec["verification"]
        rank = 1 + sum(1 for x in vals if x > v)
        tied = sum(1 for x in vals if x == v) - 1
        rank_txt = f"{ordinal(rank)} of {len(vals)}" + (f", tied with {tied}" if tied else "")
        facts[ax] = {
            "ax": ax,
            "name": name,
            "unit": unit,
            "unit_txt": unit_txt,
            "n": len(vals),
            "nodata": False,
            "v": v,
            "val_plain": fmt_plain(v, unit),
            "val_html": fmt_html(v, unit),
            "rank": rank,
            "tied": tied,
            "rank_txt": rank_txt,
            "src": short_source(ver["declared_source"]),
            "year": str(ver.get("vintage", "")),
            "url": str(ver.get("source_url", "")),
        }
    return facts


def active_consistency_rules(bundle: dict, iso_upper: str, facts: dict[str, dict]) -> list[dict]:
    """FR-55: every DEFINITION / YEAR allowlist rule whose axes are all shown with data on this sheet."""
    out: list[dict] = []
    for entry in bundle["allowlist"]:
        rule_id = entry["rule"]
        verdict = entry["verdict"]
        applies = False
        if entry.get("group") == "*":
            applies = True
        elif entry.get("country") == iso_upper:
            applies = True
        elif iso_upper in (entry.get("countries") or []):
            applies = True
        if not applies:
            continue

        rule_axes = axes_for_rule(rule_id)
        if not all(ax in facts and not facts[ax]["nodata"] for ax in rule_axes):
            continue
        # For rule-wide `share_gt_100:<axis>` entries, only emit the note on countries where value > 100.
        if rule_id.startswith("share_gt_100:") and facts[rule_axes[0]]["v"] <= 100.0:
            continue

        if rule_id in PLAIN_CONSISTENCY_NOTES:
            note_label, note_text = PLAIN_CONSISTENCY_NOTES[rule_id]
        else:
            note_label = "Different years" if verdict == "YEAR" else "Different definitions"
            note_text = entry["reason"]

        out.append({
            "rule": rule_id,
            "verdict": verdict,
            "axes": list(rule_axes),
            "label": note_label,
            "note": note_text,
        })
    return out


def sorted_neighbours(bundle: dict, ax: str, iso_upper: str) -> list[tuple[int, str, float | int]]:
    cs = bundle["dataset"]["axes"][ax]
    rows = sorted(
        ((c["sort_value"], i) for i, c in cs.items() if isinstance(c, dict) and not isinstance(c.get("sort_value"), dict)),
        key=lambda t: (-t[0], t[1]),
    )
    idx = [i for _, i in rows].index(iso_upper)
    if idx == 0:
        picks = [0, 1, 2]
    elif idx == len(rows) - 1:
        picks = [len(rows) - 3, len(rows) - 2, len(rows) - 1]
    else:
        picks = [idx - 1, idx, idx + 1]
    out = []
    for j in picks:
        if 0 <= j < len(rows):
            v, i = rows[j]
            rank = 1 + sum(1 for x, _ in rows if x > v)
            out.append((rank, i, v))
    return out


def standout_facts(facts: dict[str, dict]) -> list[dict]:
    """Top 4 axes where the country stands out (best rank/n ratio, skipping ties)."""
    clean = [f for f in facts.values() if not f["nodata"] and f["tied"] == 0]
    if len(clean) < 4:
        clean = [f for f in facts.values() if not f["nodata"] and f["tied"] <= 2]
    clean.sort(key=lambda f: (f["rank"] / f["n"], f["rank"], f["ax"]))
    return clean[:4]


def sections_for(published_axes: list[str]) -> list[tuple[str, str, list[str]]]:
    pub = set(published_axes)
    used: set[str] = set()
    out: list[tuple[str, str, list[str]]] = []
    for key, title, axs in SECTIONS:
        kept = [a for a in axs if a in pub]
        if kept:
            out.append((key, title, kept))
            used.update(kept)
    leftover = sorted(pub - used)
    if leftover:
        out.append(("other", "Other measures", leftover))
    return out


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------

# Non-sovereign territory codes that appear in GeoNames `land_neighbours`
# outside the 195-country roster (e.g. Brazil borders French Guiana, China
# borders Hong Kong and Macao).
TERRITORY_NAMES: dict[str, str] = {
    "EH": "Western Sahara",
    "GF": "French Guiana",
    "GI": "Gibraltar",
    "HK": "Hong Kong",
    "MF": "Saint Martin",
    "MO": "Macao",
    "SX": "Sint Maarten",
    "XK": "Kosovo",
}


def neighbour_name(code: str, roster: dict, geo: dict) -> str:
    if code in roster:
        return roster[code]["name"]
    if code in TERRITORY_NAMES:
        return TERRITORY_NAMES[code]
    for feat in geo["features"]:
        if feat["properties"].get("ISO_A2_EH") == code:
            return str(feat["properties"]["NAME"])
    raise SheetError(f"unknown land_neighbours territory code {code!r}")


def render_sheet(
    bundle: dict,
    iso_lower: str,
    root: pathlib.Path,
) -> tuple[str, dict, set[str]]:
    """Render one country sheet HTML, its manifest record, and the flag ISOs it needs."""
    iso = iso_lower.upper()
    roster = bundle["roster"]
    if iso not in roster:
        raise SheetError(f"{iso}: not in pipeline/roster/countries.json")
    cname = roster[iso]["name"]
    ds = bundle["dataset"]
    facts = compute_axis_facts(bundle, iso)
    standout = standout_facts(facts)
    rules = active_consistency_rules(bundle, iso, facts)
    secs = sections_for(bundle["published_axes"])

    needed_flags: set[str] = {iso_lower}
    e = html.escape

    # Hero metadata card
    continent = ds["facets"]["continent"][iso]
    subregion = ds["facets"]["subregion"][iso]
    region_txt = subregion if subregion == continent else f"{subregion}, {continent}"
    capital = bundle["capitals"].get(iso)
    cap_lat = ds["attributes"].get("capital_lat", {}).get(iso)
    cap_lon = ds["attributes"].get("capital_lon", {}).get(iso)
    neighbours = ds["field_sets"].get("land_neighbours", {}).get(iso, [])
    border_names = ", ".join(neighbour_name(n, roster, bundle["geo"]) for n in neighbours) if neighbours else "None (island)"
    tz_count = len(ds["field_sets"].get("time_zones", {}).get(iso, []))

    meta_items: list[tuple[str, str, bool]] = []
    if capital:
        meta_items.append(("Capital", capital, False))
    meta_items.append(("Region", region_txt, False))
    meta_items.append(("Time zones", str(tz_count), False))
    meta_items.append(("Borders", border_names, len(neighbours) > 3 or len(border_names) > 25))
    meta_html = "".join(
        f'<div class="a-m{" a-m-wide" if wide else ""}"><span>{e(k)}</span><b>{e(v)}</b></div>'
        for k, v, wide in meta_items
    )

    hero_html = (
        f'<div class="card a-sh">'
        f'<div class="a-sh-top">{flag_img(iso, "flag-xl", 88, 66, lazy=False)}'
        f'<div><p class="a-crumb">Countries &rsaquo; {e(continent)}</p><h1 class="left">{e(cname)}</h1></div></div>'
        f'<div class="a-meta">{meta_html}</div>'
        f'</div>'
    )

    map_html = render_locator_map(iso, cname, capital, cap_lat, cap_lon, bundle["geo"])

    # Standout mini-boards
    boards_parts: list[str] = []
    for f in standout:
        nb = sorted_neighbours(bundle, f["ax"], iso)
        rows = []
        for r, other_iso, val in nb:
            needed_flags.add(other_iso.lower())
            me_cls = " a-me" if other_iso == iso else ""
            rows.append(
                f'<div class="band a-mb{me_cls}">'
                f'<span class="a-mb-n">{ordinal(r)}</span>'
                f'{flag_img(other_iso, "", 28, 21)}'
                f'<span class="bname">{e(roster[other_iso]["name"])}</span>'
                f'<b class="a-mb-v">{fmt_html(val, f["unit"])}</b>'
                f'</div>'
            )
        unit_disp = e(f["unit"]) if f["unit"] else "&nbsp;"
        boards_parts.append(
            f'<figure class="a-board" data-axis="{e(f["ax"])}">'
            f'<figcaption><span class="a-bq">{e(f["name"])}</span><span class="a-bu">{unit_disp}</span></figcaption>'
            f'<div class="cap">&#9650; MOST</div>'
            f'{"".join(rows)}'
            f'<p class="a-bsrc">{e(f["rank_txt"])} &middot; {e(f["src"])}, {e(f["year"])}</p>'
            f'</figure>'
        )
    standout_html = (
        f'<section class="a-fs">'
        f'<h2 class="left">Where {e(cname)} stands out</h2>'
        f'<div class="a-boards">{"".join(boards_parts)}</div>'
        f'</section>'
    )

    # Map each active FR-55 consistency rule to the first section containing any of its axes
    sec_rules: dict[str, list[dict]] = {}
    for r in rules:
        placed = False
        for key, _title, axs in secs:
            if set(r["axes"]) & set(axs):
                sec_rules.setdefault(key, []).append(r)
                placed = True
                break
        if not placed:
            raise SheetError(f"{iso}: active consistency rule {r['rule']!r} could not be placed in any section")

    # Fact sections
    sec_parts: list[str] = []
    for key, title, axs in secs:
        notes_html = "".join(
            f'<p class="a-cnote" data-consistency-rule="{e(r["rule"])}" '
            f'data-consistency-axes="{e(",".join(r["axes"]))}">'
            f'<strong>{e(r["label"])}:</strong> {e(r["note"])}</p>'
            for r in sec_rules.get(key, [])
        )
        row_parts: list[str] = []
        for ax in axs:
            f = facts[ax]
            src_host = host_label(f["url"]) if f["url"] else ""
            src_label = f'{e(f["src"])}, {e(f["year"])}' + (f" &middot; {e(src_host)}" if src_host else "")
            src_el = (
                f'<a class="a-f-s" href="{e(f["url"], quote=True)}" rel="noopener noreferrer">{src_label}</a>'
                if f["url"] else f'<span class="a-f-s">{src_label}</span>'
            )
            if f["nodata"]:
                val_el = '<b class="a-nd">No data</b><span class="a-rk a-rk-nd">Not ranked</span>'
            else:
                usp = f'<small> {e(f["unit_txt"])}</small>' if f["unit_txt"] else ""
                val_el = f'<b>{f["val_html"]}{usp}</b><span class="a-rk">{e(f["rank_txt"])}</span>'
            row_parts.append(
                f'<div class="band a-f" data-axis="{e(ax)}">'
                f'<div class="a-f-l"><span class="a-f-n">{e(f["name"])}</span>{src_el}</div>'
                f'<div class="a-f-r">{val_el}</div>'
                f'</div>'
            )
        sec_parts.append(
            f'<section class="a-fs" id="sec-{e(key)}">'
            f'<h2 class="left">{e(title)}</h2>'
            f'{notes_html}'
            f'{"".join(row_parts)}'
            f'</section>'
        )

    how_html = (
        f'<p class="a-how">Rank counts from the highest value among the countries that have data: '
        f'1st is the most. Ties share a rank. Data version {bundle["vnum"]}, {e(bundle["vdate"])}.</p>'
    )

    n_all_axes = len(ds["axes"])
    n_have_all = sum(
        1 for a in ds["axes"]
        if iso in ds["axes"][a] and isinstance(ds["axes"][a][iso], dict)
        and not isinstance(ds["axes"][a][iso].get("sort_value"), dict)
    )
    play_html = (
        f'<div class="card a-play">'
        f'<h3>Sort {e(cname)} against four others</h3>'
        f'<p>The game has figures for {e(cname)} on {n_have_all} of its {n_all_axes} questions.</p>'
        f'<!-- launch:sheet-play --><!-- /launch:sheet-play -->'
        f'</div>'
    )

    desc = (
        f"Real, sourced facts and world rankings for {cname} from Sorting Geography: "
        f"size, borders, people, economy, food and energy."
    )
    rel = f"countries/{iso_lower}/index.html"
    raw_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(cname)} — Sorting Geography</title>
<meta name="description" content="{e(desc, quote=True)}">
<!-- seo:head --><!-- /seo:head -->
<meta name="robots" content="noindex,follow">
<link rel="stylesheet" href="../../style.css">
</head>
<body>
<header class="hd">
  <div class="hd-in">
    <a class="wm" href="../../">{ic_globe("ic wm-ic")}<span>Sorting&nbsp;Geography</span></a>
    <nav class="hd-links">
      <a href="../../#how-to-play">How to play</a>
      <a href="../../#daily">Daily</a>
      <a href="../../#faq">FAQ</a>
    </nav>
    <div class="hd-end">
      <a class="btn btn-sm only-pre" href="../../#notify">Get notified</a>
      <a class="btn btn-sm only-post" href="../../#launch">Get the app</a>
    </div>
  </div>
</header>

<div class="fromgame">
  <div class="fromgame-in">
    <a href="../../">{ic_back()}Back to the game</a>
    <span>Opened from the game</span>
  </div>
</div>

<main class="da">
  <div class="a-shw">
    <div class="a-side-top">
      {hero_html}
      {map_html}
    </div>
    <div class="a-main">
      {standout_html}
      <div class="a-fcols">
        {"".join(sec_parts)}
      </div>
      {how_html}
    </div>
    <div class="a-side-play">
      {play_html}
    </div>
  </div>
</main>

<footer class="ft">
  <div class="ft-in">
    <div class="ft-brand">
      <a class="wm" href="../../">{ic_globe("ic wm-ic")}<span>Sorting&nbsp;Geography</span></a>
    </div>
    <nav class="ft-links">
      <a href="../../#faq">FAQ</a>
      <a href="../../credits.html">Data sources</a>
      <a href="../../press/">Press</a>
      <a href="../../support/">Support</a>
      <a href="../../privacy/">Privacy</a>
      <a href="../../terms/">Terms</a>
    </nav>
    <p class="ft-fam">Part of the Sorting family, with Sorting History.</p>
  </div>
</footer>
</body>
</html>
"""
    # Fill seo:head and launch:sheet-play regions cleanly using the site's builders.
    ms = build_launch.release_ms(root)
    gen_launch = build_launch.regions(ms, lang="en", root=root, root_prefix="../../")
    rendered = build_launch.render(raw_html, gen_launch, rel)
    rendered = build_seo.render(rel, rendered)

    manifest_entry = {
        "name": cname,
        "values": {ax: {"val": f["val_plain"], "rank": f["rank_txt"], "nodata": f["nodata"]} for ax, f in facts.items()},
        "consistency_rules": [r["rule"] for r in rules],
    }
    return rendered, manifest_entry, needed_flags


# ---------------------------------------------------------------------------
# Offline and live-game verification guards
# ---------------------------------------------------------------------------

def _extract_rendered_facts(page: str) -> list[tuple[str, str, str]]:
    """Extract (axis_id, displayed_value_plain, displayed_rank) from every .a-f card."""
    out: list[tuple[str, str, str]] = []
    pat = re.compile(
        r'<div\s+class="band a-f"\s+data-axis="([^"]+)">'
        r'.*?<div\s+class="a-f-r"><b(?:\s+class="[^"]*")?>(.*?)</b>'
        r'<span\s+class="a-rk[^"]*">(.*?)</span></div></div>',
        re.S,
    )
    for m in pat.finditer(page):
        ax = html.unescape(m.group(1))
        val_inner = re.sub(r"<small>.*?</small>", "", m.group(2), flags=re.S)
        val_txt = html.unescape(re.sub(r"<[^>]+>", "", val_inner)).strip().replace("\u2212", "-")
        rk_txt = html.unescape(re.sub(r"<[^>]+>", "", m.group(3))).strip()
        out.append((ax, val_txt, rk_txt))
    return out


def _extract_consistency_notes(page: str) -> dict[str, str]:
    """Extract rule_id -> visible note text from every FR-55 note element."""
    out: dict[str, str] = {}
    pat = re.compile(r'<p\s+class="a-cnote"\s+data-consistency-rule="([^"]+)"[^>]*>(.*?)</p>', re.S)
    for m in pat.finditer(page):
        rule_id = html.unescape(m.group(1))
        text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", m.group(2))).split())
        out[rule_id] = text
    return out


def _check_page_security_and_seo(rel: str, iso: str, page: str) -> list[str]:
    bad: list[str] = []
    no_comments = re.sub(r"<!--.*?-->", " ", page, flags=re.S)

    # 1. noindex,follow
    if not re.search(r'<meta\s+name="robots"\s+content="noindex,follow"\s*/?>', no_comments, re.I):
        bad.append(f"{rel}: missing <meta name=\"robots\" content=\"noindex,follow\">")

    # 2. self-canonical
    want_canon = f"{SITE}/countries/{iso}/"
    if f'<link rel="canonical" href="{want_canon}">' not in no_comments:
        bad.append(f"{rel}: missing self-canonical {want_canon}")

    # 3. No scripts of any kind (no third-party scripts, no inline scripts)
    for m in re.finditer(r"<script\b([^>]*)>", no_comments, re.I):
        attrs = m.group(1)
        if not re.search(r'\btype\s*=\s*["\']application/ld\+json["\']', attrs, re.I):
            bad.append(f"{rel}: disallowed <script{attrs}> on country sheet (no third-party or inline scripts)")

    # 4. No Google Fonts or other third-party font services, no external assets
    if THIRD_PARTY_FONT_RE.search(no_comments):
        bad.append(f"{rel}: references a third-party font service")
    for m in re.finditer(r'<(?:link|img|iframe|object|embed)\b[^>]*\b(?:href|src)\s*=\s*"([^"]+)"', no_comments, re.I):
        tag = m.group(0)
        url = m.group(1)
        # <link rel="canonical"> is allowed to carry the site URL; stylesheets/preloads/imgs/iframes must be local.
        if re.search(r'\brel\s*=\s*"canonical"', tag, re.I):
            continue
        if re.match(r"^(?:https?:|//|data:)", url, re.I):
            bad.append(f"{rel}: loads external or data resource {url!r}")

    # 5. No Daily answer / today's Daily question
    visible = re.sub(r"<[^>]+>", " ", no_comments)
    m_daily = DAILY_LEAK_RE.search(visible)
    if m_daily:
        bad.append(f"{rel}: mentions {m_daily.group(0)!r} (no Daily question or answer on country sheets)")

    return bad


MAX_FIXED_WIDTH_PX = 360.0


def _iter_css_rules(css_text: str) -> list[tuple[str, str]]:
    """Parse top-level and @media-nested CSS rule blocks into (selector, declarations) pairs."""
    rules: list[tuple[str, str]] = []
    i = 0
    n = len(css_text)
    while i < n:
        brace = css_text.find("{", i)
        if brace == -1:
            break
        header = " ".join(css_text[i:brace].split())
        depth = 1
        j = brace + 1
        while j < n and depth > 0:
            ch = css_text[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            j += 1
        body = css_text[brace + 1:j - 1]
        if header.startswith("@"):
            rules.extend(_iter_css_rules(body))
        elif header:
            rules.append((header, body))
        i = j
    return rules


def _check_sheet_css_overflow(root: pathlib.Path) -> list[str]:
    """Static check on the COUNTRY SHEETS CSS section in style.css for sideways-overflow traps."""
    bad: list[str] = []
    css_path = root / "style.css"
    if not css_path.is_file():
        return ["style.css is missing"]
    css = css_path.read_text(encoding="utf-8")
    m = re.search(r"/\*[^*]*COUNTRY SHEETS\b.*?\*/", css, re.S)
    if not m:
        return ["style.css: missing COUNTRY SHEETS section marker"]
    sheet_css = re.sub(r"/\*.*?\*/", "", css[m.end():], flags=re.S)

    for selector, body in _iter_css_rules(sheet_css):
        decls: dict[str, str] = {}
        for part in body.split(";"):
            part = part.strip()
            if ":" not in part:
                continue
            prop, val = part.split(":", 1)
            prop = prop.strip().lower()
            val = val.strip()
            decls[prop] = val

            # 1. Fixed width / min-width > 360px or > 100vw
            if prop in {"width", "min-width"}:
                for px_s in re.findall(r"(?<![a-z0-9_.-])(\d+(?:\.\d+)?)px\b", val, re.I):
                    if float(px_s) > MAX_FIXED_WIDTH_PX:
                        bad.append(
                            f"style.css ({selector}): {prop}: {val} exceeds {int(MAX_FIXED_WIDTH_PX)}px "
                            f"(risks horizontal overflow on phones)"
                        )
                for vw_s in re.findall(r"(?<![a-z0-9_.-])(\d+(?:\.\d+)?)vw\b", val, re.I):
                    if float(vw_s) > 100.0:
                        bad.append(f"style.css ({selector}): {prop}: {val} exceeds 100vw")

            # 2. grid-template-columns must bound tracks with minmax(0, ...) and stay <= 360px
            if prop == "grid-template-columns":
                for px_s in re.findall(r"(?<![a-z0-9_.-])(\d+(?:\.\d+)?)px\b", val, re.I):
                    if float(px_s) > MAX_FIXED_WIDTH_PX:
                        bad.append(
                            f"style.css ({selector}): grid-template-columns ({val}) has fixed track > "
                            f"{int(MAX_FIXED_WIDTH_PX)}px"
                        )
                for min_arg, _max_arg in re.findall(r"minmax\s*\(([^,)]+),([^)]+)\)", val, re.I):
                    if not re.fullmatch(r"0(?:[a-z%]+)?", min_arg.strip(), re.I):
                        bad.append(
                            f"style.css ({selector}): grid-template-columns ({val}) uses minmax() "
                            f"without 0 minimum"
                        )
                outside_minmax = re.sub(r"minmax\s*\([^)]*\)", "", val, flags=re.I)
                if re.search(r"\b\d+(?:\.\d+)?fr\b|\bauto\b", outside_minmax, re.I):
                    bad.append(
                        f"style.css ({selector}): grid-template-columns ({val}) has unconstrained track "
                        f"without minmax(0, ...)"
                    )

            # 3. white-space: nowrap in country-sheet CSS prevents wrapping on narrow screens
            if prop == "white-space" and re.search(r"\bnowrap\b", val, re.I):
                bad.append(
                    f"style.css ({selector}): white-space: {val} risks horizontal overflow on phones"
                )

        # 4. Every display: grid container in sheet CSS must declare explicit grid-template-columns
        if decls.get("display", "").lower() in {"grid", "inline-grid"} and "grid-template-columns" not in decls:
            bad.append(
                f"style.css ({selector}): display: {decls['display']} without grid-template-columns "
                f"(implicit auto track can overflow phones)"
            )

    return bad


def _check_page_overflow(rel: str, page: str) -> list[str]:
    """Static markup checks on a country sheet for sideways-overflow hazards."""
    bad: list[str] = []
    no_comments = re.sub(r"<!--.*?-->", " ", page, flags=re.S)

    if not re.search(
        r'<meta\s+name="viewport"\s+content="width=device-width,\s*initial-scale=1"\s*/?>',
        no_comments,
        re.I,
    ):
        bad.append(f"{rel}: missing responsive viewport meta tag")

    for m in re.finditer(r'\bstyle\s*=\s*"([^"]*)"', no_comments, re.I):
        style_val = m.group(1)
        for prop_m in re.finditer(r"(?<![a-z-])((?:min-)?width)\s*:\s*(\d+(?:\.\d+)?)px\b", style_val, re.I):
            if float(prop_m.group(2)) > MAX_FIXED_WIDTH_PX:
                bad.append(
                    f"{rel}: inline style {prop_m.group(0)!r} exceeds {int(MAX_FIXED_WIDTH_PX)}px"
                )

    for m in re.finditer(r'<svg\b[^>]*\bwidth\s*=\s*"(\d+(?:\.\d+)?)"', no_comments, re.I):
        if float(m.group(1)) > MAX_FIXED_WIDTH_PX:
            bad.append(f"{rel}: <svg width=\"{m.group(1)}\"> exceeds {int(MAX_FIXED_WIDTH_PX)}px (use viewBox + CSS)")

    if re.search(r'<div\s+class="a-f-r"><b>[^<]*<small>&nbsp;', no_comments):
        bad.append(f"{rel}: fact value uses non-breaking &nbsp; before unit (prevents wrapping on narrow screens)")

    return bad


def check(root: pathlib.Path = ROOT) -> list[str]:
    """Offline CI check: verifies every sheet against COUNTRIES, deny-list, manifest, sitemap, and overflow rules."""
    bad: list[str] = []
    bad += _check_sheet_css_overflow(root)
    try:
        deny_list = load_deny_list(root)
    except SheetError as e:
        return [str(e)]

    mp = root / MANIFEST_FILE
    if not mp.is_file():
        return [f"{MANIFEST_FILE} is missing; run scripts/build_sheets.py --game <path>"]
    manifest = json.loads(mp.read_text(encoding="utf-8"))
    policy: dict[str, str] = manifest.get("axis_policy") or {}
    m_countries: dict[str, dict] = manifest.get("countries") or {}
    expected_axes = sorted(ax for ax, st in policy.items() if st == "allowed" and ax not in deny_list)

    # Check exact set of countries on disk matches COUNTRIES
    cdir = root / "countries"
    on_disk = sorted(
        p.parent.name for p in cdir.glob("*/index.html")
    ) if cdir.is_dir() else []
    missing_disk = sorted(set(COUNTRIES) - set(on_disk))
    extra_disk = sorted(set(on_disk) - set(COUNTRIES))
    if missing_disk:
        bad.append(f"countries/: missing sheet(s) for {missing_disk}")
    if extra_disk:
        bad.append(f"countries/: unexpected sheet(s) outside COUNTRIES: {extra_disk}")

    # Country sheets must never appear in sitemap.xml
    sm = root / "sitemap.xml"
    if sm.is_file() and "/countries/" in sm.read_text(encoding="utf-8"):
        bad.append("sitemap.xml: lists /countries/ URL(s); country sheets are noindex and must stay out of sitemap.xml")

    for iso in COUNTRIES:
        rel = f"countries/{iso}/index.html"
        p = root / rel
        if not p.is_file():
            continue
        page = p.read_text(encoding="utf-8")
        bad += _check_page_security_and_seo(rel, iso, page)
        bad += _check_page_overflow(rel, page)

        # Check every data-axis attribute (both fact rows and standout mini-boards)
        all_axes_in_page = re.findall(r'data-axis="([^"]+)"', page)
        for ax in sorted(set(all_axes_in_page)):
            if policy.get(ax) != "allowed":
                bad.append(f"{rel}: axis {ax!r} has web_republish={policy.get(ax)!r} (only 'allowed' may appear)")
            if ax in deny_list:
                bad.append(f"{rel}: axis {ax!r} is on {DENY_FILE} ({deny_list[ax]})")

        # Check every fact card's value and rank against manifest
        rendered = _extract_rendered_facts(page)
        rendered_map = {ax: (val, rk) for ax, val, rk in rendered}
        if len(rendered_map) != len(rendered):
            bad.append(f"{rel}: duplicate axis row rendered")

        if iso not in m_countries:
            bad.append(f"{MANIFEST_FILE}: missing entry for {iso}")
            continue
        want_vals = m_countries[iso].get("values") or {}
        missing_ax = sorted(set(expected_axes) - set(rendered_map))
        extra_ax = sorted(set(rendered_map) - set(expected_axes))
        if missing_ax:
            bad.append(f"{rel}: missing allowed axis/axes {missing_ax[:5]} ({len(missing_ax)} total)")
        if extra_ax:
            bad.append(f"{rel}: unexpected axis/axes {extra_ax[:5]} ({len(extra_ax)} total)")

        for ax, (got_val, got_rk) in rendered_map.items():
            if ax not in want_vals:
                continue
            exp = want_vals[ax]
            if got_val != exp["val"]:
                bad.append(f"{rel}: {ax} value {got_val!r} != dataset value {exp['val']!r}")
            if got_rk != exp["rank"]:
                bad.append(f"{rel}: {ax} rank {got_rk!r} != dataset rank {exp['rank']!r}")
            if exp.get("nodata") and (got_val != "No data" or got_rk != "Not ranked"):
                bad.append(f"{rel}: {ax} has no data and must read 'No data' / 'Not ranked', not {got_val!r} / {got_rk!r}")

        # FR-55: every required consistency rule must render with a non-empty note
        notes = _extract_consistency_notes(page)
        for rule_id in m_countries[iso].get("consistency_rules") or []:
            note_txt = notes.get(rule_id, "")
            if len(note_txt) < 20:
                bad.append(f"{rel}: FR-55 consistency rule {rule_id!r} rendered without its required note")

    return bad


def check_game(
    game: pathlib.Path,
    ref: str = "origin/main",
    root: pathlib.Path = ROOT,
    countries_ref: str | None = None,
) -> list[str]:
    """Live check against the game repo: dataset values, web_republish policy, FR-55, and kCountrySheetCountries."""
    bad: list[str] = []
    try:
        deny_list = load_deny_list(root)
        bundle = load_game_bundle(game, ref, deny_list)
    except SheetError as e:
        return [str(e)]

    # Compare COUNTRIES with kCountrySheetCountries on the game repo (fail closed)
    cref = countries_ref or ref
    try:
        require_ref(game, cref)
    except SheetError as e:
        return [str(e)]
    dart = game_show(game, cref, SHEET_URL_DART)
    if dart is None:
        bad.append(f"{game}: cannot read {SHEET_URL_DART} at {cref} to verify kCountrySheetCountries")
    else:
        game_countries = parse_game_countries(dart)
        if game_countries is None:
            bad.append(f"{SHEET_URL_DART} at {cref}: malformed or missing kCountrySheetCountries")
        elif sorted(game_countries) != sorted(COUNTRIES):
            only_game = sorted(set(game_countries) - set(COUNTRIES))
            only_site = sorted(set(COUNTRIES) - set(game_countries))
            bad.append(
                f"COUNTRIES differs from {SHEET_URL_DART} kCountrySheetCountries at {cref} "
                f"(only in game: {only_game}, only in site: {only_site})"
            )

    # Check every sheet directly against live dataset.json, web_republish and allowlist
    policy = bundle["policy"]
    expected_axes = set(bundle["published_axes"])
    for iso in COUNTRIES:
        rel = f"countries/{iso}/index.html"
        p = root / rel
        if not p.is_file():
            bad.append(f"{rel}: missing")
            continue
        page = p.read_text(encoding="utf-8")
        bad += _check_page_security_and_seo(rel, iso, page)
        bad += _check_page_overflow(rel, page)

        for ax in sorted(set(re.findall(r'data-axis="([^"]+)"', page))):
            if policy.get(ax) != "allowed":
                bad.append(f"{rel}: axis {ax!r} is web_republish={policy.get(ax)!r} at {ref} (refusing non-allowed axis)")
            if ax in deny_list:
                bad.append(f"{rel}: axis {ax!r} is on {DENY_FILE}")

        facts = compute_axis_facts(bundle, iso.upper())
        rendered = dict((ax, (val, rk)) for ax, val, rk in _extract_rendered_facts(page))
        missing_ax = sorted(expected_axes - set(rendered))
        if missing_ax:
            bad.append(f"{rel}: missing allowed axis/axes at {ref}: {missing_ax[:5]}")
        for ax, (got_val, got_rk) in rendered.items():
            if ax not in facts:
                continue
            f = facts[ax]
            if got_val != f["val_plain"]:
                bad.append(f"{rel}: {ax} value {got_val!r} != {ref} dataset value {f['val_plain']!r}")
            if got_rk != f["rank_txt"]:
                bad.append(f"{rel}: {ax} rank {got_rk!r} != {ref} dataset rank {f['rank_txt']!r}")

        notes = _extract_consistency_notes(page)
        for r in active_consistency_rules(bundle, iso.upper(), facts):
            if len(notes.get(r["rule"], "")) < 20:
                bad.append(f"{rel}: FR-55 rule {r['rule']!r} from {ref} rendered without its note")

    # Also verify offline checks (manifest, sitemap, etc.) stay in sync
    bad += check(root)
    return bad


def build(
    game: pathlib.Path,
    ref: str = "origin/main",
    root: pathlib.Path = ROOT,
    countries_ref: str | None = None,
) -> None:
    deny_list = load_deny_list(root)
    bundle = load_game_bundle(game, ref, deny_list)

    # If country_sheet_url.dart is present on countries_ref (or ref), enforce exact match.
    cref = countries_ref or ref
    dart = game_show(game, cref, SHEET_URL_DART)
    if dart is not None:
        game_countries = parse_game_countries(dart)
        if game_countries is None:
            raise SheetError(f"{SHEET_URL_DART} at {cref}: malformed kCountrySheetCountries")
        if sorted(game_countries) != sorted(COUNTRIES):
            raise SheetError(
                f"COUNTRIES differs from {SHEET_URL_DART} kCountrySheetCountries at {cref}: "
                f"site={sorted(COUNTRIES)} vs game={sorted(game_countries)}"
            )
    elif countries_ref is not None:
        raise SheetError(f"{game}: cannot read {SHEET_URL_DART} at {countries_ref}")

    manifest_countries: dict[str, dict] = {}
    all_flags: set[str] = set()
    pages_out: dict[str, str] = {}

    for iso in COUNTRIES:
        rendered, entry, flags = render_sheet(bundle, iso, root)
        pages_out[iso] = rendered
        manifest_countries[iso] = entry
        all_flags.update(flags)

    # Validate every generated page BEFORE writing anything (fail closed).
    for iso, page in pages_out.items():
        rel = f"countries/{iso}/index.html"
        problems = _check_page_security_and_seo(rel, iso, page)
        if problems:
            raise SheetError("refusing to write invalid sheet:\n  " + "\n  ".join(problems))

    # Copy referenced flag SVGs from the game repo at ref.
    flags_dir = root / "images" / "flags"
    flags_dir.mkdir(parents=True, exist_ok=True)
    for iso in sorted(all_flags):
        svg_bytes = game_show_bytes(game, ref, f"app/assets/flags/{iso}.svg")
        if svg_bytes is None:
            raise SheetError(f"{game}: missing app/assets/flags/{iso}.svg at {ref}")
        dest = flags_dir / f"{iso}.svg"
        if not dest.exists() or dest.read_bytes() != svg_bytes:
            dest.write_bytes(svg_bytes)

    # Remove any stale flag SVGs not needed by the generated pages.
    for existing in list(flags_dir.glob("*.svg")):
        if existing.stem not in all_flags:
            existing.unlink()

    # Write the 20 HTML sheets.
    for iso, page in pages_out.items():
        dest = root / "countries" / iso / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(page, encoding="utf-8")

    # Remove any stray country folders outside COUNTRIES.
    cdir = root / "countries"
    if cdir.is_dir():
        for sub in list(cdir.iterdir()):
            if sub.is_dir() and sub.name not in COUNTRIES:
                for f in sub.rglob("*"):
                    if f.is_file():
                        f.unlink()
                sub.rmdir()

    # Write offline verification manifest (in src/, ignored by .assetsignore).
    manifest = {
        "dataset_version": bundle["version"],
        "version_num": bundle["vnum"],
        "version_date": bundle["vdate"],
        "countries_list": list(COUNTRIES),
        "axis_policy": bundle["policy"],
        "denied_axes": sorted(deny_list),
        "published_axes": bundle["published_axes"],
        "countries": manifest_countries,
    }
    (root / MANIFEST_FILE).write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Run offline check immediately to guarantee our own output passes.
    problems = check(root)
    if problems:
        raise SheetError("generated sheets failed self-check:\n  " + "\n  ".join(problems))

    print(
        f"ok   built {len(COUNTRIES)} country sheets ({len(bundle['published_axes'])} allowed axes, "
        f"{sum(1 for v in bundle['policy'].values() if v != 'allowed')} not allowed, "
        f"{len(deny_list)} denied, {len(all_flags)} flags, {bundle['version']})"
    )


def main(argv: list[str]) -> int:
    check_mode = "--check" in argv
    game = pathlib.Path(argv[argv.index("--game") + 1]) if "--game" in argv and argv.index("--game") + 1 < len(argv) else None
    ref = argv[argv.index("--ref") + 1] if "--ref" in argv and argv.index("--ref") + 1 < len(argv) else "origin/main"
    cref = (
        argv[argv.index("--countries-ref") + 1]
        if "--countries-ref" in argv and argv.index("--countries-ref") + 1 < len(argv)
        else None
    )

    if check_mode and game is not None:
        problems = check_game(game, ref, ROOT, countries_ref=cref)
        if problems:
            print(f"country sheet check FAILED against {ref}:")
            for b in problems:
                print("  " + b)
            return 1
        print(f"ok   country sheets: {len(COUNTRIES)} pages match {ref} and kCountrySheetCountries")
        return 0

    if check_mode:
        problems = check(ROOT)
        if problems:
            print("country sheet check FAILED (Story 18.6):")
            for b in problems:
                print("  " + b)
            return 1
        print(f"ok   country sheets: {len(COUNTRIES)} pages pass all Story 18.6 checks")
        return 0

    if game is None:
        print("usage: build_sheets.py --game PATH [--ref REF] [--countries-ref REF] | --check [--game PATH]", file=sys.stderr)
        return 2

    try:
        build(game, ref, ROOT, countries_ref=cref)
    except SheetError as e:
        print(f"build_sheets FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
