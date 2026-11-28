#!/usr/bin/env python3
"""Generate and verify the English country sheets (Stories 18.6 & 18.6b).

Reads the game repo via `git show <ref>:<path>` (nothing checked out) and
generates BOTH static HTML sheets for every country in the game's roster (195)
in one run, styled with the site's existing `style.css` and self-hosted fonts
(no Google Fonts, no third-party scripts):
  - `countries/<iso>/index.html`      — short summary page (the URL the game opens)
  - `countries/<iso>/all/index.html`  — full page with every published fact

Usage:
    python3 scripts/build_sheets.py --game ../Sorting-Geography [--ref origin/main] [--countries-ref REF] [--out DIR]
    python3 scripts/build_sheets.py --check [--out DIR]
    python3 scripts/build_sheets.py --check --game ../Sorting-Geography [--ref origin/main] [--countries-ref REF] [--out DIR]

Modes:
  - Build (`--game PATH`): derives the full country roster from the game repo at
    `--ref` (`pipeline/roster/countries.json`) and reads dataset.json, axes.yaml,
    fields.yaml, fact_consistency_allowlist.yaml, capital_name.csv,
    ne_50m_admin_0_countries.geojson, puzzle.dart, app_en.arb, version-log.json,
    and flag SVGs; writes `countries/<iso>/index.html` (short),
    `countries/<iso>/all/index.html` (full), `images/flags/<iso>.svg`, and
    `src/sheets_manifest.json`. Refuses (exit 1) if any axis to be published is
    not `web_republish: allowed` or is in `src/sheet_deny_axes.json`.
  - Offline check (`--check`, used in CI): verifies both pages for every
    roster country against `src/sheets_manifest.json`, `src/facts.json`,
    `src/sheet_deny_axes.json`, and `sitemap.xml` (complete roster, allowed-only
    axes, exact dataset values, FR-55 notes, no empty sections, no null/NaN/
    undefined, noindex,follow, self-canonical, short<->full links, no third-party
    scripts/fonts, no Daily).
  - Live game check (`--check --game PATH`): runs all offline checks plus
    re-checks every roster country directly against the game repo at `--ref`
    and compares the website country set against `kCountrySheetCountries` in
    `app/lib/play/country_sheet_url.dart` (fail closed on any difference).
"""
from __future__ import annotations

import csv
import datetime
import functools
import html
from html.parser import HTMLParser
import io
import json
import math
import pathlib
import re
import shutil
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
FACTS_FILE = "src/facts.json"
SHEET_URL_DART = "app/lib/play/country_sheet_url.dart"

# Country sheets cover every country in the game's roster (195, Story 18.6b).
# The country list is derived directly from `pipeline/roster/countries.json` at
# `--ref` (never hand-typed here) and recorded in `src/sheets_manifest.json`.
# `--check --game` compares the website set against both the game's roster and
# `kCountrySheetCountries` in `app/lib/play/country_sheet_url.dart` (fail closed).

# ONE table of country ISO2 codes whose English name in `pipeline/roster/countries.json`
# takes "the" in running prose. Standalone titles/labels (<h1>, short-page <title>,
# mini-board rows, Borders list) stay the bare name; running sentences use
# country_in_prose(iso, cname, start=...).
# Note: the roster names CD "Congo (DRC)", CG "Congo", CZ "Czechia",
# FM "Micronesia", and VA "Vatican City", so those do not take "the" in running prose.
COUNTRIES_WITH_THE: frozenset[str] = frozenset({
    "AE",  # the United Arab Emirates
    "BS",  # the Bahamas
    "CF",  # the Central African Republic
    "DO",  # the Dominican Republic
    "GB",  # the United Kingdom
    "GM",  # the Gambia
    "KM",  # the Comoros
    "MH",  # the Marshall Islands
    "MV",  # the Maldives
    "NL",  # the Netherlands
    "PH",  # the Philippines
    "PS",  # the State of Palestine
    "SB",  # the Solomon Islands
    "SC",  # the Seychelles
    "US",  # the United States
})

# Sheet-only display label overrides (do not touch the game's app_en.arb).
SHEET_NAME_OVERRIDES: dict[str, str] = {
    "foreign_born_share_pct": "Share of people born abroad",
}


def country_in_prose(iso: str, cname: str, *, start: bool = False) -> str:
    """Return country name for running English prose ('the United States' / 'The United States')."""
    if iso.upper() in COUNTRIES_WITH_THE:
        return f"{'The' if start else 'the'} {cname}"
    return cname

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

# Short-layout selection rule (ONE place, deterministic, never hand-picked per country):
# Start with 12 core staples from Sally's themed sections (filtered to web_republish: allowed
# and non-denied), then fill up to SHORT_TARGET_FACTS (20) with each country's strongest-ranked
# remaining allowed facts with data (lowest rank/n ratio, untied first, then ties <= 2, then
# remaining ties, tie-breaking on rank and axis id), grouped into Sally's 5 themed sections.
SHORT_TARGET_FACTS = 20
SHORT_MAX_FACTS = 25
SHORT_CORE_AXES: tuple[str, ...] = (
    "land_area_km2", "coastline_km", "land_neighbour_count",
    "highest_point_m", "mean_elevation_m", "forest_pct",
    "population", "population_density", "median_age", "life_expectancy",
    "airports_count",
    "football_matches_all_time",
)
SHORT_SECTIONS: list[tuple[str, str, tuple[str, ...]]] = [
    ("size", "Size, sea and borders", ("size",)),
    ("land", "Land and height", ("height-water", "land")),
    ("people", "People", ("people",)),
    ("work", "Food, power and travel", ("economy", "farming", "food", "energy", "transport")),
    ("play", "Football and chess", ("play",)),
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
        "Share of people born abroad (%) divides UN DESA mid-2020 migrant stock by UN mid-2020 resident population, whereas Population is World Bank, WDI 2023.",
    ),
    "emigrants_pct_vs_total_over_pop": (
        "Different years",
        "Share of its people living abroad (%) divides UN DESA mid-2020 emigrants by UN mid-2020 resident population, whereas Population is World Bank, WDI 2023.",
    ),
    "pop_growth_vs_components": (
        "Different sources and years",
        "Births and deaths come from CIA World Factbook 2024 (2023 estimates), while population growth and net migration come from UN World Population Prospects 2024 via World Bank, WDI (2023).",
    ),
    "largest_city_gt_urban_pop": (
        "Different definitions",
        "Biggest city uses UN DESA 2025 Degree of Urbanisation city boundaries, whereas urban population (%) uses the country's own national administrative definition (World Bank, WDI 2023).",
    ),
    "capital_gt_urban_pop": (
        "Different definitions",
        "Capital population uses UN DESA 2025 Degree of Urbanisation city boundaries (mid-2025), whereas urban population (%) uses national statistical definitions (World Bank, WDI 2023).",
    ),
    "land_neighbours_0_but_boundary_gt_0": (
        "Different definitions",
        "Land borders (km) from CIA World Factbook 2024 counts boundaries with non-sovereign territories, whereas Number of land borders from GeoNames counts sovereign neighbours only.",
    ),
    "forest_pct_vs_area_over_land": (
        "Different years",
        "Forest cover (%) and forest area are FAO 2020 figures using 2020 land area, whereas Land area is World Bank, WDI 2023.",
    ),
    "maize_plus_wheat_gt_cereal": (
        "Different years",
        "Wheat grown is from 2022 while corn grown and cereal production are from 2023, so their sum can exceed 2023 total cereals.",
    ),
    "wheat_gt_cereal": (
        "Different years",
        "Wheat grown is from 2022 while cereal production is from 2023.",
    ),
    "female_share_outside_40_60": (
        "Why this is below 40%",
        "A large, mostly male expatriate and migrant workforce pushes the female share of the total resident population below 40%.",
    ),
}

SOURCE_RULES: list[tuple[str, str]] = [
    (r"^CIA World Factbook 2024", "CIA World Factbook, 2024 edition"),
    (r"^Derived: CIA World Factbook 2024", "CIA World Factbook and World Bank (derived)"),
    (r"^Derived: GeoNames capital", "GeoNames and Natural Earth (derived)"),
    (r"^Derived: Natural Earth", "Natural Earth (derived)"),
    (r"^Derived: UN WUP 2025", "UN DESA World Urbanization Prospects 2025 and World Bank (derived)"),
    (r"^ESA WorldCover 2021", "ESA WorldCover 2021, via FAOSTAT"),
    (r"^FAO 20\d\d \(via World Bank WDI", "FAO, via World Bank, WDI"),
    (r"^FAO AQUASTAT", "AQUASTAT, via World Bank, WDI"),
    (r"^FAO Food Balance Sheets.*via Our World in Data", "FAO Food Balance Sheets, via Our World in Data"),
    (r"^FAO Food Balance Sheets", "FAO Food Balance Sheets"),
    (r"^FAO Global Forest Resources Assessment 2025", "FAO Global Forest Resources Assessment 2025"),
    (r"^FAO Global Forest Resources Assessment 2020", "FAO Global Forest Resources Assessment 2020"),
    (r"^FAOSTAT Environment/Land Cover.*ESA WorldCover", "ESA WorldCover 2021, via FAOSTAT"),
    (r"^FAOSTAT QCL.*via Our World in Data", "FAOSTAT, via Our World in Data"),
    (r"^FAOSTAT", "FAOSTAT"),
    (r"^GeoNames", "GeoNames"),
    (r"^Holy See official \(Annuario Pontificio\)", "Holy See (Annuario Pontificio), via UN"),
    (r"^IANA Time Zone Database", "IANA Time Zone Database 2026a"),
    (r"^ILO\b.*via World Bank WDI", "ILO, via World Bank, WDI"),
    (r"^JRC Global Human Settlement Layer", "EU JRC Global Human Settlement Layer"),
    (r"^Marine Regions World EEZ v12", "Marine Regions, World EEZ version 12"),
    (r"^Men's international football results", "International football results (martj42)"),
    (r"^Natural Earth 1:50m", "Natural Earth 1:50 million"),
    (r"^Our World in Data \(Global Carbon Project\)", "Global Carbon Project, via Our World in Data"),
    (r"^OurAirports", "OurAirports"),
    (r"^UN DESA International Migrant Stock 2024", "UN DESA International Migrant Stock 2024"),
    (r"^UN DESA Population Division, Database on Household Size", "UN DESA Household Size and Composition"),
    (r"^UN DESA World Urbanization Prospects 2025", "UN DESA World Urbanization Prospects 2025"),
    (r"^UN IGME", "UN IGME, via World Bank, WDI"),
    (r"^UN Statistics Division Demographic Yearbook", "UN Statistics Division, Demographic Yearbook"),
    (r"^UN WPP 2024 via Our World in Data", "UN World Population Prospects 2024, via Our World in Data"),
    (r"^UN World Population Prospects 2024.*via World Bank WDI", "UN World Population Prospects 2024, via World Bank, WDI"),
    (r"^UN World Population Prospects 2024", "UN World Population Prospects 2024"),
    (r"^UN World Urbanization Prospects 2025.*via World Bank WDI", "UN DESA World Urbanization Prospects 2025, via World Bank, WDI"),
    (r"^UN World Urbanization Prospects 2024", "UN World Urbanization Prospects 2024"),
    (r"^UNDP Human Development Report 2025", "UNDP Human Development Report 2025"),
    (r"^US Energy Information Administration", "United States Energy Information Administration"),
    (r"^Wikidata", "Wikidata"),
    (r"^World Bank / ESMAP", "World Bank / ESMAP, via World Bank, WDI"),
    (r"^World Bank Food Prices for Nutrition", "World Bank Food Prices for Nutrition"),
    (r"^World Bank Global Findex 2024", "World Bank Global Findex 2024"),
    (r"^World Bank International Comparison Program 2021", "World Bank, ICP 2021"),
    (r"^World Bank\b", "World Bank, WDI"),
]

# ONE table of abbreviation expansions for plain-English country sheets (Finding 8).
# Each entry is (short_form, full_form, mode):
#   "always" -> always replace short_form with full_form (short form never shown).
#   "first"  -> expand first appearance on each page to "<full_form> (<short_form>)";
#               later appearances on the same page may use <short_form>.
# Ordered longest/most-specific first so compound forms match before shorter prefixes.
ABBREVIATIONS: list[tuple[str, str, str]] = [
    ("UN DESA", "United Nations Department of Economic and Social Affairs", "first"),
    ("UN IGME", "United Nations Inter-agency Group for Child Mortality Estimation", "first"),
    ("EU JRC", "European Union Joint Research Centre", "first"),
    ("FAOSTAT", "Food and Agriculture Organization statistical database", "first"),
    ("AQUASTAT", "Food and Agriculture Organization water database", "first"),
    ("ESMAP", "Energy Sector Management Assistance Program", "first"),
    ("UNDP", "United Nations Development Programme", "first"),
    ("IANA", "Internet Assigned Numbers Authority", "first"),
    ("FAO", "Food and Agriculture Organization", "first"),
    ("ESA", "European Space Agency", "first"),
    ("ILO", "International Labour Organization", "first"),
    ("CIA", "Central Intelligence Agency", "first"),
    ("WDI", "World Development Indicators", "first"),
    ("WUP", "World Urbanization Prospects", "first"),
    ("ICP", "International Comparison Program", "first"),
    ("EEZ", "Exclusive Economic Zone", "first"),
    ("GDP", "gross domestic product", "first"),
    ("DRC", "Democratic Republic of the Congo", "first"),
    ("CO₂", "carbon dioxide", "first"),
    ("US$", "United States dollars", "first"),
    ("kWh", "kilowatt-hours", "always"),
    ("kcal", "kilocalories", "always"),
    ("km²", "square kilometres", "first"),
    ("km³", "cubic kilometres", "first"),
    ("km", "kilometres", "first"),
    ("m³", "cubic metres", "first"),
    ("mm", "millimetres", "first"),
    ("kg", "kilograms", "first"),
    ("ha", "hectares", "always"),
    ("yr", "year", "always"),
    ("UN", "United Nations", "first"),
    ("US", "United States", "first"),
    ("m", "metres", "first"),
]


def _abbr_token_re(short: str) -> re.Pattern[str]:
    lb = r"(?<![A-Za-z0-9_'\u2019])"
    la = r"(?![A-Za-z0-9_²³₂$])" if short == "US" else r"(?![A-Za-z0-9_²³₂])"
    return re.compile(lb + re.escape(short) + la)


_ABBR_BY_SHORT: dict[str, tuple[str, str]] = {short: (full, mode) for short, full, mode in ABBREVIATIONS}
_ABBR_COMBINED_RE = re.compile("|".join(_abbr_token_re(short).pattern for short, _, _ in ABBREVIATIONS))
_CONGO_DRC_PAT = r"(?<![A-Za-z0-9_'\u2019])Congo\s+\(DRC\)"
_EXPAND_COMBINED_RE = re.compile(_CONGO_DRC_PAT + "|" + _ABBR_COMBINED_RE.pattern)
_ABBR_INTRO_RE: dict[str, re.Pattern[str]] = {
    short: re.compile(r"(?<![A-Za-z0-9_])(?i:" + re.escape(full) + r")\s+\(" + re.escape(short) + r"\)")
    for short, full, mode in ABBREVIATIONS
    if mode == "first"
}


class AbbrevExpander:
    """Expand abbreviations in page reading order so every short form is defined at first use."""

    def __init__(self) -> None:
        self.seen: set[str] = set()

    def expand(self, text: str, *, capitalize_start: bool = True) -> str:
        if not text:
            return text

        def _repl(m: re.Match[str]) -> str:
            matched = m.group(0)
            if matched != "DRC" and matched.startswith("Congo") and matched.endswith("(DRC)"):
                if "DRC" in self.seen:
                    return matched
                self.seen.add("DRC")
                return "Democratic Republic of the Congo (DRC)"
            short = matched
            full, mode = _ABBR_BY_SHORT[short]
            use_full = full
            if capitalize_start and full[0].islower():
                prefix = text[:m.start()]
                if not prefix or re.search(r"(?:^|[.:?!]\s+)$", prefix):
                    use_full = full[0].upper() + full[1:]
            if mode == "always":
                return use_full
            if short in self.seen:
                return short
            self.seen.add(short)
            return f"{use_full} ({short})"

        return _EXPAND_COMBINED_RE.sub(_repl, text)


# Custom locator map frames for countries with distant overseas territories or
# antimeridian crossings so every map is well-framed and honest in its caption.
# Format: ISO -> (lon0, lon1, lat0, lat1, shift_mode, caption_note)
# shift_mode: None | "east" (lon < -30 -> +360, for RU) | "west" (lon > 100 -> -360, for US)
MAP_FRAMES: dict[str, tuple[float, float, float, float, str | None, str]] = {
    "AU": (108.0, 159.0, -45.5, -8.5, None, "Mainland Australia and Tasmania shown."),
    "CA": (-146.0, -48.0, 40.0, 84.0, None, "Canada as the game counts it."),
    "FJ": (175.0, 184.0, -21.0, -12.0, "east", "Fiji as the game counts it."),
    "FR": (-8.5, 13.0, 40.5, 52.2, None, "Metropolitan France and Corsica shown; figures count the whole country."),
    "KI": (168.0, 212.0, -14.0, 8.0, "east", "Kiribati as the game counts it."),
    "NL": (1.5, 9.0, 49.8, 54.5, None, "The European Netherlands shown."),
    "RU": (14.0, 196.0, 38.0, 80.5, "east", "Russia as the game counts it."),
    "US": (-172.0, -62.0, 17.0, 73.0, "west", "The 50 states of the United States shown."),
    "ZA": (12.0, 37.5, -36.5, -20.5, None, "Mainland South Africa shown."),
}

COUNTRY_CONST = re.compile(
    r"^\s*const\s+Set<String>\s+kCountrySheetCountries\s*=\s*<String>\{([^}]*)\}\s*;",
    re.M,
)
ISO_RE = re.compile(r"[a-z]{2}")
ISO_UPPER_RE = re.compile(r"[A-Z]{2}")
BAD_LITERAL_RE = re.compile(r"\b(?:null|NULL|NaN|undefined)\b")
STRAY_NONE_RE = re.compile(r"\bNone\b(?!\s*\(island\))")
MAP_HINT_LOCAL = "Tap the map to see where it is in the world"
MAP_HINT_WORLD = "Tap the map to zoom back in"
THIRD_PARTY_FONT_RE = re.compile(
    r"fonts\.googleapis\.com|fonts\.gstatic\.com|use\.typekit\.net|fonts\.bunny\.net",
    re.I,
)
DAILY_LEAK_RE = re.compile(
    r"\btoday'?s\s+daily\b|\bdaily\s+(?:answer|question|puzzle|challenge)\b",
    re.I,
)


def _is_valid_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


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


def normalize_unit(unit: str) -> str:
    """Normalize awkward raw ARB unit strings into clean plain-English units (Finding 7)."""
    u = unit.strip()
    if u == "annual %":
        return "% a year"
    if u == "$ a person":
        return "dollars a person"
    if u == "kg per person/yr":
        return "kg per person a year"
    if u == "litres/yr":
        return "litres a year"
    if u == "m/1,000 km²":
        return "m per 1,000 km²"
    if u == "people/km²":
        return "people per km²"
    return u


def fmt_plain(v: float | int, unit: str) -> str:
    """Plain-text formatted value (uses ASCII '-' before HTML conversion to &minus;)."""
    if unit.startswith("%"):
        if v == 0:
            return "0%"
        if abs(v) < 0.001:
            return "< 0.001%" if v > 0 else "> -0.001%"
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
    if unit in {"$ a person", "dollars a person"}:
        return f"{v:.2f}"
    if 0 < abs(v) < 0.0001:
        return "< 0.0001" if v > 0 else "> -0.0001"
    if 0 < abs(v) < 0.01:
        return f"{v:.4f}".rstrip("0").rstrip(".")
    if 0 < abs(v) < 0.1:
        return f"{v:.3f}".rstrip("0").rstrip(".")
    if 0 < abs(v) < 1:
        return f"{v:.2f}"
    return f"{v:.1f}"


def fmt_html(v: float | int, unit: str) -> str:
    return html.escape(fmt_plain(v, unit)).replace("-", "&minus;")


def fmt_plain_to_html(s: str) -> str:
    return html.escape(s).replace("-", "&minus;")


def _formatted_decimals(s: str) -> int:
    m = re.search(r"\.(\d+)", s)
    return len(m.group(1)) if m else 0


def _format_at_decimals(vals: list[float | int], unit: str, d: int) -> list[str]:
    use_pct = unit.startswith("%")
    use_tril = not use_pct and any(abs(v) >= 1_000_000_000_000 for v in vals)
    use_bil = not use_pct and not use_tril and unit == "US$" and any(abs(v) >= 10_000_000_000 for v in vals)
    if use_pct:
        return [f"{v:.{d}f}%" for v in vals]
    if use_tril:
        return [f"{v / 1e12:,.{d}f} trillion" for v in vals]
    if use_bil:
        return [f"{v / 1e9:,.{d}f} billion" for v in vals]
    return [f"{v:,.{d}f}" for v in vals]


def format_board_values(
    rows: list[tuple[int, str, float | int]],
    unit: str,
    card_val: str | None = None,
) -> tuple[list[str], list[int]]:
    """Format mini-board values without float noise (at most +2 decimals beyond card precision).

    Returns (formatted_values, display_ranks). Values that remain equal at the maximum
    allowed precision (card_dec + 2) are treated as ties and share the same display rank.
    """
    vals = [v for _, _, v in rows]
    orig_ranks = [r for r, _, _ in rows]
    default = [fmt_plain(v, unit) for v in vals]

    def has_collision(strs: list[str], equiv: list[str] | None = None) -> bool:
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                if equiv is not None:
                    if equiv[i] != equiv[j] and strs[i] == strs[j]:
                        return True
                elif vals[i] != vals[j] and strs[i] == strs[j]:
                    return True
        return False

    if not has_collision(default):
        return default, orig_ranks

    card_dec = _formatted_decimals(card_val) if card_val is not None else max(
        (_formatted_decimals(s) for s in default), default=0
    )
    max_dec = card_dec + 2
    max_strs = _format_at_decimals(vals, unit, max_dec)

    chosen = max_strs
    if not has_collision(default, equiv=max_strs):
        chosen = default
    else:
        for d in range(card_dec + 1, max_dec + 1):
            cand = _format_at_decimals(vals, unit, d)
            if not has_collision(cand, equiv=max_strs):
                chosen = cand
                break

    disp_ranks = list(orig_ranks)
    for i in range(1, len(chosen)):
        if chosen[i] == chosen[i - 1]:
            disp_ranks[i] = disp_ranks[i - 1]
    return chosen, disp_ranks


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


def flag_img(iso: str, cls: str = "", w: int = 32, h: int = 24, lazy: bool = True, prefix: str = "../../") -> str:
    extra = f" {cls}" if cls else ""
    ld = ' loading="lazy"' if lazy else ""
    return f'<img class="flag{extra}" src="{prefix}images/flags/{iso.lower()}.svg" alt="" width="{w}" height="{h}"{ld}>'


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


WORLD_W = 560.0
WORLD_H = 280.0
WORLD_PAD = 8.0
WORLD_LON0 = -180.0
WORLD_LON1 = 180.0
WORLD_LAT0 = -60.0
WORLD_LAT1 = 85.0


def _world_proj(lon: float, lat: float) -> tuple[float, float]:
    clamped_lat = max(WORLD_LAT0, min(WORLD_LAT1, lat))
    x = WORLD_PAD + (lon - WORLD_LON0) / (WORLD_LON1 - WORLD_LON0) * (WORLD_W - 2.0 * WORLD_PAD)
    y = WORLD_PAD + (WORLD_LAT1 - clamped_lat) / (WORLD_LAT1 - WORLD_LAT0) * (WORLD_H - 2.0 * WORLD_PAD)
    return (x, y)


def _world_graticule_d() -> str:
    parts: list[str] = []
    for lon in (-120.0, -60.0, 0.0, 60.0, 120.0):
        x, _ = _world_proj(lon, 0.0)
        parts.append(f"M{x:.0f} 0V{WORLD_H:.0f}")
    for lat in (-30.0, 0.0, 30.0, 60.0):
        _, y = _world_proj(0.0, lat)
        parts.append(f"M0 {y:.0f}H{WORLD_W:.0f}")
    return "".join(parts)


_WORLD_GRAT_D = _world_graticule_d()


def _encode_int_ring(pts: list[tuple[int, int]]) -> str:
    """Encode an integer-coordinate closed ring compactly using relative lineto deltas."""
    x0, y0 = pts[0]
    deltas = []
    px, py = x0, y0
    for ix, iy in pts[1:]:
        deltas.append(f"{ix - px} {iy - py}")
        px, py = ix, iy
    return f"M{x0} {y0}l{' '.join(deltas)}z"


def _build_world_land_d(geo: dict) -> str:
    """Build one shared simplified world land layer from Natural Earth GeoJSON."""
    out: list[str] = []
    for feat in geo["features"]:
        if feat["properties"].get("ISO_A2_EH") == "AQ":
            continue
        for poly in _feature_polys(feat):
            ring = poly[0]
            lons = [pt[0] for pt in ring]
            lats = [pt[1] for pt in ring]
            if max(lons) - min(lons) > 180.0 or max(lats) < WORLD_LAT0:
                continue
            x0, y1 = _world_proj(min(lons), min(lats))
            x1, y0 = _world_proj(max(lons), max(lats))
            if (x1 - x0) < 4.0 and (y1 - y0) < 4.0:
                continue
            pts: list[tuple[int, int]] = []
            last: tuple[float, float] | None = None
            for lon, lat in ring:
                x, y = _world_proj(lon, lat)
                if last is not None and abs(x - last[0]) < 4.8 and abs(y - last[1]) < 4.8:
                    continue
                ix, iy = round(x), round(y)
                if not pts or pts[-1] != (ix, iy):
                    pts.append((ix, iy))
                last = (x, y)
            if len(pts) > 1 and pts[-1] == pts[0]:
                pts.pop()
            if len(set(pts)) >= 3:
                out.append(_encode_int_ring(pts))
    return "".join(out)


def _world_target_and_marker(iso_feats: list[dict], iso: str) -> tuple[str, str]:
    """Return (target_path_d, marker_svg) for the world-context view."""
    primary = [f for f in iso_feats if f["properties"].get("TYPE") != "Dependency"] or iso_feats
    target_feats = [f for f in iso_feats if f["properties"].get("TYPE") != "Dependency" or iso not in {"AU"}]
    target_parts: list[str] = []

    def _wring_int(ring: list, tol: float) -> str:
        pts: list[tuple[int, int]] = []
        last: tuple[float, float] | None = None
        for lon, lat in ring:
            x, y = _world_proj(lon, lat)
            if last is not None and abs(x - last[0]) < tol and abs(y - last[1]) < tol:
                continue
            ix, iy = round(x), round(y)
            if not pts or pts[-1] != (ix, iy):
                pts.append((ix, iy))
            last = (x, y)
        if len(pts) > 1 and pts[-1] == pts[0]:
            pts.pop()
        if len(set(pts)) < 3:
            return ""
        return _encode_int_ring(pts)

    valid_rings: list[list] = []
    for feat in target_feats:
        for poly in _feature_polys(feat):
            ring = poly[0]
            lons = [pt[0] for pt in ring]
            lats = [pt[1] for pt in ring]
            if max(lons) - min(lons) > 180.0 or max(lats) < WORLD_LAT0:
                continue
            valid_rings.append(ring)
            x0, y1 = _world_proj(min(lons), min(lats))
            x1, y0 = _world_proj(max(lons), max(lats))
            if (x1 - x0) < 2.0 and (y1 - y0) < 2.0:
                continue
            d = _wring_int(ring, 2.8)
            if d:
                target_parts.append(d)

    # For microstates/atolls smaller than 2px on the world map, keep one fallback ring
    # alongside the locator ring+dot so the target path is never empty when representable.
    if not target_parts and valid_rings:
        pts_f: list[tuple[str, str]] = []
        for lon, lat in valid_rings[0]:
            x, y = _world_proj(lon, lat)
            pt = (f"{x:.1f}", f"{y:.1f}")
            if not pts_f or pts_f[-1] != pt:
                pts_f.append(pt)
        if len(pts_f) > 1 and pts_f[-1] == pts_f[0]:
            pts_f.pop()
        if len(set(pts_f)) >= 3:
            target_parts.append("M" + "L".join(f"{sx} {sy}" for sx, sy in pts_f) + "Z")

    bboxes: list[tuple[float, float, float, float, float]] = []
    for feat in primary:
        for poly in _feature_polys(feat):
            ring = poly[0]
            lons = [pt[0] for pt in ring]
            lats = [pt[1] for pt in ring]
            if max(lons) - min(lons) > 180.0 or max(lats) < WORLD_LAT0:
                continue
            span = (max(lons) - min(lons)) * (max(lats) - min(lats))
            bboxes.append((span, min(lons), max(lons), min(lats), max(lats)))
    marker_svg = ""
    if bboxes:
        bboxes.sort(reverse=True)
        _, m_lon0, m_lon1, m_lat0, m_lat1 = bboxes[0]
        wx, wy = _world_proj((m_lon0 + m_lon1) / 2.0, (m_lat0 + m_lat1) / 2.0)
        marker_svg = (
            f'<circle cx="{wx:.1f}" cy="{wy:.1f}" r="9" '
            'style="fill:var(--map-pt);fill-opacity:.22;stroke:var(--map-pt);stroke-width:1.8"></circle>'
            f'<circle cx="{wx:.1f}" cy="{wy:.1f}" r="3" '
            'style="fill:var(--map-pt);stroke:var(--map-sea);stroke-width:1.2"></circle>'
        )
    return "".join(target_parts), marker_svg


def render_locator_map(
    iso: str,
    cname: str,
    capital: str | None,
    cap_lat: float | None,
    cap_lon: float | None,
    geo: dict,
    *,
    world_land_d: str | None = None,
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

    def ring_d(ring: list, *, tol_in: float = 1.4) -> str:
        pts: list[tuple[float, float]] = []
        last: tuple[float, float] | None = None
        for lon, lat in ring:
            x, y = proj(lon, lat)
            in_view = -20.0 <= x <= W + 20.0 and -20.0 <= y <= H + 20.0
            tol = tol_in if in_view else 18.0
            if last is not None and abs(x - last[0]) < tol and abs(y - last[1]) < tol:
                continue
            pts.append((x, y))
            last = (x, y)
        if len(pts) < 3:
            return ""
        return "M" + "L".join(f"{x:.1f} {y:.1f}" for x, y in pts) + "Z"

    def feat_d(feat: dict, *, is_target: bool = False) -> str:
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
            if not d and is_target:
                d = ring_d(ring, tol_in=0.0)
            if d:
                out.append(d)
        return "".join(out)

    others: list[str] = []
    target_paths: list[str] = []
    target_xs: list[float] = []
    target_ys: list[float] = []
    for feat in geo["features"]:
        code = feat["properties"].get("ISO_A2_EH")
        is_tgt = code == iso and (feat["properties"].get("TYPE") != "Dependency" or iso not in {"AU"})
        d = feat_d(feat, is_target=is_tgt)
        if is_tgt:
            for poly in _feature_polys(feat):
                ring = poly[0]
                slons = [_shift_lon(pt[0], shift_mode) for pt in ring]
                lats = [pt[1] for pt in ring]
                if max(slons) - min(slons) > 180.0:
                    continue
                if max(slons) < lon0 or min(slons) > lon1 or max(lats) < lat0 or min(lats) > lat1:
                    continue
                for lon, lat in ring:
                    px, py = proj(lon, lat)
                    if 0 <= px <= W and 0 <= py <= H:
                        target_xs.append(px)
                        target_ys.append(py)
        if not d:
            continue
        if is_tgt:
            target_paths.append(d)
        else:
            others.append(d)

    # For tiny microstates / atolls whose projected outline is < 8px across, add a subtle locator ring.
    micro_svg = ""
    if target_xs and target_ys:
        span_x = max(target_xs) - min(target_xs)
        span_y = max(target_ys) - min(target_ys)
        if span_x < 8.0 and span_y < 8.0:
            mx = (min(target_xs) + max(target_xs)) / 2.0
            my = (min(target_ys) + max(target_ys)) / 2.0
            micro_svg = (
                f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="7" '
                'style="fill:var(--map-pt);fill-opacity:.25;stroke:var(--map-pt);stroke-width:1.6"></circle>'
            )

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
    if capital and _is_valid_number(cap_lat) and _is_valid_number(cap_lon):
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

    w_land = world_land_d if world_land_d is not None else _build_world_land_d(geo)
    w_target, w_marker = _world_target_and_marker(iso_feats, iso)

    cname_prose = country_in_prose(iso, cname)
    cap_text = f"{frame_note} " if frame_note else f"{country_in_prose(iso, cname, start=True)} as the game counts it. "
    aria = f"Locator map of {cname_prose}" + (f" showing {capital}" if capital else "") + "."
    world_aria = f"World map showing where {cname_prose} is."
    toggle_aria = f"Switch between close-up map and world map of {cname_prose}"
    return (
        f'<figure class="map a-map">'
        f'<input type="checkbox" class="map-in" id="map-view" aria-label="{html.escape(toggle_aria, quote=True)}">'
        f'<label class="map-btn" for="map-view">'
        f'<span class="map-frame map-local">'
        f'<svg viewBox="0 0 {W:.0f} {H:.0f}" role="img" aria-label="{html.escape(aria, quote=True)}">'
        f'<rect width="{W:.0f}" height="{H:.0f}" style="fill:var(--map-sea)"></rect>'
        f'<path d="{"".join(grat)}" style="fill:none;stroke:var(--map-grid);stroke-width:.8"></path>'
        f'<path d="{"".join(others)}" style="fill:var(--map-land);stroke:var(--map-edge);stroke-width:.8;stroke-linejoin:round"></path>'
        f'<path d="{"".join(target_paths)}" style="fill:var(--map-pt);stroke:var(--map-pt);stroke-width:1.2;stroke-linejoin:round"></path>'
        f'{micro_svg}{cap_svg}'
        '</svg>'
        '</span>'
        f'<span class="map-frame map-world">'
        f'<svg viewBox="0 0 {WORLD_W:.0f} {WORLD_H:.0f}" role="img" aria-label="{html.escape(world_aria, quote=True)}">'
        f'<rect width="{WORLD_W:.0f}" height="{WORLD_H:.0f}" style="fill:var(--map-sea)"></rect>'
        f'<path d="{_WORLD_GRAT_D}" style="fill:none;stroke:var(--map-grid);stroke-width:.8"></path>'
        f'<path d="{w_land}" style="fill:var(--map-land);stroke:var(--map-edge);stroke-width:.6;stroke-linejoin:round"></path>'
        f'<path d="{w_target}" style="fill:var(--map-pt);stroke:var(--map-pt);stroke-width:1;stroke-linejoin:round"></path>'
        f'{w_marker}'
        '</svg>'
        '</span>'
        f'<span class="map-hint map-hint-local">{MAP_HINT_LOCAL}</span>'
        f'<span class="map-hint map-hint-world">{MAP_HINT_WORLD}</span>'
        '</label>'
        f'<figcaption class="mapcap">{html.escape(cap_text)}Map: Natural Earth 1:50 million, public domain.</figcaption>'
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

    # Fail closed if any axis declared in SECTIONS is no longer 'allowed' or is denied (Story 18.6 / Finding 6).
    section_axes = {ax for _, _, axs in SECTIONS for ax in axs}
    for ax in sorted(section_axes):
        if ax in policy and policy[ax] != "allowed":
            raise SheetError(
                f"refusing to publish axis {ax!r}: listed in SECTIONS with web_republish={policy[ax]!r} (must be 'allowed')"
            )
        if ax in deny_list:
            raise SheetError(
                f"refusing to publish axis {ax!r}: listed in SECTIONS and on {DENY_FILE} ({deny_list[ax]})"
            )

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
        "world_land_d": _build_world_land_d(geo),
        "capitals": capitals,
        "arb": arb,
        "axis_keys": axis_keys,
        "published_axes": published_axes,
        "deny_list": deny_list,
    }


def roster_countries(bundle: dict) -> tuple[str, ...]:
    """Derive the sorted lowercase ISO2 country roster from the game bundle (fail closed)."""
    roster = bundle.get("roster")
    if not isinstance(roster, dict) or not roster:
        raise SheetError("pipeline/roster/countries.json has no countries")
    bad_codes = sorted(k for k in roster if not isinstance(k, str) or not ISO_UPPER_RE.fullmatch(k))
    if bad_codes:
        raise SheetError(f"pipeline/roster/countries.json has invalid ISO2 code(s): {bad_codes}")
    continents = (bundle.get("dataset") or {}).get("facets", {}).get("continent") or {}
    missing_continent = sorted(k for k in roster if k not in continents or not isinstance(continents[k], str) or not continents[k].strip())
    if missing_continent:
        raise SheetError(f"dataset.json facets.continent is missing roster country/countries: {missing_continent}")
    return tuple(sorted(k.lower() for k in roster))


def _validate_iso_list(raw: object, field: str, label: str) -> tuple[list[str] | None, list[str]]:
    if not isinstance(raw, list) or not raw:
        return None, [f"{label}: missing or empty {field!r}"]
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not ISO_RE.fullmatch(item) or item in seen:
            return None, [f"{label}: invalid or duplicate ISO2 entry {item!r} in {field!r}"]
        seen.add(item)
        out.append(item)
    return sorted(out), []


def manifest_countries_lists(manifest: dict, label: str = MANIFEST_FILE) -> tuple[list[str], list[str], list[str]]:
    """Return (roster_list, site_list, errors) from a sheets manifest (fail closed)."""
    bad: list[str] = []
    roster_list, err_r = _validate_iso_list(manifest.get("roster_countries"), "roster_countries", label)
    site_list, err_s = _validate_iso_list(manifest.get("countries_list"), "countries_list", label)
    bad += err_r + err_s
    if roster_list is None or site_list is None:
        return roster_list or [], site_list or [], bad
    missing_from_site = sorted(set(roster_list) - set(site_list))
    extra_in_site = sorted(set(site_list) - set(roster_list))
    if missing_from_site:
        bad.append(f"{label}: roster country/countries missing from website set: {missing_from_site}")
    if extra_in_site:
        bad.append(f"{label}: unexpected country/countries outside roster: {extra_in_site}")
    return roster_list, site_list, bad


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
        name, raw_unit = split_name(label)
        name = SHEET_NAME_OVERRIDES.get(ax, name)
        unit = normalize_unit(raw_unit)
        unit_txt = unit[1:].strip() if unit.startswith("%") else unit
        vals = sorted(
            (c["sort_value"] for c in cs.values() if isinstance(c, dict) and _is_valid_number(c.get("sort_value"))),
            reverse=True,
        )
        rec = cs.get(iso_upper)
        default_ver = _axis_default_ver(cs)
        if rec is None or not isinstance(rec, dict) or not _is_valid_number(rec.get("sort_value")):
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
                "year": str(ver.get("vintage") or ""),
                "url": str(ver.get("source_url") or ""),
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
            "year": str(ver.get("vintage") or ""),
            "url": str(ver.get("source_url") or ""),
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
        ((c["sort_value"], i) for i, c in cs.items() if isinstance(c, dict) and _is_valid_number(c.get("sort_value"))),
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
    """Top 4 axes where the country stands out (best rank/n ratio, preferring untied)."""
    clean = [f for f in facts.values() if not f["nodata"] and f["tied"] == 0]
    if len(clean) < 4:
        clean = [f for f in facts.values() if not f["nodata"] and f["tied"] <= 2]
    if len(clean) < 4:
        clean = [f for f in facts.values() if not f["nodata"]]
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


def select_short_axes(facts: dict[str, dict]) -> list[str]:
    """Deterministic short-layout selection: core Sally staples (with data) + country's strongest ranks up to 20."""
    selected: list[str] = [ax for ax in SHORT_CORE_AXES if ax in facts and not facts[ax]["nodata"]]
    chosen = set(selected)
    remaining = [f for ax, f in facts.items() if ax not in chosen and not f["nodata"]]
    remaining.sort(
        key=lambda f: (
            0 if f["tied"] == 0 else (1 if f["tied"] <= 2 else 2),
            f["rank"] / f["n"],
            f["rank"],
            f["ax"],
        )
    )
    for f in remaining:
        if len(selected) >= SHORT_TARGET_FACTS:
            break
        selected.append(f["ax"])
    return selected


def short_sections_for(selected_axes: list[str]) -> list[tuple[str, str, list[str]]]:
    """Group selected short-layout axes into Sally's themed sections."""
    sel = set(selected_axes)
    full_by_key = {key: axs for key, _title, axs in SECTIONS}
    used: set[str] = set()
    out: list[tuple[str, str, list[str]]] = []
    for key, title, full_keys in SHORT_SECTIONS:
        ordered = [a for fk in full_keys for a in full_by_key.get(fk, []) if a in sel]
        if ordered:
            out.append((key, title, ordered))
            used.update(ordered)
    leftover = sorted(sel - used)
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


def compute_sheet_expectation(bundle: dict, iso_lower: str, layout: str = "full") -> dict:
    """Compute exact rendered text for hero, map caption, mini-boards, notes, and fact cards in reading order."""
    if layout not in {"full", "short"}:
        raise SheetError(f"unsupported layout {layout!r} (must be 'full' or 'short')")
    iso = iso_lower.upper()
    roster = bundle["roster"]
    if iso not in roster:
        raise SheetError(f"{iso}: not in pipeline/roster/countries.json")
    cname = roster[iso]["name"]
    ds = bundle["dataset"]
    all_facts = compute_axis_facts(bundle, iso)
    if layout == "short":
        selected_axes = select_short_axes(all_facts)
        shown_facts = {ax: all_facts[ax] for ax in selected_axes}
        secs = short_sections_for(selected_axes)
    else:
        shown_facts = all_facts
        secs = sections_for(bundle["published_axes"])
    standout = standout_facts(shown_facts) if layout == "short" else []
    rules = active_consistency_rules(bundle, iso, shown_facts)

    # Expand abbreviations strictly in page reading order (Finding 8):
    # 0. Hero h1 -> 1. Hero metadata -> 2. Map caption -> 3. Standout mini-boards (short only) -> 4. Sections (notes, then fact cards) -> 5. .a-how
    exp = AbbrevExpander()
    h1_name = exp.expand(cname)

    continent = ds["facets"]["continent"][iso]
    capital = (bundle["capitals"].get(iso) or "").strip() or None
    cap_lat = ds["attributes"].get("capital_lat", {}).get(iso)
    cap_lon = ds["attributes"].get("capital_lon", {}).get(iso)
    neighbours = ds["field_sets"].get("land_neighbours", {}).get(iso) or []
    border_names = ", ".join(neighbour_name(n, roster, bundle["geo"]) for n in neighbours) if neighbours else "None (island)"
    border_names_exp = exp.expand(border_names)
    tz_count = len(ds["field_sets"].get("time_zones", {}).get(iso) or [])

    meta_items: list[tuple[str, str, bool]] = []
    if capital:
        meta_items.append(("Capital", exp.expand(capital), False))
    meta_items.append(("Region", exp.expand(continent), False))
    meta_items.append(("Time-zone regions", str(tz_count), False))
    meta_items.append(("Borders", border_names_exp, len(neighbours) > 3 or len(border_names_exp) > 25))

    # Standout mini-boards (capped decimal precision without float noise — Finding 2)
    boards: list[dict] = []
    needed_flags: set[str] = {iso_lower}
    for f in standout:
        nb = sorted_neighbours(bundle, f["ax"], iso)
        fmt_vals, disp_ranks = format_board_values(nb, f["unit"], card_val=f["val_plain"])
        b_title = exp.expand(f["name"], capitalize_start=True)
        b_unit = exp.expand(f["unit"], capitalize_start=False) if f["unit"] else ""
        b_rows: list[dict] = []
        me_idx: int | None = None
        for idx, ((_r, other_iso, _raw_v), val_plain, dr) in enumerate(zip(nb, fmt_vals, disp_ranks)):
            needed_flags.add(other_iso.lower())
            if other_iso == iso:
                me_idx = idx
            b_rows.append({
                "iso": other_iso,
                "is_me": other_iso == iso,
                "rank": ordinal(dr),
                "name": exp.expand(roster[other_iso]["name"]),
                "val": val_plain,
            })
        if me_idx is not None:
            me_disp_rank = disp_ranks[me_idx]
            board_tied = sum(1 for s in fmt_vals if s == fmt_vals[me_idx]) - 1
            eff_tied = max(f["tied"], board_tied)
            b_rank_txt = f"{ordinal(me_disp_rank)} of {f['n']}" + (f", tied with {eff_tied}" if eff_tied else "")
        else:
            b_rank_txt = f["rank_txt"]
        b_src = exp.expand(f["src"], capitalize_start=True)
        b_src_yr = f'{b_src}, {f["year"]}' if f["year"] else b_src
        b_bsrc = f'{b_rank_txt} \u00b7 {b_src_yr}'
        boards.append({
            "ax": f["ax"],
            "title": b_title,
            "unit": b_unit,
            "src": b_src,
            "year": f["year"],
            "rank_txt": b_rank_txt,
            "bsrc": b_bsrc,
            "rows": b_rows,
        })

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

    # Fact sections (notes before cards, matching rendered DOM reading order)
    rendered_sections: list[dict] = []
    cards_by_ax: dict[str, dict] = {}
    for key, title, axs in secs:
        if not axs:
            continue
        sec_notes: list[dict] = []
        for r in sec_rules.get(key, []):
            sec_notes.append({
                "rule": r["rule"],
                "axes": r["axes"],
                "label": exp.expand(r["label"], capitalize_start=True),
                "note": exp.expand(r["note"], capitalize_start=True),
            })
        sec_cards: list[dict] = []
        for ax in axs:
            f = shown_facts[ax]
            c_name = exp.expand(f["name"], capitalize_start=True)
            c_src = exp.expand(f["src"], capitalize_start=True)
            src_host = host_label(f["url"]) if f["url"] else ""
            src_head = f'{c_src}, {f["year"]}' if f["year"] else c_src
            src_text = src_head + (f" \u00b7 {src_host}" if src_host else "")
            if f["nodata"]:
                c_unit = ""
            else:
                c_unit = exp.expand(f["unit_txt"], capitalize_start=False) if f["unit_txt"] else ""
            card = {
                "ax": ax,
                "name": c_name,
                "val": f["val_plain"],
                "unit": c_unit,
                "rank": f["rank_txt"],
                "src": c_src,
                "year": f["year"],
                "url": f["url"],
                "src_text": src_text,
                "nodata": f["nodata"],
            }
            sec_cards.append(card)
            cards_by_ax[ax] = card
        rendered_sections.append({
            "key": key,
            "title": title,
            "notes": sec_notes,
            "cards": sec_cards,
        })

    return {
        "iso": iso,
        "cname": cname,
        "h1_name": h1_name,
        "continent": continent,
        "capital": capital,
        "cap_lat": cap_lat,
        "cap_lon": cap_lon,
        "meta_items": meta_items,
        "boards": boards,
        "sections": rendered_sections,
        "cards": cards_by_ax,
        "shown_axes": sorted(shown_facts),
        "rules": rules,
        "needed_flags": needed_flags,
    }


def render_sheet(
    bundle: dict,
    iso_lower: str,
    root: pathlib.Path,
    layout: str = "short",
    asset_prefix: str = "../../",
    full_fact_count: int | None = None,
) -> tuple[str, dict, set[str], str]:
    """Render one country sheet HTML (short or full), its manifest record, needed flag ISOs, and country name."""
    spec = compute_sheet_expectation(bundle, iso_lower, layout=layout)
    iso = spec["iso"]
    cname = spec["cname"]
    h1_name = spec["h1_name"]
    cname_prose = country_in_prose(iso, cname)
    continent = spec["continent"]
    ds = bundle["dataset"]
    e = html.escape

    meta_html = "".join(
        f'<div class="a-m{" a-m-wide" if wide else ""}"><span>{e(k)}</span><b>{e(v)}</b></div>'
        for k, v, wide in spec["meta_items"]
    )

    hero_html = (
        f'<div class="card a-sh">'
        f'<div class="a-sh-top">{flag_img(iso, "flag-xl", 88, 66, lazy=False, prefix=asset_prefix)}'
        f'<div><p class="a-crumb">Countries &rsaquo; {e(continent)}</p><h1 class="left">{e(h1_name)}</h1></div></div>'
        f'<div class="a-meta">{meta_html}</div>'
        f'</div>'
    )

    map_html = render_locator_map(
        iso, cname, spec["capital"], spec["cap_lat"], spec["cap_lon"], bundle["geo"],
        world_land_d=bundle.get("world_land_d"),
    )

    # Standout mini-boards (summary page only)
    boards_parts: list[str] = []
    manifest_boards: list[dict] = []
    for b in spec["boards"]:
        rows_html = []
        manifest_rows = []
        for row in b["rows"]:
            me_cls = " a-me" if row["is_me"] else ""
            rows_html.append(
                f'<div class="band a-mb{me_cls}">'
                f'<span class="a-mb-n">{e(row["rank"])}</span>'
                f'{flag_img(row["iso"], "", 28, 21, prefix=asset_prefix)}'
                f'<span class="bname">{e(row["name"])}</span>'
                f'<b class="a-mb-v">{fmt_plain_to_html(row["val"])}</b>'
                f'</div>'
            )
            manifest_rows.append({"rank": row["rank"], "name": row["name"], "val": row["val"]})
        unit_disp = e(b["unit"]) if b["unit"] else "&nbsp;"
        b_src_yr = f'{e(b["src"])}, {e(b["year"])}' if b["year"] else e(b["src"])
        boards_parts.append(
            f'<figure class="a-board" data-axis="{e(b["ax"])}">'
            f'<figcaption><span class="a-bq">{e(b["title"])}</span><span class="a-bu">{unit_disp}</span></figcaption>'
            f'<div class="cap">&#9650; MOST</div>'
            f'{"".join(rows_html)}'
            f'<p class="a-bsrc">{e(b["rank_txt"])} &middot; {b_src_yr}</p>'
            f'</figure>'
        )
        manifest_boards.append({
            "ax": b["ax"],
            "title": b["title"],
            "unit": b["unit"],
            "bsrc": b["bsrc"],
            "rows": manifest_rows,
        })
    if layout == "short" and boards_parts:
        standout_block = (
            f'      <section class="a-fs">'
            f'<h2 class="left">Where {e(cname_prose)} stands out</h2>'
            f'<div class="a-boards">{"".join(boards_parts)}</div>'
            f'</section>\n'
        )
    else:
        standout_block = ""

    # Fact sections
    sec_parts: list[str] = []
    for sec in spec["sections"]:
        if not sec["cards"]:
            continue
        notes_html = "".join(
            f'<p class="a-cnote" data-consistency-rule="{e(r["rule"])}" '
            f'data-consistency-axes="{e(",".join(r["axes"]))}">'
            f'<strong>{e(r["label"])}:</strong> {e(r["note"])}</p>'
            for r in sec["notes"]
        )
        row_parts: list[str] = []
        for card in sec["cards"]:
            src_host = host_label(card["url"]) if card["url"] else ""
            src_head = f'{e(card["src"])}, {e(card["year"])}' if card["year"] else e(card["src"])
            src_label = src_head + (f" &middot; {e(src_host)}" if src_host else "")
            src_el = (
                f'<a class="a-f-s" href="{e(card["url"], quote=True)}" rel="noopener noreferrer">{src_label}</a>'
                if card["url"] else f'<span class="a-f-s">{src_label}</span>'
            )
            if card["nodata"]:
                val_el = '<b class="a-nd">No data</b><span class="a-rk a-rk-nd">Not ranked</span>'
            else:
                usp = f'<small> {e(card["unit"])}</small>' if card["unit"] else ""
                val_el = f'<b>{fmt_plain_to_html(card["val"])}{usp}</b><span class="a-rk">{e(card["rank"])}</span>'
            row_parts.append(
                f'<div class="band a-f" data-axis="{e(card["ax"])}">'
                f'<div class="a-f-l"><span class="a-f-n">{e(card["name"])}</span>{src_el}</div>'
                f'<div class="a-f-r">{val_el}</div>'
                f'</div>'
            )
        sec_parts.append(
            f'<section class="a-fs" id="sec-{e(sec["key"])}">'
            f'<h2 class="left">{e(sec["title"])}</h2>'
            f'{notes_html}'
            f'{"".join(row_parts)}'
            f'</section>'
        )

    n_all_axes = len(ds["axes"])
    n_have_all = sum(
        1 for a in ds["axes"]
        if iso in ds["axes"][a] and isinstance(ds["axes"][a][iso], dict)
        and _is_valid_number(ds["axes"][a][iso].get("sort_value"))
    )
    head_prose = f"the {h1_name}" if h1_name != cname and iso == "CD" else cname_prose
    if layout == "short":
        if full_fact_count is None:
            raise SheetError(f"{iso_lower}: short sheet requires full_fact_count")
        rel = f"countries/{iso_lower}/index.html"
        title_str = f"{h1_name} — Sorting Geography"
        subnav_html = ""
        closing_html = (
            '<div class="a-closing">'
            f'<p class="a-more"><a class="a-more-link" href="./all/">See all {full_fact_count} facts about {e(cname_prose)}</a></p>'
            f'<p class="a-how">Showing {len(spec["shown_axes"])} highlights for {e(cname_prose)}. '
            f'Rank counts from the highest value among the countries that have data: '
            f'1st is the most. Ties share a rank. Data version {bundle["vnum"]}, {e(bundle["vdate"])}.</p>'
            '</div>'
        )
    else:
        rel = f"countries/{iso_lower}/all/index.html"
        title_str = f"All facts about {head_prose} — Sorting Geography"
        subnav_html = (
            '\n<nav class="a-subnav" aria-label="Country sheet view">\n'
            '  <div class="a-subnav-in">\n'
            f'    <a class="a-back-summary" href="../">{ic_back()}Back to the summary</a>\n'
            '  </div>\n'
            '</nav>'
        )
        closing_html = (
            f'<p class="a-how">Rank counts from the highest value among the countries that have data: '
            f'1st is the most. Ties share a rank. Data version {bundle["vnum"]}, {e(bundle["vdate"])}.</p>'
        )

    if n_have_all == n_all_axes:
        play_count_line = f"The game has figures for {e(cname_prose)} on all {n_all_axes} questions."
    else:
        play_count_line = f"The game has figures for {e(cname_prose)} on {n_have_all} of its {n_all_axes} questions."
    play_html = (
        f'<div class="card a-play">'
        f'<h3>Sort {e(cname_prose)} against four others</h3>'
        f'<p>{play_count_line}</p>'
        f'<!-- launch:sheet-play --><!-- /launch:sheet-play -->'
        f'</div>'
    )

    desc = (
        f"Real, sourced facts and world rankings for {head_prose} from Sorting Geography: "
        f"size, borders, people, economy, food and energy."
    )
    raw_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title_str)}</title>
<meta name="description" content="{e(desc, quote=True)}">
<!-- seo:head --><!-- /seo:head -->
<meta name="robots" content="noindex,follow">
<link rel="stylesheet" href="{asset_prefix}style.css">
</head>
<body>
<header class="hd">
  <div class="hd-in">
    <a class="wm" href="{asset_prefix}">{ic_globe("ic wm-ic")}<span>Sorting&nbsp;Geography</span></a>
    <nav class="hd-links">
      <a href="{asset_prefix}#how-to-play">How to play</a>
      <a href="{asset_prefix}#daily">Daily</a>
      <a href="{asset_prefix}#faq">FAQ</a>
    </nav>
    <div class="hd-end">
      <a class="btn btn-sm only-pre" href="{asset_prefix}#notify">Get notified</a>
      <a class="btn btn-sm only-post" href="{asset_prefix}#launch">Get the app</a>
    </div>
  </div>
</header>

<div class="fromgame">
  <div class="fromgame-in">
    <a href="{asset_prefix}">{ic_back()}Back to the game</a>
    <span>Opened from the game</span>
  </div>
</div>{subnav_html}

<main class="da">
  <div class="a-shw">
    <div class="a-side-top">
      {hero_html}
      {map_html}
    </div>
    <div class="a-main">
{standout_block}      <div class="a-fcols">
        {"".join(sec_parts)}
      </div>
      {closing_html}
    </div>
    <div class="a-side-play">
      {play_html}
    </div>
  </div>
</main>

<footer class="ft">
  <div class="ft-in">
    <div class="ft-brand">
      <a class="wm" href="{asset_prefix}">{ic_globe("ic wm-ic")}<span>Sorting&nbsp;Geography</span></a>
    </div>
    <nav class="ft-links">
      <a href="{asset_prefix}#faq">FAQ</a>
      <a href="{asset_prefix}credits.html">Data sources</a>
      <a href="{asset_prefix}press/">Press</a>
      <a href="{asset_prefix}support/">Support</a>
      <a href="{asset_prefix}privacy/">Privacy</a>
      <a href="{asset_prefix}terms/">Terms</a>
    </nav>
    <p class="ft-fam">Part of the Sorting family, with Sorting History.</p>
  </div>
</footer>
</body>
</html>
"""
    # Fill seo:head and launch:sheet-play regions cleanly using the site's builders.
    ms = build_launch.release_ms(root)
    gen_launch = build_launch.regions(ms, lang="en", root=root, root_prefix=asset_prefix)
    rendered = build_launch.render(raw_html, gen_launch, rel)
    rendered = build_seo.render(rel, rendered)

    manifest_entry = {
        "shown_axes": spec["shown_axes"],
        "boards": manifest_boards,
        "values": {
            ax: {
                "val": card["val"],
                "unit": card["unit"],
                "rank": card["rank"],
                "src": card["src"],
                "year": card["year"],
                "url": card["url"],
                "src_text": card["src_text"],
                "nodata": card["nodata"],
            }
            for ax, card in spec["cards"].items()
        },
        "consistency_rules": [r["rule"] for r in spec["rules"]],
    }
    return rendered, manifest_entry, spec["needed_flags"], cname


# ---------------------------------------------------------------------------
# Offline and live-game verification guards (HTMLParser-based, Finding 5)
# ---------------------------------------------------------------------------

VOID_TAGS: frozenset[str] = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})
EXTERNAL_OR_DATA_URL_RE = re.compile(r"^(?:https?:|//|data:|javascript:)", re.I)
REQUIRED_ASSETSIGNORE: tuple[str, ...] = (".gitignore", ".neon-test.sh")


def _is_external_or_data_url(url: str) -> bool:
    return bool(EXTERNAL_OR_DATA_URL_RE.match(url.strip()))


class _SheetHTMLParser(HTMLParser):
    """Single-pass HTMLParser extracting security/SEO/overflow signals, data-axis, fact cards, mini-boards, notes, navigation links, and visible text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[tuple[str, set[str], dict[str, str]]] = []
        self._order = 0
        self.all_data_axes: list[str] = []

        # Security / SEO / Overflow
        self.has_noindex_follow = False
        self.canonical_hrefs: list[str] = []
        self.has_viewport = False
        self.disallowed_scripts: list[str] = []
        self.external_resources: list[str] = []
        self.inline_handlers: list[str] = []
        self.third_party_fonts: list[str] = []
        self.overflow_styles: list[str] = []
        self.overflow_svgs: list[str] = []

        # Content extraction
        self.facts: list[dict] = []
        self.boards: list[dict] = []
        self.consistency_notes: dict[str, str] = {}
        self.fromgame_present = False
        self.fromgame_links: list[tuple[str, str]] = []
        self.closing_present = False
        self.closing_links: list[tuple[str, str]] = []
        self.how_present = False
        self.how_links: list[tuple[str, str]] = []
        self.subnav_present = False
        self.subnav_links: list[tuple[str, str]] = []
        self.h1_text = ""
        self.meta_labels: list[str] = []
        self.has_standout_boards = False
        self.standout_headings: list[str] = []
        self.play_h3_text = ""
        self.play_p_texts: list[str] = []
        self.map_caption_text = ""
        self.map_toggle_inputs: list[tuple[str, str]] = []
        self.map_toggle_labels: list[str] = []
        self.has_map_local_svg = False
        self.has_map_world_svg = False
        self.map_hint_local_text = ""
        self.map_hint_world_text = ""
        self.sections_summary: list[tuple[str, int]] = []

        # DOM placement tracking
        self.fromgame_order: int | None = None
        self.subnav_order: int | None = None
        self.main_order: int | None = None
        self.last_fact_section_order: int | None = None
        self.closing_order: int | None = None
        self.play_card_order: int | None = None

        self._all_visible_parts: list[str] = []
        self._main_visible_parts: list[str] = []
        self._how_parts: list[str] = []

        self._cur_section: list | None = None  # [depth, heading_parts, item_count]
        self._cur_fact: dict | None = None
        self._cur_board: dict | None = None
        self._cur_mb_row: dict | None = None
        self._cur_cnote: tuple[int, str, list[str]] | None = None
        self._cur_nav_anchor: tuple[int, set[str], str, list[str]] | None = None
        self._in_fromgame_depth: int | None = None
        self._in_closing_depth: int | None = None
        self._in_how_depth: int | None = None
        self._in_subnav_depth: int | None = None
        self._in_main_depth: int | None = None
        self._in_svg_depth: int | None = None
        self._in_play_depth: int | None = None
        self._in_play_ls_depth: int | None = None
        self._in_play_h3: tuple[int, list[str]] | None = None
        self._in_play_p: tuple[int, list[str]] | None = None
        self._in_h1: tuple[int, list[str]] | None = None
        self._in_h2: tuple[int, list[str]] | None = None
        self._in_meta_label: tuple[int, list[str]] | None = None
        self._in_mapcap: tuple[int, list[str]] | None = None
        self._in_map_local_depth: int | None = None
        self._in_map_world_depth: int | None = None
        self._in_map_hint_local: tuple[int, list[str]] | None = None
        self._in_map_hint_world: tuple[int, list[str]] | None = None
        self._in_script_depth: int | None = None
        self._in_style_depth: int | None = None
        # Fast depth flags for fact-card and mini-board inner elements
        self._f_name_d: int | None = None
        self._f_src_d: int | None = None
        self._f_r_d: int | None = None
        self._f_b_d: int | None = None
        self._f_small_d: int | None = None
        self._f_rk_d: int | None = None
        self._b_title_d: int | None = None
        self._b_unit_d: int | None = None
        self._b_bsrc_d: int | None = None
        self._mb_n_d: int | None = None
        self._mb_name_d: int | None = None
        self._mb_v_d: int | None = None

    def _check_srcset(self, srcset: str) -> None:
        for cand in srcset.split(","):
            tok = cand.strip().split()
            if tok and _is_external_or_data_url(tok[0]):
                self.external_resources.append(tok[0])

    def _on_open(self, tag: str, attrs: list[tuple[str, str | None]], is_void: bool) -> None:
        tag = tag.lower()
        self._order += 1
        attr_map = {k.lower(): (v if v is not None else "") for k, v in attrs}
        classes = set(attr_map.get("class", "").split())

        # Separator so adjacent elements don't glue tokens in visible text
        self._all_visible_parts.append(" ")
        if (
            self._in_main_depth is not None
            and self._in_svg_depth is None
            and self._in_play_ls_depth is None
            and self._in_script_depth is None
            and self._in_style_depth is None
        ):
            self._main_visible_parts.append(" ")

        # Collect every data-axis attribute anywhere in the document
        if "data-axis" in attr_map and attr_map["data-axis"]:
            self.all_data_axes.append(attr_map["data-axis"])

        # Security / SEO / Overflow attribute checks
        for k, v in attrs:
            kl = k.lower()
            val = v if v is not None else ""
            if kl.startswith("on"):
                self.inline_handlers.append(f"<{tag} {kl}=...>")
            if val and THIRD_PARTY_FONT_RE.search(val):
                self.third_party_fonts.append(val)

        if tag == "meta":
            mname = attr_map.get("name", "").strip().lower()
            mcontent = attr_map.get("content", "").strip()
            if mname == "robots" and mcontent.lower() == "noindex,follow":
                self.has_noindex_follow = True
            if mname == "viewport" and re.fullmatch(r"width=device-width,\s*initial-scale=1", mcontent, re.I):
                self.has_viewport = True

        elif tag == "link":
            rels = set(attr_map.get("rel", "").lower().split())
            href = attr_map.get("href", "").strip()
            if rels == {"canonical"}:
                if href:
                    self.canonical_hrefs.append(href)
            elif href and _is_external_or_data_url(href):
                self.external_resources.append(href)

        elif tag == "script":
            stype = attr_map.get("type", "").strip().lower()
            ssrc = attr_map.get("src", "").strip()
            if stype != "application/ld+json" or ssrc:
                attr_desc = " ".join(f'{k}="{v}"' if v is not None else k for k, v in attrs)
                self.disallowed_scripts.append(f"<script{' ' + attr_desc if attr_desc else ''}>")
            if ssrc and _is_external_or_data_url(ssrc):
                self.external_resources.append(ssrc)

        elif tag in {"img", "iframe", "embed", "source", "audio", "video", "track"}:
            src = attr_map.get("src", "").strip()
            if src and _is_external_or_data_url(src):
                self.external_resources.append(src)
            srcset = attr_map.get("srcset", "").strip()
            if srcset:
                self._check_srcset(srcset)

        elif tag == "object":
            data_url = attr_map.get("data", "").strip()
            if data_url and _is_external_or_data_url(data_url):
                self.external_resources.append(data_url)

        elif tag == "form":
            action = attr_map.get("action", "").strip()
            if action and _is_external_or_data_url(action):
                self.external_resources.append(action)

        elif tag == "a":
            href = attr_map.get("href", "").strip()
            if href and re.match(r"^javascript:", href, re.I):
                self.external_resources.append(href)

        style_val = attr_map.get("style", "")
        if style_val:
            if THIRD_PARTY_FONT_RE.search(style_val):
                self.third_party_fonts.append(style_val)
            for prop_m in re.finditer(r"(?<![a-z-])((?:min-)?width)\s*:\s*(\d+(?:\.\d+)?)px\b", style_val, re.I):
                if float(prop_m.group(2)) > MAX_FIXED_WIDTH_PX:
                    self.overflow_styles.append(prop_m.group(0))

        if tag == "input" and attr_map.get("type", "").strip().lower() == "checkbox" and "map-in" in classes:
            self.map_toggle_inputs.append((attr_map.get("id", "").strip(), attr_map.get("aria-label", "").strip()))

        if tag == "svg":
            w_attr = attr_map.get("width", "").strip()
            if re.fullmatch(r"\d+(?:\.\d+)?", w_attr) and float(w_attr) > MAX_FIXED_WIDTH_PX:
                self.overflow_svgs.append(w_attr)
            if self._in_map_local_depth is not None:
                self.has_map_local_svg = True
            if self._in_map_world_depth is not None:
                self.has_map_world_svg = True

        if not is_void:
            parent_entry = self._stack[-1] if self._stack else None
            self._stack.append((tag, classes, attr_map))
            depth = len(self._stack)

            if tag == "div" and "fromgame" in classes:
                self.fromgame_present = True
                if self.fromgame_order is None:
                    self.fromgame_order = self._order
                if self._in_fromgame_depth is None:
                    self._in_fromgame_depth = depth
            if tag == "main" and self._in_main_depth is None:
                self._in_main_depth = depth
                self.main_order = self._order
            if tag == "section" and "a-fs" in classes:
                if attr_map.get("id", "").startswith("sec-"):
                    self.last_fact_section_order = self._order
                if self._cur_section is None:
                    self._cur_section = [depth, [], 0]
            if tag == "div" and ("a-side-play" in classes or "a-play" in classes) and self.play_card_order is None:
                self.play_card_order = self._order
            if tag == "div" and "a-play" in classes and self._in_play_depth is None:
                self._in_play_depth = depth
            if tag == "div" and "a-boards" in classes:
                self.has_standout_boards = True
            if tag == "svg" and self._in_svg_depth is None:
                self._in_svg_depth = depth
            if "a-play-ls" in classes and self._in_play_ls_depth is None:
                self._in_play_ls_depth = depth
            if tag == "script" and self._in_script_depth is None:
                self._in_script_depth = depth
            if tag == "style" and self._in_style_depth is None:
                self._in_style_depth = depth

            if tag == "h1" and not self.h1_text and self._in_h1 is None:
                self._in_h1 = (depth, [])
            if tag == "h2" and self._in_h2 is None:
                self._in_h2 = (depth, [])
            if tag == "span" and parent_entry is not None and parent_entry[0] == "div" and "a-m" in parent_entry[1]:
                self._in_meta_label = (depth, [])
            if tag == "figcaption" and "mapcap" in classes and self._in_mapcap is None:
                self._in_mapcap = (depth, [])
            if tag == "label" and "map-btn" in classes:
                self.map_toggle_labels.append(attr_map.get("for", "").strip())
            if tag == "span" and "map-local" in classes and self._in_map_local_depth is None:
                self._in_map_local_depth = depth
            if tag == "span" and "map-world" in classes and self._in_map_world_depth is None:
                self._in_map_world_depth = depth
            if tag == "span" and "map-hint-local" in classes and self._in_map_hint_local is None:
                self._in_map_hint_local = (depth, [])
            if tag == "span" and "map-hint-world" in classes and self._in_map_hint_world is None:
                self._in_map_hint_world = (depth, [])
            if self._in_play_depth is not None and self._in_play_ls_depth is None:
                if tag == "h3" and self._in_play_h3 is None:
                    self._in_play_h3 = (depth, [])
                elif tag == "p" and self._in_play_p is None:
                    self._in_play_p = (depth, [])

            if tag == "div" and "a-closing" in classes:
                self.closing_present = True
                self.closing_order = self._order
                self._in_closing_depth = depth
            if tag == "p" and "a-how" in classes:
                self.how_present = True
                self._in_how_depth = depth
            if tag == "nav" and "a-subnav" in classes:
                self.subnav_present = True
                self.subnav_order = self._order
                self._in_subnav_depth = depth

            if tag == "a":
                scopes: set[str] = set()
                if self._in_fromgame_depth is not None:
                    scopes.add("fromgame")
                if self._in_closing_depth is not None:
                    scopes.add("closing")
                if self._in_how_depth is not None:
                    scopes.add("how")
                if self._in_subnav_depth is not None:
                    scopes.add("subnav")
                if scopes:
                    self._cur_nav_anchor = (depth, scopes, attr_map.get("href", "").strip(), [])

            if tag == "p" and "a-cnote" in classes and "data-consistency-rule" in attr_map:
                self._cur_cnote = (depth, attr_map["data-consistency-rule"], [])

            if tag == "div" and "a-f" in classes and "data-axis" in attr_map:
                if self._cur_section is not None:
                    self._cur_section[2] += 1
                self._cur_fact = {
                    "depth": depth,
                    "ax": attr_map["data-axis"],
                    "name": [],
                    "src_text": [],
                    "src_href": "",
                    "val": [],
                    "unit": [],
                    "rank": [],
                    "has_nd_class": False,
                }
            elif self._cur_fact is not None:
                if tag == "span" and "a-f-n" in classes and self._f_name_d is None:
                    self._f_name_d = depth
                elif tag in {"a", "span"} and "a-f-s" in classes:
                    if self._f_src_d is None:
                        self._f_src_d = depth
                    if tag == "a":
                        self._cur_fact["src_href"] = attr_map.get("href", "")
                elif tag == "div" and "a-f-r" in classes and self._f_r_d is None:
                    self._f_r_d = depth
                elif self._f_r_d is not None:
                    if tag == "b":
                        if self._f_b_d is None:
                            self._f_b_d = depth
                        if "a-nd" in classes:
                            self._cur_fact["has_nd_class"] = True
                    elif tag == "small" and self._f_b_d is not None and self._f_small_d is None:
                        self._f_small_d = depth
                    elif tag == "span" and "a-rk" in classes:
                        if self._f_rk_d is None:
                            self._f_rk_d = depth
                        if "a-rk-nd" in classes:
                            self._cur_fact["has_nd_class"] = True

            if tag == "figure" and "a-board" in classes and "data-axis" in attr_map:
                if self._cur_section is not None:
                    self._cur_section[2] += 1
                self._cur_board = {
                    "depth": depth,
                    "ax": attr_map["data-axis"],
                    "title": [],
                    "unit": [],
                    "bsrc": [],
                    "rows": [],
                }
            elif self._cur_board is not None:
                if tag == "div" and "a-mb" in classes:
                    self._cur_mb_row = {
                        "depth": depth,
                        "rank": [],
                        "name": [],
                        "val": [],
                    }
                elif self._cur_mb_row is not None:
                    if tag == "span" and "a-mb-n" in classes and self._mb_n_d is None:
                        self._mb_n_d = depth
                    elif tag == "span" and "bname" in classes and self._mb_name_d is None:
                        self._mb_name_d = depth
                    elif tag == "b" and "a-mb-v" in classes and self._mb_v_d is None:
                        self._mb_v_d = depth
                else:
                    if tag == "span" and "a-bq" in classes and self._b_title_d is None:
                        self._b_title_d = depth
                    elif tag == "span" and "a-bu" in classes and self._b_unit_d is None:
                        self._b_unit_d = depth
                    elif tag == "p" and "a-bsrc" in classes and self._b_bsrc_d is None:
                        self._b_bsrc_d = depth

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._on_open(tag, attrs, is_void=(tag.lower() in VOID_TAGS))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._on_open(tag, attrs, is_void=True)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_TAGS:
            return
        self._all_visible_parts.append(" ")
        if (
            self._in_main_depth is not None
            and self._in_svg_depth is None
            and self._in_play_ls_depth is None
            and self._in_script_depth is None
            and self._in_style_depth is None
        ):
            self._main_visible_parts.append(" ")

        # Pop back to matching tag if present
        match_idx: int | None = None
        for idx in range(len(self._stack) - 1, -1, -1):
            if self._stack[idx][0] == tag:
                match_idx = idx
                break
        if match_idx is None:
            return
        while len(self._stack) > match_idx:
            depth = len(self._stack)
            self._stack.pop()
            if self._in_main_depth == depth:
                self._in_main_depth = None
            if self._in_svg_depth == depth:
                self._in_svg_depth = None
            if self._in_play_depth == depth:
                self._in_play_depth = None
            if self._in_play_ls_depth == depth:
                self._in_play_ls_depth = None
            if self._in_script_depth == depth:
                self._in_script_depth = None
            if self._in_style_depth == depth:
                self._in_style_depth = None
            if self._in_fromgame_depth == depth:
                self._in_fromgame_depth = None
            if self._in_closing_depth == depth:
                self._in_closing_depth = None
            if self._in_how_depth == depth:
                self._in_how_depth = None
            if self._in_subnav_depth == depth:
                self._in_subnav_depth = None
            if self._in_h1 is not None and self._in_h1[0] == depth:
                self.h1_text = " ".join("".join(self._in_h1[1]).split())
                self._in_h1 = None
            if self._in_h2 is not None and self._in_h2[0] == depth:
                h2_txt = " ".join("".join(self._in_h2[1]).split())
                if self._cur_section is not None and not self._cur_section[1]:
                    self._cur_section[1].append(h2_txt)
                if h2_txt.startswith("Where ") and h2_txt.endswith(" stands out"):
                    self.standout_headings.append(h2_txt)
                self._in_h2 = None
            if self._cur_section is not None and self._cur_section[0] == depth:
                sec_h = " ".join(self._cur_section[1]).strip()
                self.sections_summary.append((sec_h, self._cur_section[2]))
                self._cur_section = None
            if self._f_name_d == depth:
                self._f_name_d = None
            if self._f_src_d == depth:
                self._f_src_d = None
            if self._f_r_d == depth:
                self._f_r_d = None
            if self._f_b_d == depth:
                self._f_b_d = None
            if self._f_small_d == depth:
                self._f_small_d = None
            if self._f_rk_d == depth:
                self._f_rk_d = None
            if self._b_title_d == depth:
                self._b_title_d = None
            if self._b_unit_d == depth:
                self._b_unit_d = None
            if self._b_bsrc_d == depth:
                self._b_bsrc_d = None
            if self._mb_n_d == depth:
                self._mb_n_d = None
            if self._mb_name_d == depth:
                self._mb_name_d = None
            if self._mb_v_d == depth:
                self._mb_v_d = None
            if self._in_meta_label is not None and self._in_meta_label[0] == depth:
                self.meta_labels.append(" ".join("".join(self._in_meta_label[1]).split()))
                self._in_meta_label = None
            if self._in_mapcap is not None and self._in_mapcap[0] == depth:
                self.map_caption_text = " ".join("".join(self._in_mapcap[1]).split())
                self._in_mapcap = None
            if self._in_map_local_depth == depth:
                self._in_map_local_depth = None
            if self._in_map_world_depth == depth:
                self._in_map_world_depth = None
            if self._in_map_hint_local is not None and self._in_map_hint_local[0] == depth:
                self.map_hint_local_text = " ".join("".join(self._in_map_hint_local[1]).split())
                self._in_map_hint_local = None
            if self._in_map_hint_world is not None and self._in_map_hint_world[0] == depth:
                self.map_hint_world_text = " ".join("".join(self._in_map_hint_world[1]).split())
                self._in_map_hint_world = None
            if self._in_play_h3 is not None and self._in_play_h3[0] == depth:
                self.play_h3_text = " ".join("".join(self._in_play_h3[1]).split())
                self._in_play_h3 = None
            if self._in_play_p is not None and self._in_play_p[0] == depth:
                self.play_p_texts.append(" ".join("".join(self._in_play_p[1]).split()))
                self._in_play_p = None
            if self._cur_nav_anchor is not None and self._cur_nav_anchor[0] == depth:
                _, scopes, href, parts = self._cur_nav_anchor
                txt = " ".join("".join(parts).split())
                if "fromgame" in scopes:
                    self.fromgame_links.append((href, txt))
                if "closing" in scopes:
                    self.closing_links.append((href, txt))
                if "how" in scopes:
                    self.how_links.append((href, txt))
                if "subnav" in scopes:
                    self.subnav_links.append((href, txt))
                self._cur_nav_anchor = None
            if self._cur_cnote is not None and self._cur_cnote[0] == depth:
                _, rule_id, parts = self._cur_cnote
                self.consistency_notes[rule_id] = " ".join("".join(parts).split())
                self._cur_cnote = None
            if self._cur_fact is not None and self._cur_fact["depth"] == depth:
                f = self._cur_fact
                unit_raw = "".join(f["unit"])
                val_clean = "".join(f["val"]).strip().replace("\u2212", "-")
                rank_clean = " ".join("".join(f["rank"]).split())
                self.facts.append({
                    "ax": f["ax"],
                    "name": " ".join("".join(f["name"]).split()),
                    "src_text": " ".join("".join(f["src_text"]).split()),
                    "src_href": f["src_href"],
                    "val": val_clean,
                    "unit": unit_raw.strip(),
                    "unit_has_nbsp": unit_raw.startswith("\xa0"),
                    "rank": rank_clean,
                    "is_nodata": f["has_nd_class"] or val_clean == "No data" or rank_clean == "Not ranked",
                })
                self._cur_fact = None
            if self._cur_mb_row is not None and self._cur_mb_row["depth"] == depth:
                r = self._cur_mb_row
                if self._cur_board is not None:
                    self._cur_board["rows"].append({
                        "rank": " ".join("".join(r["rank"]).split()),
                        "name": " ".join("".join(r["name"]).split()),
                        "val": "".join(r["val"]).strip().replace("\u2212", "-"),
                    })
                self._cur_mb_row = None
            if self._cur_board is not None and self._cur_board["depth"] == depth:
                b = self._cur_board
                unit_clean = "".join(b["unit"]).replace("\xa0", " ").strip()
                self.boards.append({
                    "ax": b["ax"],
                    "title": " ".join("".join(b["title"]).split()),
                    "unit": unit_clean,
                    "bsrc": " ".join("".join(b["bsrc"]).split()),
                    "rows": b["rows"],
                })
                self._cur_board = None

    def handle_data(self, data: str) -> None:
        if self._in_style_depth is not None and THIRD_PARTY_FONT_RE.search(data):
            self.third_party_fonts.append(data.strip())
        if self._in_script_depth is None and self._in_style_depth is None:
            self._all_visible_parts.append(data)
            if self._in_main_depth is not None and self._in_svg_depth is None and self._in_play_ls_depth is None:
                self._main_visible_parts.append(data)

        if self._cur_nav_anchor is not None and self._in_svg_depth is None:
            self._cur_nav_anchor[3].append(data)

        if self._in_how_depth is not None and self._in_svg_depth is None:
            self._how_parts.append(data)
        if self._in_h1 is not None and self._in_svg_depth is None:
            self._in_h1[1].append(data)
        if self._in_h2 is not None and self._in_svg_depth is None:
            self._in_h2[1].append(data)
        if self._in_meta_label is not None and self._in_svg_depth is None:
            self._in_meta_label[1].append(data)
        if self._in_mapcap is not None and self._in_svg_depth is None:
            self._in_mapcap[1].append(data)
        if self._in_map_hint_local is not None and self._in_svg_depth is None:
            self._in_map_hint_local[1].append(data)
        if self._in_map_hint_world is not None and self._in_svg_depth is None:
            self._in_map_hint_world[1].append(data)
        if self._in_play_h3 is not None and self._in_svg_depth is None:
            self._in_play_h3[1].append(data)
        if self._in_play_p is not None and self._in_svg_depth is None:
            self._in_play_p[1].append(data)

        if self._cur_cnote is not None:
            self._cur_cnote[2].append(data)

        if self._cur_fact is not None:
            if self._f_name_d is not None:
                self._cur_fact["name"].append(data)
            if self._f_src_d is not None:
                self._cur_fact["src_text"].append(data)
            if self._f_r_d is not None:
                if self._f_small_d is not None and self._f_b_d is not None:
                    self._cur_fact["unit"].append(data)
                elif self._f_b_d is not None:
                    self._cur_fact["val"].append(data)
                if self._f_rk_d is not None:
                    self._cur_fact["rank"].append(data)

        if self._cur_board is not None:
            if self._cur_mb_row is not None:
                if self._mb_n_d is not None:
                    self._cur_mb_row["rank"].append(data)
                if self._mb_name_d is not None:
                    self._cur_mb_row["name"].append(data)
                if self._mb_v_d is not None:
                    self._cur_mb_row["val"].append(data)
            else:
                if self._b_title_d is not None:
                    self._cur_board["title"].append(data)
                if self._b_unit_d is not None:
                    self._cur_board["unit"].append(data)
                if self._b_bsrc_d is not None:
                    self._cur_board["bsrc"].append(data)

    @property
    def all_visible_text(self) -> str:
        return " ".join("".join(self._all_visible_parts).split())

    @property
    def main_visible_text(self) -> str:
        return " ".join("".join(self._main_visible_parts).split())

    @property
    def how_text(self) -> str:
        return " ".join("".join(self._how_parts).split())


@functools.lru_cache(maxsize=512)
def _parse_sheet_html(page: str) -> _SheetHTMLParser:
    parser = _SheetHTMLParser()
    parser.feed(page)
    parser.close()
    return parser


def _check_assetsignore(root: pathlib.Path) -> list[str]:
    """Fail if .assetsignore does not exclude .gitignore, .neon-test.sh, or any root dotfile (Finding 1)."""
    p = root / ".assetsignore"
    if not p.is_file():
        return [".assetsignore is missing"]
    entries = {
        ln.strip().strip("/")
        for ln in p.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    bad: list[str] = []
    has_dot_glob = ".*" in entries
    for req in REQUIRED_ASSETSIGNORE:
        if req not in entries and not (req.startswith(".") and has_dot_glob):
            bad.append(f".assetsignore: {req!r} is not ignored (would be publicly served on deploy)")
    for item in sorted(root.iterdir()):
        name = item.name
        if name.startswith(".") and name != ".well-known":
            if name not in entries and not has_dot_glob:
                bad.append(f".assetsignore: dotfile {name!r} at site root is not ignored")
    return bad


def _check_page_security_and_seo(rel: str, want_canon: str, parsed: _SheetHTMLParser) -> list[str]:
    bad: list[str] = []

    # 1. noindex,follow
    if not parsed.has_noindex_follow:
        bad.append(f'{rel}: missing <meta name="robots" content="noindex,follow">')

    # 2. self-canonical
    if parsed.canonical_hrefs != [want_canon]:
        bad.append(f"{rel}: missing or wrong self-canonical {want_canon} (got {parsed.canonical_hrefs!r})")

    # 3. No scripts of any kind (no third-party scripts, no inline scripts)
    for sc in parsed.disallowed_scripts:
        bad.append(f"{rel}: disallowed {sc} on country sheet (no third-party or inline scripts)")

    # 4. No inline event handlers
    for h in parsed.inline_handlers:
        bad.append(f"{rel}: disallowed inline event handler {h}")

    # 5. No Google Fonts or other third-party font services, no external/data resources
    if parsed.third_party_fonts:
        bad.append(f"{rel}: references a third-party font service ({parsed.third_party_fonts[0]!r})")
    for url in parsed.external_resources:
        bad.append(f"{rel}: loads external or data resource {url!r}")

    # 6. No Daily answer / today's Daily question
    m_daily = DAILY_LEAK_RE.search(parsed.all_visible_text)
    if m_daily:
        bad.append(f"{rel}: mentions {m_daily.group(0)!r} (no Daily question or answer on country sheets)")

    return bad


def _check_fromgame_bar(rel: str, parsed: _SheetHTMLParser, want_href: str) -> list[str]:
    """Both short and full pages must have the .fromgame bar before <main> with one 'Back to the game' link."""
    bad: list[str] = []
    if not parsed.fromgame_present:
        bad.append(f"{rel}: missing 'Back to the game' bar (.fromgame)")
        return bad
    if parsed.fromgame_order is None or parsed.main_order is None or not (parsed.fromgame_order < parsed.main_order):
        bad.append(f"{rel}: 'Back to the game' bar (.fromgame) must appear before <main>")
    if len(parsed.fromgame_links) == 0:
        bad.append(f"{rel}: 'Back to the game' bar (.fromgame) is missing link to {want_href!r}")
    elif len(parsed.fromgame_links) > 1:
        bad.append(
            f"{rel}: 'Back to the game' bar (.fromgame) must contain exactly one link "
            f"(found {len(parsed.fromgame_links)}: {parsed.fromgame_links!r})"
        )
    else:
        href, text = parsed.fromgame_links[0]
        if href != want_href:
            bad.append(f"{rel}: 'Back to the game' link href {href!r} must be {want_href!r}")
        if text != "Back to the game":
            bad.append(f"{rel}: 'Back to the game' link text {text!r} != 'Back to the game'")
    return bad


def _check_short_no_nodata(rel: str, parsed: _SheetHTMLParser) -> list[str]:
    """Short pages must never show a 'No data' / 'Not ranked' fact card."""
    bad: list[str] = []
    for card in parsed.facts:
        if card["is_nodata"]:
            bad.append(f"{rel}: short page must not show a 'No data' fact card ({card['ax']!r})")
    return bad


def _check_country_wording(
    rel: str,
    iso: str,
    cname: str,
    layout: str,
    parsed: _SheetHTMLParser,
    shown_count: int | None = None,
) -> list[str]:
    """Verify bare <h1>, 'the'/'The' before country names in running prose, hero label, standout placement, and play card wording."""
    bad: list[str] = []
    cname_prose = country_in_prose(iso, cname)
    cname_start = country_in_prose(iso, cname, start=True)
    want_h1 = AbbrevExpander().expand(cname)

    if parsed.h1_text != want_h1:
        bad.append(f"{rel}: <h1> {parsed.h1_text!r} != bare country name {want_h1!r}")

    if "Time zones" in parsed.meta_labels:
        bad.append(f"{rel}: hero card uses 'Time zones' instead of 'Time-zone regions'")
    if "Time-zone regions" not in parsed.meta_labels:
        bad.append(f"{rel}: hero card is missing 'Time-zone regions' label")

    want_play_h3 = f"Sort {cname_prose} against four others"
    if parsed.play_h3_text != want_play_h3:
        bad.append(f"{rel}: play card heading {parsed.play_h3_text!r} != {want_play_h3!r}")

    want_play_prefix = f"The game has figures for {cname_prose} on "
    matching_play = [p for p in parsed.play_p_texts if p.startswith(want_play_prefix)]
    if not matching_play:
        bad.append(f"{rel}: play card missing sentence starting with {want_play_prefix!r} (got {parsed.play_p_texts!r})")
    else:
        for p in matching_play:
            m_same = re.search(r"\bon (\d+) of its \1 questions\.", p)
            if m_same:
                bad.append(
                    f"{rel}: play card uses awkward 'on {m_same.group(1)} of its {m_same.group(1)} questions.' "
                    f"(use 'on all {m_same.group(1)} questions.')"
                )

    if layout == "short":
        want_standout = f"Where {cname_prose} stands out"
        if parsed.boards:
            if parsed.standout_headings != [want_standout]:
                bad.append(f"{rel}: short page standout heading {parsed.standout_headings!r} != [{want_standout!r}]")
        else:
            if parsed.standout_headings:
                bad.append(f"{rel}: short page has standout heading {parsed.standout_headings!r} with no mini-boards")
        if shown_count is not None:
            want_how_prefix = f"Showing {shown_count} highlights for {cname_prose}."
            if not parsed.how_text.startswith(want_how_prefix):
                bad.append(f"{rel}: short page .a-how text must start with {want_how_prefix!r} (got {parsed.how_text[:80]!r})")
    else:
        if parsed.standout_headings or parsed.has_standout_boards or parsed.boards:
            bad.append(f"{rel}: full page must not include 'Where ... stands out' section or mini-boards")

    if iso.upper() in COUNTRIES_WITH_THE:
        if parsed.map_caption_text.startswith(f"{cname} "):
            bad.append(f"{rel}: map caption starts with bare {cname!r} instead of {cname_start!r}")
        if iso.upper() == "NL" and parsed.map_caption_text.startswith("European Netherlands "):
            bad.append(f"{rel}: map caption starts with 'European Netherlands' instead of 'The European Netherlands'")

    return bad


def _check_short_closing(rel: str, parsed: _SheetHTMLParser, iso: str, cname: str, full_fact_count: int) -> list[str]:
    """Short page closing area must sit after the last fact section, before the play card, with exactly one link to ./all/."""
    bad: list[str] = []
    if not parsed.closing_present:
        bad.append(f"{rel}: short page is missing closing area (.a-closing) with link to './all/'")
        return bad
    if not parsed.how_present:
        bad.append(f"{rel}: short page is missing closing .a-how line")
    if parsed.how_links:
        bad.append(f"{rel}: short page closing .a-how line must not contain a link (found {parsed.how_links!r})")
    if (
        parsed.last_fact_section_order is None
        or parsed.closing_order is None
        or parsed.play_card_order is None
        or not (parsed.last_fact_section_order < parsed.closing_order < parsed.play_card_order)
    ):
        bad.append(f"{rel}: short page closing area must appear after the last fact section and before the play card")
    if len(parsed.closing_links) == 0:
        bad.append(f"{rel}: short page closing area is missing link to './all/'")
    elif len(parsed.closing_links) > 1:
        bad.append(
            f"{rel}: short page closing area must contain exactly one link to './all/' "
            f"(found {len(parsed.closing_links)}: {parsed.closing_links!r})"
        )
    else:
        href, text = parsed.closing_links[0]
        if href != "./all/":
            bad.append(f"{rel}: short page closing link href {href!r} must be './all/'")
        want_text = f"See all {full_fact_count} facts about {country_in_prose(iso, cname)}"
        if text != want_text:
            bad.append(f"{rel}: short page closing link text {text!r} != {want_text!r}")
    return bad


def _check_full_back_link(rel: str, parsed: _SheetHTMLParser) -> list[str]:
    """Full page must have a 'Back to the summary' link to '../' at the top under the back-to-game bar."""
    bad: list[str] = []
    if not parsed.subnav_present:
        bad.append(f"{rel}: full page is missing 'Back to the summary' bar (.a-subnav)")
        return bad
    if (
        parsed.fromgame_order is None
        or parsed.subnav_order is None
        or parsed.main_order is None
        or not (parsed.fromgame_order < parsed.subnav_order < parsed.main_order)
    ):
        bad.append(f"{rel}: full page 'Back to the summary' bar must sit under the back-to-game bar before <main>")
    if len(parsed.subnav_links) == 0:
        bad.append(f"{rel}: full page is missing 'Back to the summary' link to '../'")
    elif len(parsed.subnav_links) > 1:
        bad.append(
            f"{rel}: full page subnav must contain exactly one link to '../' "
            f"(found {len(parsed.subnav_links)}: {parsed.subnav_links!r})"
        )
    else:
        href, text = parsed.subnav_links[0]
        if href != "../":
            bad.append(f"{rel}: full page back-to-summary link href {href!r} must be '../'")
        if text != "Back to the summary":
            bad.append(f"{rel}: full page back-to-summary link text {text!r} != 'Back to the summary'")
    if not parsed.how_present:
        bad.append(f"{rel}: full page is missing closing .a-how line")
    if parsed.how_links:
        bad.append(f"{rel}: full page closing .a-how line must not contain a link (found {parsed.how_links!r})")
    return bad


def _check_page_abbreviations(rel: str, parsed: _SheetHTMLParser) -> list[str]:
    """Fail if any known abbreviation appears unexpanded or before its full (short) introduction (Finding 8)."""
    bad: list[str] = []
    text = parsed.main_visible_text
    first_pos: dict[str, int] = {}
    for m in _ABBR_COMBINED_RE.finditer(text):
        short = m.group(0)
        if short not in first_pos:
            first_pos[short] = m.start()
    for short, full, mode in ABBREVIATIONS:
        pos = first_pos.get(short)
        if pos is None:
            continue
        if mode == "always":
            bad.append(f"{rel}: unexpanded abbreviation {short!r} (spell out as {full!r})")
            continue
        m_intro = _ABBR_INTRO_RE[short].search(text)
        if m_intro is None or (m_intro.end() - len(short) - 1) > pos:
            bad.append(
                f"{rel}: abbreviation {short!r} appears before its full form {full!r} (expected '{full} ({short})')"
            )
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


def _check_page_overflow(rel: str, parsed: _SheetHTMLParser) -> list[str]:
    """Static markup checks on a country sheet for sideways-overflow hazards."""
    bad: list[str] = []
    if not parsed.has_viewport:
        bad.append(f"{rel}: missing responsive viewport meta tag")
    for st in parsed.overflow_styles:
        bad.append(f"{rel}: inline style {st!r} exceeds {int(MAX_FIXED_WIDTH_PX)}px")
    for w in parsed.overflow_svgs:
        bad.append(f'{rel}: <svg width="{w}"> exceeds {int(MAX_FIXED_WIDTH_PX)}px (use viewBox + CSS)')
    if any(f["unit_has_nbsp"] for f in parsed.facts):
        bad.append(f"{rel}: fact value uses non-breaking &nbsp; before unit (prevents wrapping on narrow screens)")
    return bad


def _check_boards(
    rel: str,
    got_boards: list[dict],
    want_boards: list[dict] | None,
    label: str,
    card_vals: dict[str, str] | None = None,
) -> list[str]:
    """Verify mini-board distinct-rank values (Finding 2), capped decimals, and exact rows/units/sources (Finding 5)."""
    bad: list[str] = []
    for b in got_boards:
        rows = b["rows"]
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                if rows[i]["rank"] != rows[j]["rank"] and rows[i]["val"] == rows[j]["val"]:
                    bad.append(
                        f"{rel}: mini-board {b['ax']!r} shows identical value {rows[i]['val']!r} "
                        f"for distinct ranks {rows[i]['rank']!r} and {rows[j]['rank']!r}"
                    )
        if card_vals and b["ax"] in card_vals:
            max_dec = _formatted_decimals(card_vals[b["ax"]]) + 2
            for r in rows:
                got_dec = _formatted_decimals(r["val"])
                if got_dec > max_dec:
                    bad.append(
                        f"{rel}: mini-board {b['ax']!r} value {r['val']!r} has {got_dec} decimals "
                        f"(max {max_dec} for card value {card_vals[b['ax']]!r})"
                    )

    if not isinstance(want_boards, list):
        bad.append(f"{rel}: {label} is missing mini-boards ('boards')")
        return bad
    for wb in want_boards:
        if not isinstance(wb, dict) or not all(k in wb for k in ("ax", "unit", "bsrc", "rows")):
            bad.append(f"{rel}: {label} mini-board entry is malformed or missing required fields")
            return bad
    got_axes = [b["ax"] for b in got_boards]
    want_axes = [b["ax"] for b in want_boards]
    if got_axes != want_axes:
        bad.append(f"{rel}: mini-board axes {got_axes} != {label} {want_axes}")
        return bad
    for gb, wb in zip(got_boards, want_boards):
        ax = gb["ax"]
        if gb["unit"] != wb["unit"]:
            bad.append(f"{rel}: mini-board {ax!r} unit {gb['unit']!r} != {label} unit {wb['unit']!r}")
        if gb["bsrc"] != wb["bsrc"]:
            bad.append(f"{rel}: mini-board {ax!r} source {gb['bsrc']!r} != {label} source {wb['bsrc']!r}")
        if len(gb["rows"]) != len(wb["rows"]):
            bad.append(f"{rel}: mini-board {ax!r} has {len(gb['rows'])} rows != {label} {len(wb['rows'])}")
            continue
        for idx, (gr, wr) in enumerate(zip(gb["rows"], wb["rows"])):
            if gr["rank"] != wr["rank"]:
                bad.append(f"{rel}: mini-board {ax!r} row {idx + 1} rank {gr['rank']!r} != {label} rank {wr['rank']!r}")
            if gr["name"] != wr["name"]:
                bad.append(f"{rel}: mini-board {ax!r} row {idx + 1} country {gr['name']!r} != {label} country {wr['name']!r}")
            if gr["val"] != wr["val"]:
                bad.append(f"{rel}: mini-board {ax!r} row {idx + 1} value {gr['val']!r} != {label} value {wr['val']!r}")
    return bad


def _check_card_fields(rel: str, ax: str, got: dict, exp: dict, label: str) -> list[str]:
    bad: list[str] = []
    if not isinstance(exp, dict):
        return [f"{rel}: {ax} {label} entry is missing or invalid"]
    for req_key in ("val", "rank", "unit", "src_text", "url"):
        if req_key not in exp or not isinstance(exp[req_key], str):
            bad.append(f"{rel}: {ax} {label} entry is missing required field {req_key!r}")
    if "val" in exp and isinstance(exp["val"], str) and got["val"] != exp["val"]:
        bad.append(f"{rel}: {ax} value {got['val']!r} != {label} value {exp['val']!r}")
    if "rank" in exp and isinstance(exp["rank"], str) and got["rank"] != exp["rank"]:
        bad.append(f"{rel}: {ax} rank {got['rank']!r} != {label} rank {exp['rank']!r}")
    if exp.get("nodata") and (got["val"] != "No data" or got["rank"] != "Not ranked"):
        bad.append(
            f"{rel}: {ax} has no data and must read 'No data' / 'Not ranked', not {got['val']!r} / {got['rank']!r}"
        )
    if "unit" in exp and isinstance(exp["unit"], str) and got["unit"] != exp["unit"]:
        bad.append(f"{rel}: {ax} unit {got['unit']!r} != {label} unit {exp['unit']!r}")
    if "src_text" in exp and isinstance(exp["src_text"], str) and got["src_text"] != exp["src_text"]:
        bad.append(f"{rel}: {ax} source/year {got['src_text']!r} != {label} {exp['src_text']!r}")
    if not got["src_href"]:
        bad.append(f"{rel}: {ax} source link has empty URL (every fact must link to its source)")
    if "url" in exp and isinstance(exp["url"], str):
        if not exp["url"].strip():
            bad.append(f"{rel}: {ax} {label} entry has empty 'url'")
        elif got["src_href"] != exp["url"]:
            bad.append(f"{rel}: {ax} source URL {got['src_href']!r} != {label} URL {exp['url']!r}")
    return bad


def _check_no_empty_sections_or_bad_literals(rel: str, parsed: _SheetHTMLParser) -> list[str]:
    bad: list[str] = []
    for heading, item_count in parsed.sections_summary:
        if item_count == 0:
            bad.append(f"{rel}: empty section heading {heading!r} (must never render an empty section)")
    m_lit = BAD_LITERAL_RE.search(parsed.all_visible_text)
    if m_lit:
        bad.append(f"{rel}: contains forbidden literal {m_lit.group(0)!r} in visible text")
    m_none = STRAY_NONE_RE.search(parsed.all_visible_text)
    if m_none:
        bad.append(f"{rel}: contains stray 'None' literal in visible text")
    return bad


def _check_map_toggle(rel: str, parsed: _SheetHTMLParser) -> list[str]:
    """Verify the script-free HTML/CSS close-up <-> world map toggle, aria-label, SVGs, and captions."""
    bad: list[str] = []
    if len(parsed.map_toggle_inputs) != 1:
        bad.append(f"{rel}: expected 1 map view toggle checkbox (.map-in), found {len(parsed.map_toggle_inputs)}")
        return bad
    in_id, aria = parsed.map_toggle_inputs[0]
    if not in_id:
        bad.append(f"{rel}: map view toggle checkbox (.map-in) is missing id")
    if not aria:
        bad.append(f"{rel}: map view toggle checkbox (.map-in) is missing aria-label")
    if in_id and in_id not in parsed.map_toggle_labels:
        bad.append(f"{rel}: map view toggle label (.map-btn) missing for={in_id!r}")
    if not parsed.has_map_local_svg:
        bad.append(f"{rel}: map view is missing close-up SVG (.map-local)")
    if not parsed.has_map_world_svg:
        bad.append(f"{rel}: map view is missing world SVG (.map-world)")
    if parsed.map_hint_local_text != MAP_HINT_LOCAL:
        bad.append(f"{rel}: close-up map hint {parsed.map_hint_local_text!r} != {MAP_HINT_LOCAL!r}")
    if parsed.map_hint_world_text != MAP_HINT_WORLD:
        bad.append(f"{rel}: world map hint {parsed.map_hint_world_text!r} != {MAP_HINT_WORLD!r}")
    return bad


def _check_single_page(
    rel: str,
    want_canon: str,
    parsed: _SheetHTMLParser,
    layout: str,
    policy: dict[str, str],
    deny_list: dict[str, str],
    expected_axes: list[str],
    want_entry: dict,
    label: str,
    *,
    iso: str,
    cname: str,
    full_fact_count: int,
    fromgame_href: str,
    ref_note: str = "",
) -> list[str]:
    bad: list[str] = []
    bad += _check_page_security_and_seo(rel, want_canon, parsed)
    bad += _check_page_overflow(rel, parsed)
    bad += _check_page_abbreviations(rel, parsed)
    bad += _check_fromgame_bar(rel, parsed, fromgame_href)
    bad += _check_no_empty_sections_or_bad_literals(rel, parsed)
    bad += _check_map_toggle(rel, parsed)

    # Check every data-axis attribute (both fact rows and standout mini-boards, any quote style)
    for ax in sorted(set(parsed.all_data_axes)):
        if policy.get(ax) != "allowed":
            if ref_note:
                bad.append(f"{rel}: axis {ax!r} is web_republish={policy.get(ax)!r} at {ref_note} (refusing non-allowed axis)")
            else:
                bad.append(f"{rel}: axis {ax!r} has web_republish={policy.get(ax)!r} (only 'allowed' may appear)")
        if ax in deny_list:
            bad.append(f"{rel}: axis {ax!r} is on {DENY_FILE} ({deny_list[ax]})")

    rendered = parsed.facts
    rendered_map = {f["ax"]: f for f in rendered}
    if len(rendered_map) != len(rendered):
        bad.append(f"{rel}: duplicate axis row rendered")

    if not isinstance(want_entry, dict):
        bad.append(f"{rel}: {label} is missing {layout!r} entry")
        return bad

    want_vals = want_entry.get("values")
    if not isinstance(want_vals, dict):
        bad.append(f"{rel}: {label} is missing 'values'")
        want_vals = {}
    want_boards = want_entry.get("boards")

    if layout == "short":
        card_vals = {ax: c["val"] for ax, c in rendered_map.items()}
        bad += _check_boards(rel, parsed.boards, want_boards, label, card_vals=card_vals)
        bad += _check_short_no_nodata(rel, parsed)
        if len(rendered) == 0:
            bad.append(f"{rel}: short page has 0 facts")
        if len(rendered) > SHORT_MAX_FACTS:
            bad.append(f"{rel}: short page has {len(rendered)} facts (max {SHORT_MAX_FACTS})")
        expected_short = want_entry.get("shown_axes")
        if not isinstance(expected_short, list):
            bad.append(f"{rel}: {label} is missing 'shown_axes'")
        else:
            missing_ax = sorted(set(expected_short) - set(rendered_map))
            extra_ax = sorted(set(rendered_map) - set(expected_short))
            if missing_ax:
                bad.append(f"{rel}: missing short-page axis/axes {missing_ax[:5]} ({len(missing_ax)} total)")
            if extra_ax:
                bad.append(f"{rel}: unexpected short-page axis/axes {extra_ax[:5]} ({len(extra_ax)} total)")
        bad += _check_short_closing(rel, parsed, iso, cname, full_fact_count)
        bad += _check_country_wording(
            rel, iso, cname, layout, parsed,
            shown_count=len(expected_short) if isinstance(expected_short, list) else len(rendered),
        )
    else:
        if want_boards:
            bad.append(f"{rel}: {label} full entry must not list mini-boards (got {len(want_boards)})")
        missing_ax = sorted(set(expected_axes) - set(rendered_map))
        extra_ax = sorted(set(rendered_map) - set(expected_axes))
        if missing_ax:
            bad.append(f"{rel}: missing allowed axis/axes {missing_ax[:5]} ({len(missing_ax)} total)")
        if extra_ax:
            bad.append(f"{rel}: unexpected axis/axes {extra_ax[:5]} ({len(extra_ax)} total)")
        bad += _check_full_back_link(rel, parsed)
        bad += _check_country_wording(rel, iso, cname, layout, parsed)

    for ax, got_card in rendered_map.items():
        if ax in SHEET_NAME_OVERRIDES and got_card["name"] != SHEET_NAME_OVERRIDES[ax]:
            bad.append(f"{rel}: {ax} label {got_card['name']!r} != {SHEET_NAME_OVERRIDES[ax]!r}")
        if ax not in want_vals:
            bad.append(f"{rel}: {label} is missing values entry for rendered axis {ax!r}")
            continue
        if layout == "short" and isinstance(want_vals[ax], dict) and want_vals[ax].get("nodata"):
            bad.append(f"{rel}: short page axis {ax!r} has no data in {label}")
        bad += _check_card_fields(rel, ax, got_card, want_vals[ax], label)

    notes = parsed.consistency_notes
    for rule_id in want_entry.get("consistency_rules") or []:
        note_txt = notes.get(rule_id, "")
        if len(note_txt) < 20:
            bad.append(f"{rel}: FR-55 consistency rule {rule_id!r} rendered without its required note")

    return bad


def check(
    root: pathlib.Path = ROOT,
    out_dir: pathlib.Path | None = None,
) -> list[str]:
    """Offline CI check: verifies both short and full sheets for every roster country against manifest, facts.json, deny-list, sitemap, .assetsignore, flags, abbreviations, and overflow rules."""
    bad: list[str] = []
    bad += _check_assetsignore(root)
    bad += _check_sheet_css_overflow(root)
    try:
        deny_list = load_deny_list(root)
    except SheetError as e:
        return [str(e)]

    target_dir = out_dir if out_dir is not None else root
    # Fail closed: when --out is specified, never fall back to src/sheets_manifest.json (Finding 4).
    mp = (out_dir / "sheets_manifest.json") if out_dir is not None else (root / MANIFEST_FILE)
    if not mp.is_file():
        return [f"{mp} is missing; run scripts/build_sheets.py --game <path>"]
    manifest = json.loads(mp.read_text(encoding="utf-8"))

    roster_list, site_list, list_errs = manifest_countries_lists(manifest, label=MANIFEST_FILE)
    bad += list_errs
    expected_countries = sorted(set(roster_list) | set(site_list))
    if not expected_countries:
        return bad

    # Verify website country count matches src/facts.json ("countries": 195) on root checks
    is_custom_out = out_dir is not None and out_dir.resolve() != root.resolve()
    facts_path = root / FACTS_FILE
    if not is_custom_out and facts_path.is_file():
        facts_countries = json.loads(facts_path.read_text(encoding="utf-8")).get("countries")
        if isinstance(facts_countries, int) and len(site_list) != facts_countries:
            bad.append(
                f"{MANIFEST_FILE}: website set has {len(site_list)} countries != {FACTS_FILE} countries ({facts_countries})"
            )

    policy: dict[str, str] = manifest.get("axis_policy") or {}
    m_countries: dict[str, dict] = manifest.get("countries") or {}
    expected_axes = sorted(ax for ax, st in policy.items() if st == "allowed" and ax not in deny_list)

    # Check exact set of short and full pages on disk matches the roster/website country set
    cdir = target_dir / "countries"
    on_disk_short = sorted(
        p.parent.name for p in cdir.glob("*/index.html")
    ) if cdir.is_dir() else []
    missing_short = sorted(set(expected_countries) - set(on_disk_short))
    extra_short = sorted(set(on_disk_short) - set(expected_countries))
    if missing_short:
        bad.append(f"countries/: missing sheet(s) for {missing_short}")
    if extra_short:
        bad.append(f"countries/: unexpected sheet(s) outside roster: {extra_short}")

    on_disk_full = sorted(
        p.parent.parent.name for p in cdir.glob("*/all/index.html")
    ) if cdir.is_dir() else []
    missing_full = sorted(set(expected_countries) - set(on_disk_full))
    extra_full = sorted(set(on_disk_full) - set(expected_countries))
    if missing_full:
        bad.append(f"countries/: missing full sheet(s) (all/) for {missing_full}")
    if extra_full:
        bad.append(f"countries/: unexpected full sheet(s) (all/) outside roster: {extra_full}")

    # Every country in the website set must have its flag SVG on disk
    if is_custom_out:
        try:
            target_dir.resolve().relative_to(root.resolve())
            flags_dir = root / "images" / "flags"
        except ValueError:
            flags_dir = target_dir / "images" / "flags"
    else:
        flags_dir = root / "images" / "flags"
    missing_flags = [iso for iso in expected_countries if not (flags_dir / f"{iso}.svg").is_file()]
    if missing_flags:
        bad.append(f"images/flags/: missing flag SVG(s) for {missing_flags[:10]} ({len(missing_flags)} total)")

    # Country sheets (short or full) must never appear in sitemap.xml
    sm = root / "sitemap.xml"
    if sm.is_file() and "/countries/" in sm.read_text(encoding="utf-8"):
        bad.append("sitemap.xml: lists /countries/ URL(s); country sheets are noindex and must stay out of sitemap.xml")

    short_fromgame_href = _asset_prefix_for(root, out_dir if is_custom_out else None, base_depth=2)
    full_fromgame_href = _asset_prefix_for(root, out_dir if is_custom_out else None, base_depth=3)

    for iso in expected_countries:
        if iso not in m_countries:
            bad.append(f"{MANIFEST_FILE}: missing entry for {iso}")
            continue
        centry = m_countries[iso]
        cname = centry.get("name")
        if not isinstance(cname, str) or not cname:
            bad.append(f"{MANIFEST_FILE}: missing 'name' for {iso}")
            continue
        full_entry = centry.get("full")
        short_entry = centry.get("short")
        full_count = centry.get("full_fact_count")
        if not isinstance(full_count, int) or full_count <= 0:
            bad.append(f"{MANIFEST_FILE}: missing or invalid 'full_fact_count' for {iso}")
            full_count = len(expected_axes)
        elif isinstance(full_entry, dict) and isinstance(full_entry.get("values"), dict):
            want_data_count = sum(
                1 for v in full_entry["values"].values()
                if isinstance(v, dict) and not v.get("nodata")
            )
            if full_count != want_data_count:
                bad.append(
                    f"{MANIFEST_FILE}: {iso} full_fact_count={full_count} != full facts with data ({want_data_count})"
                )

        # Full page first so we can also verify short page's <N> matches actual full page facts with data
        rel_full = f"countries/{iso}/all/index.html"
        p_full = target_dir / rel_full
        actual_full_facts: int | None = None
        if p_full.is_file():
            parsed_full = _parse_sheet_html(p_full.read_text(encoding="utf-8"))
            actual_full_facts = sum(1 for f in parsed_full.facts if not f["is_nodata"])
            if actual_full_facts != full_count:
                bad.append(
                    f"{rel_full}: full page has {actual_full_facts} facts with data != manifest full_fact_count={full_count}"
                )
            bad += _check_single_page(
                rel_full,
                f"{SITE}/countries/{iso}/all/",
                parsed_full,
                "full",
                policy,
                deny_list,
                expected_axes,
                full_entry,
                "dataset",
                iso=iso,
                cname=cname,
                full_fact_count=full_count,
                fromgame_href=full_fromgame_href,
            )

        rel_short = f"countries/{iso}/index.html"
        p_short = target_dir / rel_short
        if p_short.is_file():
            parsed_short = _parse_sheet_html(p_short.read_text(encoding="utf-8"))
            want_n = actual_full_facts if actual_full_facts is not None else full_count
            bad += _check_single_page(
                rel_short,
                f"{SITE}/countries/{iso}/",
                parsed_short,
                "short",
                policy,
                deny_list,
                expected_axes,
                short_entry,
                "dataset",
                iso=iso,
                cname=cname,
                full_fact_count=want_n,
                fromgame_href=short_fromgame_href,
            )

    return bad


def _spec_to_want_entry(spec: dict) -> dict:
    return {
        "shown_axes": spec["shown_axes"],
        "boards": [
            {
                "ax": b["ax"],
                "unit": b["unit"],
                "bsrc": b["bsrc"],
                "rows": [{"rank": r["rank"], "name": r["name"], "val": r["val"]} for r in b["rows"]],
            }
            for b in spec["boards"]
        ],
        "values": spec["cards"],
        "consistency_rules": [r["rule"] for r in spec["rules"]],
    }


def check_game(
    game: pathlib.Path,
    ref: str = "origin/main",
    root: pathlib.Path = ROOT,
    countries_ref: str | None = None,
    out_dir: pathlib.Path | None = None,
) -> list[str]:
    """Live check against the game repo: every roster country (short + full), dataset values, mini-boards, units/sources, web_republish policy, FR-55, links, and kCountrySheetCountries."""
    bad: list[str] = []
    try:
        deny_list = load_deny_list(root)
        bundle = load_game_bundle(game, ref, deny_list)
        roster = roster_countries(bundle)
    except SheetError as e:
        return [str(e)]

    target_dir = out_dir if out_dir is not None else root
    mp = (out_dir / "sheets_manifest.json") if out_dir is not None else (root / MANIFEST_FILE)
    site_countries: list[str] = []
    if mp.is_file():
        manifest = json.loads(mp.read_text(encoding="utf-8"))
        _, site_list, _ = manifest_countries_lists(manifest, label=MANIFEST_FILE)
        site_countries = site_list
        missing_roster = sorted(set(roster) - set(site_countries))
        extra_site = sorted(set(site_countries) - set(roster))
        if missing_roster:
            bad.append(f"{MANIFEST_FILE}: website set is missing roster country/countries from {ref}: {missing_roster}")
        if extra_site:
            bad.append(f"{MANIFEST_FILE}: website set has country/countries not in {ref} roster: {extra_site}")
    else:
        cdir = target_dir / "countries"
        site_countries = sorted(p.parent.name for p in cdir.glob("*/index.html")) if cdir.is_dir() else []

    # Compare the website country set with kCountrySheetCountries on the game repo (fail closed)
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
        compare_site = site_countries if site_countries else list(roster)
        if game_countries is None:
            bad.append(f"{SHEET_URL_DART} at {cref}: malformed or missing kCountrySheetCountries")
        elif sorted(game_countries) != sorted(compare_site):
            only_game = sorted(set(game_countries) - set(compare_site))
            only_site = sorted(set(compare_site) - set(game_countries))
            bad.append(
                f"COUNTRIES differs from {SHEET_URL_DART} kCountrySheetCountries at {cref} "
                f"(only in game: {only_game}, only in site: {only_site})"
            )

    # Check both short and full sheets for every roster country directly against live dataset.json, web_republish and allowlist
    is_custom_out = out_dir is not None and out_dir.resolve() != root.resolve()
    short_fromgame_href = _asset_prefix_for(root, out_dir if is_custom_out else None, base_depth=2)
    full_fromgame_href = _asset_prefix_for(root, out_dir if is_custom_out else None, base_depth=3)
    policy = bundle["policy"]
    expected_axes = bundle["published_axes"]
    for iso in roster:
        full_spec = compute_sheet_expectation(bundle, iso, layout="full")
        short_spec = compute_sheet_expectation(bundle, iso, layout="short")
        cname = full_spec["cname"]
        full_count = sum(1 for card in full_spec["cards"].values() if not card["nodata"])

        rel_full = f"countries/{iso}/all/index.html"
        p_full = target_dir / rel_full
        if not p_full.is_file():
            bad.append(f"{rel_full}: missing")
        else:
            parsed_full = _parse_sheet_html(p_full.read_text(encoding="utf-8"))
            bad += _check_single_page(
                rel_full,
                f"{SITE}/countries/{iso}/all/",
                parsed_full,
                "full",
                policy,
                deny_list,
                expected_axes,
                _spec_to_want_entry(full_spec),
                f"{ref} dataset",
                iso=iso,
                cname=cname,
                full_fact_count=full_count,
                fromgame_href=full_fromgame_href,
                ref_note=ref,
            )

        rel_short = f"countries/{iso}/index.html"
        p_short = target_dir / rel_short
        if not p_short.is_file():
            bad.append(f"{rel_short}: missing")
        else:
            parsed_short = _parse_sheet_html(p_short.read_text(encoding="utf-8"))
            bad += _check_single_page(
                rel_short,
                f"{SITE}/countries/{iso}/",
                parsed_short,
                "short",
                policy,
                deny_list,
                expected_axes,
                _spec_to_want_entry(short_spec),
                f"{ref} dataset",
                iso=iso,
                cname=cname,
                full_fact_count=full_count,
                fromgame_href=short_fromgame_href,
                ref_note=ref,
            )

    # Also verify offline checks (manifest, sitemap, .assetsignore, flags, etc.) stay in sync
    bad += check(root, out_dir=out_dir)
    return bad


def _asset_prefix_for(root: pathlib.Path, out_dir: pathlib.Path | None, base_depth: int = 2) -> str:
    if out_dir is None:
        return "../" * base_depth
    try:
        rel_out = out_dir.resolve().relative_to(root.resolve())
        depth = len(rel_out.parts)
        return "../" * (base_depth + depth)
    except ValueError:
        return "../" * base_depth


def build(
    game: pathlib.Path,
    ref: str = "origin/main",
    root: pathlib.Path = ROOT,
    countries_ref: str | None = None,
    out_dir: pathlib.Path | None = None,
) -> None:
    deny_list = load_deny_list(root)
    bundle = load_game_bundle(game, ref, deny_list)
    countries = roster_countries(bundle)

    # When --countries-ref is explicitly given, enforce exact match with kCountrySheetCountries (fail closed).
    # Otherwise, build all roster countries from --ref and note any difference vs kCountrySheetCountries
    # (`--check --game` always fails closed on any difference).
    if countries_ref is not None:
        require_ref(game, countries_ref)
        dart = game_show(game, countries_ref, SHEET_URL_DART)
        if dart is None:
            raise SheetError(f"{game}: cannot read {SHEET_URL_DART} at {countries_ref}")
        game_countries = parse_game_countries(dart)
        if game_countries is None:
            raise SheetError(f"{SHEET_URL_DART} at {countries_ref}: malformed kCountrySheetCountries")
        if sorted(game_countries) != sorted(countries):
            raise SheetError(
                f"COUNTRIES differs from {SHEET_URL_DART} kCountrySheetCountries at {countries_ref}: "
                f"site={len(countries)} vs game={len(game_countries)}"
            )
    else:
        dart = game_show(game, ref, SHEET_URL_DART)
        if dart is not None:
            game_countries = parse_game_countries(dart)
            if game_countries is not None and sorted(game_countries) != sorted(countries):
                print(
                    f"note {SHEET_URL_DART} kCountrySheetCountries at {ref} has {len(game_countries)} countries "
                    f"vs {len(countries)} in roster; run --check --game once the game branch updates it"
                )

    target_dir = out_dir if out_dir is not None else root
    is_custom_out = out_dir is not None and out_dir.resolve() != root.resolve()
    short_prefix = _asset_prefix_for(root, out_dir if is_custom_out else None, base_depth=2)
    full_prefix = _asset_prefix_for(root, out_dir if is_custom_out else None, base_depth=3)

    manifest_countries: dict[str, dict] = {}
    all_flags: set[str] = set()
    short_pages_out: dict[str, str] = {}
    full_pages_out: dict[str, str] = {}

    for iso in countries:
        full_html, full_entry, full_flags, cname = render_sheet(
            bundle, iso, root, layout="full", asset_prefix=full_prefix,
        )
        full_fact_count = sum(1 for v in full_entry["values"].values() if not v["nodata"])
        short_html, short_entry, short_flags, _ = render_sheet(
            bundle, iso, root, layout="short", asset_prefix=short_prefix, full_fact_count=full_fact_count,
        )
        short_pages_out[iso] = short_html
        full_pages_out[iso] = full_html
        manifest_countries[iso] = {
            "name": cname,
            "full_fact_count": full_fact_count,
            "short": short_entry,
            "full": full_entry,
        }
        all_flags.update(full_flags)
        all_flags.update(short_flags)

    # Validate every generated page (short and full) BEFORE writing anything (fail closed).
    for iso in countries:
        cname = manifest_countries[iso]["name"]
        full_count = manifest_countries[iso]["full_fact_count"]
        short_count = len(manifest_countries[iso]["short"]["shown_axes"])

        rel_short = f"countries/{iso}/index.html"
        parsed_short = _parse_sheet_html(short_pages_out[iso])
        problems = (
            _check_page_security_and_seo(rel_short, f"{SITE}/countries/{iso}/", parsed_short)
            + _check_page_overflow(rel_short, parsed_short)
            + _check_page_abbreviations(rel_short, parsed_short)
            + _check_fromgame_bar(rel_short, parsed_short, short_prefix)
            + _check_no_empty_sections_or_bad_literals(rel_short, parsed_short)
            + _check_map_toggle(rel_short, parsed_short)
            + _check_short_no_nodata(rel_short, parsed_short)
            + _check_short_closing(rel_short, parsed_short, iso, cname, full_count)
            + _check_country_wording(rel_short, iso, cname, "short", parsed_short, shown_count=short_count)
        )
        rel_full = f"countries/{iso}/all/index.html"
        parsed_full = _parse_sheet_html(full_pages_out[iso])
        problems += (
            _check_page_security_and_seo(rel_full, f"{SITE}/countries/{iso}/all/", parsed_full)
            + _check_page_overflow(rel_full, parsed_full)
            + _check_page_abbreviations(rel_full, parsed_full)
            + _check_fromgame_bar(rel_full, parsed_full, full_prefix)
            + _check_no_empty_sections_or_bad_literals(rel_full, parsed_full)
            + _check_map_toggle(rel_full, parsed_full)
            + _check_full_back_link(rel_full, parsed_full)
            + _check_country_wording(rel_full, iso, cname, "full", parsed_full)
        )
        if problems:
            raise SheetError("refusing to write invalid sheet:\n  " + "\n  ".join(problems))

    # Copy referenced flag SVGs from the game repo at ref.
    if is_custom_out:
        try:
            target_dir.resolve().relative_to(root.resolve())
            flags_dir = root / "images" / "flags"
        except ValueError:
            flags_dir = target_dir / "images" / "flags"
    else:
        flags_dir = root / "images" / "flags"
    flags_dir.mkdir(parents=True, exist_ok=True)
    for iso in sorted(all_flags):
        svg_bytes = game_show_bytes(game, ref, f"app/assets/flags/{iso}.svg")
        if svg_bytes is None:
            raise SheetError(f"{game}: missing app/assets/flags/{iso}.svg at {ref}")
        dest = flags_dir / f"{iso}.svg"
        if not dest.exists() or dest.read_bytes() != svg_bytes:
            dest.write_bytes(svg_bytes)

    # Remove any stale flag SVGs only when building into root itself.
    if not is_custom_out:
        for existing in list(flags_dir.glob("*.svg")):
            if existing.stem not in all_flags:
                existing.unlink()

    # Write all short and full HTML sheets (2 per roster country).
    for iso in countries:
        short_dest = target_dir / "countries" / iso / "index.html"
        short_dest.parent.mkdir(parents=True, exist_ok=True)
        short_dest.write_text(short_pages_out[iso], encoding="utf-8")

        full_dest = target_dir / "countries" / iso / "all" / "index.html"
        full_dest.parent.mkdir(parents=True, exist_ok=True)
        full_dest.write_text(full_pages_out[iso], encoding="utf-8")

    # Remove any stray country folders outside the roster.
    cdir = target_dir / "countries"
    countries_set = set(countries)
    if cdir.is_dir():
        for sub in list(cdir.iterdir()):
            if sub.is_dir() and sub.name not in countries_set:
                shutil.rmtree(sub)

    # Write offline verification manifest (in src/ for root builds, or <out>/sheets_manifest.json for --out).
    manifest = {
        "dataset_version": bundle["version"],
        "version_num": bundle["vnum"],
        "version_date": bundle["vdate"],
        "roster_countries": list(countries),
        "countries_list": list(countries),
        "axis_policy": bundle["policy"],
        "denied_axes": sorted(deny_list),
        "published_axes": bundle["published_axes"],
        "countries": manifest_countries,
    }
    manifest_dest = (target_dir / "sheets_manifest.json") if is_custom_out else (root / MANIFEST_FILE)
    manifest_dest.write_text(
        json.dumps(manifest, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Run offline check immediately to guarantee our own output passes.
    problems = check(root, out_dir=(target_dir if is_custom_out else None))
    if problems:
        raise SheetError("generated sheets failed self-check:\n  " + "\n  ".join(problems))

    dest_note = f" -> {target_dir}" if is_custom_out else ""
    print(
        f"ok   built {len(countries)} country sheets x 2 (short + all/{dest_note}, "
        f"{len(bundle['published_axes'])} allowed axes, "
        f"{sum(1 for v in bundle['policy'].values() if v != 'allowed')} not allowed, "
        f"{len(deny_list)} denied, {len(all_flags)} flags, {bundle['version']})"
    )


def _manifest_country_count(root: pathlib.Path, out_dir: pathlib.Path | None) -> int:
    mp = (out_dir / "sheets_manifest.json") if out_dir is not None else (root / MANIFEST_FILE)
    if not mp.is_file():
        return 0
    return len(json.loads(mp.read_text(encoding="utf-8")).get("countries_list") or [])


def main(argv: list[str]) -> int:
    check_mode = "--check" in argv
    game = pathlib.Path(argv[argv.index("--game") + 1]) if "--game" in argv and argv.index("--game") + 1 < len(argv) else None
    ref = argv[argv.index("--ref") + 1] if "--ref" in argv and argv.index("--ref") + 1 < len(argv) else "origin/main"
    cref = (
        argv[argv.index("--countries-ref") + 1]
        if "--countries-ref" in argv and argv.index("--countries-ref") + 1 < len(argv)
        else None
    )
    out_arg = (
        argv[argv.index("--out") + 1]
        if "--out" in argv and argv.index("--out") + 1 < len(argv)
        else None
    )
    out_dir = (ROOT / out_arg) if out_arg is not None else None

    if check_mode and game is not None:
        problems = check_game(game, ref, ROOT, countries_ref=cref, out_dir=out_dir)
        if problems:
            print(f"country sheet check FAILED against {ref}:")
            for b in problems:
                print("  " + b)
            return 1
        n = _manifest_country_count(ROOT, out_dir)
        print(f"ok   country sheets: {n} countries (short + all/, {n * 2} pages) match {ref} and kCountrySheetCountries")
        return 0

    if check_mode:
        problems = check(ROOT, out_dir=out_dir)
        if problems:
            print("country sheet check FAILED (Story 18.6):")
            for b in problems:
                print("  " + b)
            return 1
        n = _manifest_country_count(ROOT, out_dir)
        print(f"ok   country sheets: {n} countries (short + all/, {n * 2} pages) pass all Story 18.6 checks")
        return 0

    if game is None:
        print(
            "usage: build_sheets.py --game PATH [--ref REF] [--countries-ref REF] [--out DIR] "
            "| --check [--game PATH] [--out DIR]",
            file=sys.stderr,
        )
        return 2

    try:
        build(game, ref, ROOT, countries_ref=cref, out_dir=out_dir)
    except SheetError as e:
        print(f"build_sheets FAILED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
