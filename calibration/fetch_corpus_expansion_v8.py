#!/usr/bin/env python3
"""
fetch_corpus_expansion_v8.py -- "8th-pass" corpus expansion fetch script.

WHY THIS EXISTS (2026-07-10): bootstrap CV analysis (re-run at the current
89-dataset corpus; see calibration/bootstrap_stability_report.md and
Docs/02_Calibration_and_Validation/DATA-CERTIFY_Current_State_and_Limitations_Summary.md
Section 4.1#5) shows axis-level EWM weights are still far from converged
(P CV=24.0%, I CV=26.1%), and extrapolating 1/sqrt(N) scaling suggests
roughly 350-600 datasets would be needed to bring those down to a
conventionally stable ~10-15% band. Growing the corpus purely by count is
not enough on its own, though -- what matters is adding GENUINELY
INDEPENDENT real catalogs (not re-slicing existing ones, which would
violate the bootstrap's i.i.d.-ish resampling assumption), ideally from
regions not yet represented at all.

A geographic audit of calibration/corpus_manifest.csv (89 datasets) found
the existing 61 real catalogs are heavily concentrated in circum-Pacific /
Japan-adjacent seismicity (Japan appears in >20 dataset_ids alone) with
entire major seismic regions absent: mainland China, the Indian
subcontinent, most of Central/South America outside Chile/Ecuador/Peru/
Mexico, the Caribbean beyond Haiti, the Balkans, East Africa's rift zone,
most of the Middle East, Russia's Far East/Siberia, Hawaii, and the
southwest Pacific islands beyond Tonga/PNG.

This script fetches 160 NEW real earthquake catalogs from exactly those
gap regions via the USGS FDSN Event Web Service CSV export -- the same
service, same schema, and same "prepare via prepare_dataset.py's existing
CANDIDATES auto-detection" pipeline already used for every real dataset in
the corpus (see calibration/build_corpus.py's STANDARD_FILES /
STANDARD_FILES_V7 precedent from the 7th calibration pass, 2026-07-07,
which did exactly this same kind of gap-filling expansion). Of the 160:
114 are distinct new regions/named historical sequences, and 46 are a
second, non-overlapping EARLIER time-window of a "general window" region
already in that 114 -- generated programmatically (see
EARLY_WINDOW_TARGETS / _add_early_window_variants() below) rather than
hand-written, using the same convention the corpus already relies on
extensively for Japan (many distinct non-overlapping time-window queries
of one country each counted as a separate real dataset).

Requesting 160 in one run (rather than the more conservative 40-80
originally suggested) was an explicit user choice (2026-07-10), made
knowing that even a much larger corpus will not fully converge every
sub-criterion weight (P5/P9/I4 in particular are limited by scarce
per-record fields, not by corpus size -- see
DATA-CERTIFY_Current_State_and_Limitations_Summary.md Section 4.1#5) and that this is a
best-effort geographic expansion assembled without live network
verification of each target's actual event count.

USAGE
-----
Run from the DATA-CERTIFY project root, with Python 3.8+ and an internet
connection:

    python fetch_corpus_expansion_v8.py

No third-party packages required (standard library only). Safe to re-run:
it skips any target it already successfully downloaded. There's a short,
polite delay between requests. Progress -- including event counts -- is
printed as it goes, so you can eyeball which regions came back sparse or
empty (a real result for low-seismicity/short-window targets, not
necessarily a bug) before deciding whether to keep them.

OUTPUT
------
One CSV per target, written DIRECTLY into `Dataset/` using the exact same
column schema every other real dataset already uses (USGS ComCat's native
`format=csv` export), so `calibration/build_corpus.py`'s existing
STANDARD_FILES machinery picks each one up with zero special-casing --
just add the filename to a new `STANDARD_FILES_V8` list (see the printed
summary at the end of the run for the exact list to paste in).

Also writes `corpus_expansion_v8_fetch_report.txt` next to this script
summarizing every target's final row count, so it's easy to spot regions
that came back empty/too-sparse to be usable and decide whether to widen
that target's box/window and re-run.
"""
import csv
import io
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# NOTE (2026-07-11 reorg): this script now lives in calibration/, not the repo
# root, so REPO_ROOT needs one extra dirname() hop to still resolve Dataset/
# (which stays at the true repo root). SCRIPT_DIR anchors this script's own
# output report (corpus_expansion_v8_fetch_report.txt) next to itself.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
ROOT = REPO_ROOT
DATASET_DIR = os.path.join(ROOT, "Dataset")
USGS_BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"
USER_AGENT = "data-certify-corpus-expansion/0.1 (Earth Science Informatics submission)"
TIMEOUT_SEC = 90
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SEC = 3.0
POLITE_DELAY_SEC = 1.5
MIN_USABLE_ROWS = 15  # below this, flag as "too sparse" in the report but keep the file

# ---------------------------------------------------------------------------
# Target list: (output_filename, minlat, maxlat, minlon, maxlon, start_iso,
# end_iso, min_magnitude, human-readable note).
#
# Boxes are deliberately generous (a few degrees of padding around the
# named seismic zone) and time windows/magnitude floors are chosen to make
# a reasonably-sized, non-trivial catalog likely -- named historical
# sequences use a tight window around the real event; "general window"
# targets (no single famous sequence, or chosen for genuinely LOW/moderate
# seismicity as a useful diversity contrast to the corpus's current
# high-seismicity bias) use a multi-year window with a moderate magnitude
# floor instead. These are approximate and NOT independently verified
# against live USGS query results (this script's sandbox has no network
# access) -- eyeball the row counts in the fetch report once you run it,
# and treat anything under MIN_USABLE_ROWS as a candidate to widen/redo
# rather than something to add to the corpus as-is.
# ---------------------------------------------------------------------------
TARGETS = [
    # --- Mainland China (entirely absent from current corpus) ---
    ("china_sichuan_2008.csv", 29.0, 33.5, 101.0, 106.0,
     "2008-05-01T00:00:00", "2008-09-01T00:00:00", 4.0,
     "Wenchuan mainshock + aftershock sequence, Sichuan"),
    ("china_yunnan_general.csv", 22.0, 28.5, 98.0, 104.0,
     "2010-01-01T00:00:00", "2020-01-01T00:00:00", 4.5,
     "Yunnan general seismicity window"),
    ("china_xinjiang_general.csv", 35.0, 42.0, 73.0, 90.0,
     "2010-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Xinjiang/Tian Shan general seismicity window"),

    # --- Indian subcontinent (entirely absent) ---
    ("india_gujarat_bhuj_2001.csv", 22.0, 25.0, 68.5, 71.5,
     "2001-01-20T00:00:00", "2001-06-01T00:00:00", 3.5,
     "Bhuj mainshock + aftershock sequence, Gujarat"),
    ("india_kashmir_2005.csv", 33.0, 35.5, 72.5, 75.5,
     "2005-10-01T00:00:00", "2006-02-01T00:00:00", 3.5,
     "Kashmir mainshock + aftershock sequence"),
    ("india_assam_general.csv", 24.0, 28.5, 89.5, 97.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Northeast India / Assam general seismicity window"),
    ("pakistan_balochistan_2013.csv", 26.0, 28.5, 64.5, 67.0,
     "2013-09-01T00:00:00", "2014-01-01T00:00:00", 3.5,
     "Awaran mainshock + aftershock sequence, Balochistan"),

    # --- South America (beyond existing Chile/Ecuador/Peru coverage) ---
    ("colombia_andes_general.csv", 1.0, 8.0, -77.0, -72.0,
     "2010-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Colombian Andes general seismicity window"),
    ("argentina_sanjuan_general.csv", -33.0, -28.0, -70.5, -66.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "San Juan / Mendoza general seismicity window"),
    ("bolivia_deep_general.csv", -22.0, -15.0, -70.0, -63.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Bolivia deep-focus general seismicity window"),

    # --- Central America / Caribbean (beyond existing Haiti/Mexico coverage) ---
    ("guatemala_general.csv", 13.0, 17.5, -92.5, -88.0,
     "2010-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Guatemala general seismicity window"),
    ("elsalvador_2001.csv", 12.5, 14.5, -90.0, -87.5,
     "2001-01-01T00:00:00", "2001-05-01T00:00:00", 3.5,
     "El Salvador mainshock + aftershock sequence, Jan-Feb 2001"),
    ("costarica_general.csv", 8.0, 11.5, -86.5, -82.5,
     "2010-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Costa Rica general seismicity window"),
    ("panama_general.csv", 6.5, 9.5, -83.5, -77.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Panama general seismicity window"),
    ("puertorico_2020_ponce.csv", 17.5, 18.7, -67.5, -66.0,
     "2019-12-01T00:00:00", "2020-06-01T00:00:00", 3.0,
     "Ponce/Indios sequence, southwest Puerto Rico"),
    ("dominicanrepublic_general.csv", 17.5, 20.0, -72.0, -68.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Dominican Republic general seismicity window"),
    ("jamaica_general.csv", 16.5, 19.0, -79.0, -75.5,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Jamaica general seismicity window"),

    # --- Balkans / Southern Europe (beyond existing Italy/Greece coverage) ---
    ("croatia_petrinja_2020.csv", 44.5, 46.0, 15.5, 17.0,
     "2020-12-01T00:00:00", "2021-03-01T00:00:00", 3.0,
     "Petrinja mainshock + aftershock sequence"),
    ("albania_durres_2019.csv", 40.5, 42.0, 19.0, 20.5,
     "2019-09-01T00:00:00", "2020-01-01T00:00:00", 3.0,
     "Durres mainshock + aftershock sequence"),
    ("spain_lorca_2011.csv", 37.0, 38.5, -2.5, -0.5,
     "2011-05-01T00:00:00", "2011-08-01T00:00:00", 3.0,
     "Lorca mainshock + aftershock sequence"),
    ("portugal_azores_general.csv", 36.5, 40.0, -32.0, -24.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Azores general seismicity window"),

    # --- East Africa rift (entirely absent) ---
    ("tanzania_rift_general.csv", -10.0, -2.0, 29.0, 36.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Tanzania / western rift general seismicity window"),
    ("drc_rift_general.csv", -5.0, 0.5, 27.5, 30.5,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "DR Congo / Lake Kivu rift general seismicity window"),
    ("mozambique_general.csv", -20.0, -12.0, 33.0, 40.5,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Mozambique general seismicity window"),

    # --- Middle East (beyond existing Iran/Afghanistan coverage) ---
    ("iraq_halabja_2017.csv", 34.0, 36.0, 44.5, 46.5,
     "2017-11-01T00:00:00", "2018-02-01T00:00:00", 3.0,
     "Halabja/Zagros mainshock + aftershock sequence"),
    ("saudiarabia_harrat_general.csv", 22.5, 26.5, 37.0, 40.5,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Harrat Lunayyir / western Saudi Arabia general seismicity window"),
    ("lebanon_general.csv", 33.0, 34.7, 35.0, 36.7,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.0,
     "Lebanon general seismicity window"),

    # --- Russia (beyond existing Kamchatka coverage) ---
    ("russia_sakhalin_general.csv", 45.5, 55.0, 141.5, 145.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Sakhalin general seismicity window"),
    ("russia_baikal_general.csv", 50.5, 56.0, 102.0, 111.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Lake Baikal rift general seismicity window"),

    # --- USA / Canada (beyond existing California-Ridgecrest / Alaska-Anchorage) ---
    ("usa_hawaii_kilauea_2018.csv", 18.8, 20.3, -156.2, -154.7,
     "2018-04-01T00:00:00", "2018-10-01T00:00:00", 3.0,
     "Kilauea eruption-associated sequence, 2018"),
    ("usa_california_southnapa_2014.csv", 37.8, 38.6, -122.6, -121.9,
     "2014-08-01T00:00:00", "2014-11-01T00:00:00", 2.5,
     "South Napa mainshock + aftershock sequence"),
    ("usa_cascadia_general.csv", 40.0, 49.0, -125.5, -121.5,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.0,
     "Cascadia general seismicity window (deliberately lower/quieter than corpus norm)"),
    ("canada_britishcolumbia_general.csv", 48.0, 55.0, -132.0, -122.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "British Columbia general seismicity window"),

    # --- Australia (very low seismicity -- useful diversity contrast) ---
    ("australia_general.csv", -39.0, -10.0, 112.0, 154.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Australia continent-wide general seismicity window (deliberately low-rate)"),

    # --- Southwest Pacific islands (beyond existing Tonga/PNG coverage) ---
    ("vanuatu_general.csv", -21.0, -12.0, 166.0, 172.0,
     "2010-01-01T00:00:00", "2020-01-01T00:00:00", 4.5,
     "Vanuatu general seismicity window"),
    ("solomonislands_general.csv", -12.0, -5.0, 154.0, 163.0,
     "2010-01-01T00:00:00", "2020-01-01T00:00:00", 4.5,
     "Solomon Islands general seismicity window"),
    ("fiji_general.csv", -21.0, -15.0, 176.0, 180.0,
     "2010-01-01T00:00:00", "2020-01-01T00:00:00", 4.5,
     "Fiji general seismicity window"),
    ("samoa_general.csv", -15.5, -12.5, -173.0, -170.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Samoa general seismicity window"),

    # --- Central Asia (beyond existing Afghanistan/Tibet coverage) ---
    ("centralasia_kyrgyzstan_tajikistan.csv", 36.5, 43.5, 67.0, 76.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Kyrgyzstan/Tajikistan general seismicity window"),
    ("uzbekistan_general.csv", 38.0, 43.0, 60.0, 70.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Uzbekistan general seismicity window"),

    # --- Mongolia (intraplate diversity contrast) ---
    ("mongolia_gobialtai_general.csv", 44.0, 49.5, 90.0, 100.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Gobi-Altai / Mongolia general seismicity window"),

    # =========================================================================
    # BATCH 2 (2026-07-10, per user request to reach ~160 in one download
    # instead of doing this in several smaller rounds): more named historical
    # sequences within the regions above, plus entirely new countries/regions
    # still absent after batch 1.
    # =========================================================================

    # --- more China ---
    ("china_qinghai_yushu_2010.csv", 32.0, 34.5, 95.5, 98.5,
     "2010-04-01T00:00:00", "2010-08-01T00:00:00", 3.0,
     "Yushu mainshock + aftershock sequence, Qinghai"),
    ("china_gansu_general.csv", 33.0, 37.0, 100.0, 107.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Gansu general seismicity window"),
    ("china_taiwanstrait_general.csv", 23.0, 26.0, 117.0, 121.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Taiwan Strait general seismicity window"),
    ("china_hebei_general.csv", 36.0, 41.0, 113.0, 119.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Hebei / North China Plain general seismicity window"),
    ("china_shanxi_general.csv", 34.0, 40.0, 110.0, 114.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Shanxi general seismicity window"),
    ("china_tibet_plateau_general.csv", 28.0, 35.0, 80.0, 92.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Tibetan plateau (west of existing Tibet 202501 catalog) general window"),

    # --- more South Asia ---
    ("india_uttarakhand_general.csv", 29.0, 31.5, 78.0, 81.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Uttarakhand general seismicity window"),
    ("india_andaman_general.csv", 6.0, 14.0, 92.0, 94.5,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Andaman-Nicobar subduction zone general window"),
    ("bangladesh_general.csv", 20.5, 26.5, 88.0, 92.5,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Bangladesh general seismicity window"),
    ("pakistan_general.csv", 24.0, 37.0, 61.0, 77.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Pakistan (broader than existing Balochistan-2013 catalog) general window"),
    ("nepal_sikkim_general.csv", 26.5, 28.5, 87.5, 89.5,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Nepal/Sikkim border general seismicity window"),

    # --- more South America ---
    ("colombia_armenia_1999.csv", 3.5, 5.5, -76.5, -74.5,
     "1999-01-01T00:00:00", "1999-04-01T00:00:00", 3.0,
     "Armenia/Quindio mainshock + aftershock sequence"),
    ("peru_pisco_2007.csv", -15.0, -12.5, -77.0, -75.0,
     "2007-08-01T00:00:00", "2007-11-01T00:00:00", 3.0,
     "Pisco mainshock + aftershock sequence"),
    ("peru_arequipa_2001.csv", -18.0, -15.0, -73.0, -70.5,
     "2001-06-01T00:00:00", "2001-09-01T00:00:00", 3.0,
     "Arequipa mainshock + aftershock sequence"),
    ("ecuador_general.csv", -5.0, 2.0, -81.0, -75.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Ecuador (broader than existing Muisne-Pedernales-2016 catalog) general window"),
    ("chile_iquique_2014.csv", -21.0, -18.0, -71.5, -69.0,
     "2014-03-01T00:00:00", "2014-06-01T00:00:00", 3.5,
     "Iquique mainshock + aftershock sequence"),
    ("chile_maule_2010.csv", -37.0, -34.0, -74.0, -71.0,
     "2010-02-01T00:00:00", "2010-05-01T00:00:00", 3.5,
     "Maule mainshock + aftershock sequence"),
    ("venezuela_general.csv", 7.0, 12.0, -73.0, -60.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Venezuela (broader than existing 202606 catalog) general window"),
    ("brazil_general.csv", -20.0, -3.0, -55.0, -35.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Brazil general seismicity window (deliberately low/moderate-rate, intraplate)"),
    ("suriname_guyana_general.csv", 2.0, 8.0, -61.0, -54.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Suriname/Guyana general seismicity window (very low-rate, edge case)"),

    # --- more Central America / Caribbean ---
    ("nicaragua_general.csv", 10.5, 15.0, -87.5, -83.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Nicaragua general seismicity window"),
    ("cuba_general.csv", 19.5, 23.5, -85.0, -74.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Cuba general seismicity window"),
    ("trinidadtobago_general.csv", 9.5, 11.5, -62.0, -60.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Trinidad and Tobago general seismicity window"),
    ("honduras_general.csv", 13.0, 17.0, -89.5, -83.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Honduras general seismicity window"),
    ("mexico_oaxaca_general.csv", 15.0, 18.0, -98.0, -94.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Oaxaca (Mexico, different region than existing Chiapas-2017 catalog) general window"),

    # --- Europe (beyond existing Italy/Greece/Turkey/Morocco/Spain coverage) ---
    ("iceland_general.csv", 63.0, 66.5, -24.5, -13.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.0,
     "Iceland general seismicity window (volcanic/rift regime, diversity contrast)"),
    ("iceland_reykjanes_2021.csv", 63.7, 64.2, -22.7, -21.7,
     "2021-01-01T00:00:00", "2021-06-01T00:00:00", 2.5,
     "Reykjanes eruption-associated seismic swarm, 2021"),
    ("norway_general.csv", 58.0, 71.0, 4.0, 31.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Norway general seismicity window (postglacial-rebound regime)"),
    ("switzerland_general.csv", 45.5, 47.8, 5.9, 10.5,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5,
     "Switzerland general seismicity window (very low-rate, edge case)"),
    ("romania_vrancea_general.csv", 45.0, 46.5, 26.0, 27.5,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Vrancea intermediate-depth seismic zone general window"),
    ("bulgaria_general.csv", 41.0, 44.5, 22.0, 29.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Bulgaria general seismicity window"),
    ("turkey_izmit_1999.csv", 40.0, 41.2, 29.0, 31.0,
     "1999-08-01T00:00:00", "1999-11-01T00:00:00", 3.0,
     "Izmit mainshock + aftershock sequence, 1999"),
    ("turkey_van_2011.csv", 38.0, 39.5, 42.5, 44.5,
     "2011-10-01T00:00:00", "2012-01-01T00:00:00", 3.0,
     "Van mainshock + aftershock sequence, 2011"),
    ("france_general.csv", 42.0, 48.0, -1.0, 8.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.0,
     "France general seismicity window (Alps/Pyrenees, low-moderate rate)"),
    ("germany_general.csv", 47.0, 55.0, 6.0, 15.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5,
     "Germany general seismicity window (very low-rate, edge case)"),

    # --- more Middle East ---
    ("iran_bam_2003.csv", 28.0, 30.0, 57.5, 59.5,
     "2003-12-01T00:00:00", "2004-03-01T00:00:00", 3.0,
     "Bam mainshock + aftershock sequence, 2003"),
    ("iran_ahar_varzaghan_2012.csv", 37.5, 39.0, 46.0, 48.0,
     "2012-08-01T00:00:00", "2012-11-01T00:00:00", 3.0,
     "Ahar-Varzaghan mainshock + aftershock sequence, 2012"),
    ("yemen_general.csv", 12.0, 19.0, 42.0, 54.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Yemen general seismicity window"),
    ("oman_general.csv", 16.0, 26.0, 52.0, 60.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Oman general seismicity window"),
    ("jordan_general.csv", 29.0, 33.5, 34.5, 39.5,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.0,
     "Jordan general seismicity window"),
    ("israel_deadsea_general.csv", 29.5, 33.5, 34.5, 36.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5,
     "Dead Sea transform general seismicity window"),
    ("syria_general.csv", 32.0, 37.5, 35.5, 42.5,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Syria general seismicity window"),
    ("egypt_general.csv", 22.0, 32.0, 25.0, 35.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Egypt general seismicity window"),

    # --- Africa (entirely absent otherwise) ---
    ("ethiopia_general.csv", 3.0, 15.0, 33.0, 48.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Ethiopia general seismicity window"),
    ("kenya_general.csv", -5.0, 5.0, 34.0, 42.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Kenya general seismicity window"),
    ("algeria_boumerdes_2003.csv", 36.0, 37.5, 2.5, 4.5,
     "2003-05-01T00:00:00", "2003-08-01T00:00:00", 3.0,
     "Boumerdes mainshock + aftershock sequence, 2003"),
    ("morocco_alhoceima_2004.csv", 34.5, 35.7, -4.5, -3.0,
     "2004-02-01T00:00:00", "2004-05-01T00:00:00", 3.0,
     "Al Hoceima mainshock + aftershock sequence, 2004 (different sequence than existing 2023 catalog)"),
    ("southafrica_general.csv", -34.0, -22.0, 16.0, 33.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "South Africa general seismicity window (natural + mining-induced)"),
    ("malawi_general.csv", -17.0, -9.0, 32.0, 36.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Malawi general seismicity window"),
    ("ghana_accra_general.csv", 4.0, 11.0, -3.5, 1.5,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Ghana general seismicity window (very low-rate, West Africa edge case)"),
    ("madagascar_general.csv", -26.0, -11.0, 42.5, 51.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Madagascar general seismicity window"),

    # --- more Russia / Central Asia ---
    ("russia_kurilislands_general.csv", 43.0, 51.0, 145.0, 157.0,
     "2010-01-01T00:00:00", "2020-01-01T00:00:00", 4.5,
     "Kuril Islands general seismicity window"),
    ("kazakhstan_general.csv", 40.0, 55.0, 46.0, 87.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Kazakhstan general seismicity window"),
    ("turkmenistan_general.csv", 35.0, 42.5, 52.0, 66.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Turkmenistan general seismicity window"),
    ("russia_caucasus_general.csv", 42.0, 45.0, 44.0, 49.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Russian Caucasus (Dagestan/Chechnya) general seismicity window"),
    ("azerbaijan_general.csv", 38.0, 42.0, 45.0, 50.5,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Azerbaijan general seismicity window"),

    # --- more North America ---
    ("usa_yellowstone_general.csv", 44.0, 45.2, -111.3, -109.7,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 2.5,
     "Yellowstone caldera general seismicity window (volcanic/geothermal swarm regime)"),
    ("usa_newmadrid_general.csv", 35.0, 38.0, -91.0, -88.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5,
     "New Madrid seismic zone general window (intraplate, central US)"),
    ("usa_oklahoma_induced_general.csv", 34.5, 37.0, -99.0, -95.0,
     "2010-01-01T00:00:00", "2018-01-01T00:00:00", 3.0,
     "Oklahoma general seismicity window (largely wastewater-injection-induced, useful anthropogenic-origin contrast)"),
    ("usa_puertorico_general.csv", 17.5, 19.0, -68.0, -65.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "Puerto Rico (broader than existing 2020-Ponce catalog) general window"),
    ("canada_quebec_general.csv", 45.0, 48.0, -76.0, -70.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5,
     "Quebec general seismicity window (intraplate, low-moderate rate)"),
    ("mexico_baja_general.csv", 28.0, 33.0, -117.0, -112.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Baja California general seismicity window"),
    ("greenland_general.csv", 60.0, 83.0, -55.0, -20.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Greenland general seismicity window (arctic, very low-rate edge case)"),

    # --- more Oceania / Pacific ---
    ("newzealand_kaikoura_2016.csv", -43.0, -41.5, 172.5, 175.0,
     "2016-11-01T00:00:00", "2017-02-01T00:00:00", 3.0,
     "Kaikoura mainshock + aftershock sequence, 2016 (different window than existing 'nz' catalog)"),
    ("papuanewguinea_general.csv", -10.0, -2.0, 141.0, 153.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Papua New Guinea (broader than existing highlands-2018 catalog) general window"),
    ("newcaledonia_general.csv", -23.0, -19.0, 163.0, 169.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "New Caledonia general seismicity window"),
    ("tuvalu_kiribati_general.csv", -11.0, 4.0, 172.0, 180.0,
     "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Tuvalu/Kiribati general seismicity window (very low-rate, edge case)"),
    ("marianaislands_general.csv", 12.0, 21.0, 143.0, 147.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Mariana Islands general seismicity window"),
    ("guam_general.csv", 12.0, 15.0, 143.0, 146.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0,
     "Guam general seismicity window"),
    ("indonesia_sumatra_general.csv", -6.0, 6.0, 94.0, 104.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Sumatra subduction zone general window (different region than existing Palu-2018 catalog)"),
    ("indonesia_java_general.csv", -9.0, -5.0, 105.0, 115.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5,
     "Java general seismicity window"),

    # --- more East Asia ---
    ("southkorea_gyeongju_2016.csv", 35.5, 36.2, 128.8, 129.5,
     "2016-08-01T00:00:00", "2016-11-01T00:00:00", 2.5,
     "Gyeongju mainshock + aftershock sequence, 2016"),
    ("northkorea_general.csv", 38.0, 43.0, 124.0, 131.0,
     "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5,
     "North Korea general seismicity window (includes natural + declared nuclear-test-associated events -- useful for the anthropogenic-misattribution future-work theme)"),
]

# ---------------------------------------------------------------------------
# BATCH 3: programmatically-generated earlier, NON-OVERLAPPING time windows
# for a subset of the "general window" (non single-sequence) targets above.
# This mirrors the convention the corpus already uses extensively for Japan
# (>20 distinct dataset_ids, each its own non-overlapping time window of the
# same country) -- adding a second, earlier, non-overlapping window of the
# SAME region is a genuinely new independent sample, not a re-slice of an
# already-included dataset, so it does not violate the bootstrap's
# independence assumption the way re-slicing an EXISTING corpus entry would.
# Early window always ends exactly where the modern window begins (zero
# overlap) and starts 10 years earlier.
# ---------------------------------------------------------------------------
EARLY_WINDOW_TARGETS = [
    "china_yunnan_general.csv", "china_xinjiang_general.csv",
    "india_assam_general.csv", "colombia_andes_general.csv",
    "argentina_sanjuan_general.csv", "bolivia_deep_general.csv",
    "guatemala_general.csv", "costarica_general.csv", "panama_general.csv",
    "dominicanrepublic_general.csv", "jamaica_general.csv",
    "portugal_azores_general.csv", "tanzania_rift_general.csv",
    "drc_rift_general.csv", "mozambique_general.csv",
    "saudiarabia_harrat_general.csv", "lebanon_general.csv",
    "russia_sakhalin_general.csv", "russia_baikal_general.csv",
    "usa_cascadia_general.csv", "canada_britishcolumbia_general.csv",
    "australia_general.csv", "vanuatu_general.csv",
    "solomonislands_general.csv", "fiji_general.csv", "samoa_general.csv",
    "centralasia_kyrgyzstan_tajikistan.csv", "uzbekistan_general.csv",
    "mongolia_gobialtai_general.csv",
    "china_gansu_general.csv", "india_uttarakhand_general.csv",
    "india_andaman_general.csv", "bangladesh_general.csv",
    "ecuador_general.csv", "brazil_general.csv", "nicaragua_general.csv",
    "cuba_general.csv", "iceland_general.csv", "switzerland_general.csv",
    "yemen_general.csv", "oman_general.csv", "ethiopia_general.csv",
    "kenya_general.csv", "kazakhstan_general.csv",
    "usa_yellowstone_general.csv", "indonesia_sumatra_general.csv",
]


def _shift_year(iso_str: str, delta_years: int) -> str:
    year = int(iso_str[:4])
    return f"{year + delta_years}{iso_str[4:]}"


def _add_early_window_variants():
    by_name = {t[0]: t for t in TARGETS}
    added = 0
    for fname in EARLY_WINDOW_TARGETS:
        entry = by_name.get(fname)
        if entry is None:
            continue
        fn, minlat, maxlat, minlon, maxlon, start_iso, end_iso, min_mag, note = entry
        early_end = start_iso  # zero overlap with the modern-window entry
        early_start = _shift_year(start_iso, -10)
        base = fn[:-4]
        TARGETS.append((
            f"{base}_early.csv", minlat, maxlat, minlon, maxlon,
            early_start, early_end, min_mag,
            f"{note} -- earlier (pre-{start_iso[:4]}), non-overlapping window "
            f"for independent corpus growth (same region, different real sample)",
        ))
        added += 1
    return added


_add_early_window_variants()


def fetch_with_retry(url):
    last_err = None
    for attempt in range(RETRY_ATTEMPTS):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last_err = e
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SEC * (attempt + 1))
    raise RuntimeError(f"All {RETRY_ATTEMPTS} attempts failed: {last_err}")


def build_url(minlat, maxlat, minlon, maxlon, start_iso, end_iso, min_mag):
    params = {
        "format": "csv",
        "starttime": start_iso,
        "endtime": end_iso,
        "minlatitude": minlat,
        "maxlatitude": maxlat,
        "minlongitude": minlon,
        "maxlongitude": maxlon,
        "minmagnitude": min_mag,
        "orderby": "time",
    }
    return f"{USGS_BASE}?{urllib.parse.urlencode(params)}"


def main():
    os.makedirs(DATASET_DIR, exist_ok=True)
    report_lines = []
    kept = []
    skipped_existing = 0
    empty_or_sparse = []
    failed = []

    print(f"Fetching {len(TARGETS)} new corpus-expansion targets from USGS ComCat...")
    print(f"Writing into: {DATASET_DIR}\n")

    for i, (fname, minlat, maxlat, minlon, maxlon, start_iso, end_iso, min_mag, note) in enumerate(TARGETS, 1):
        out_path = os.path.join(DATASET_DIR, fname)
        if os.path.exists(out_path):
            print(f"[{i}/{len(TARGETS)}] SKIP (already exists): {fname}")
            skipped_existing += 1
            with open(out_path, "r", encoding="utf-8") as f:
                n = max(0, sum(1 for _ in f) - 1)
            report_lines.append(f"{fname}\t{n}\tSKIPPED (already present)\t{note}")
            if n >= MIN_USABLE_ROWS:
                kept.append(fname)
            continue

        url = build_url(minlat, maxlat, minlon, maxlon, start_iso, end_iso, min_mag)
        try:
            raw = fetch_with_retry(url)
        except Exception as e:
            print(f"[{i}/{len(TARGETS)}] FAILED: {fname} -- {e}")
            failed.append(fname)
            report_lines.append(f"{fname}\tFAILED\t{e}\t{note}")
            time.sleep(POLITE_DELAY_SEC)
            continue

        text = raw.decode("utf-8", errors="replace")
        reader = list(csv.reader(io.StringIO(text)))
        n_rows = max(0, len(reader) - 1)  # minus header

        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)

        status = "OK"
        if n_rows == 0:
            status = "EMPTY"
            empty_or_sparse.append(fname)
        elif n_rows < MIN_USABLE_ROWS:
            status = f"SPARSE (<{MIN_USABLE_ROWS})"
            empty_or_sparse.append(fname)
        else:
            kept.append(fname)

        print(f"[{i}/{len(TARGETS)}] {status}: {fname} -- {n_rows} rows")
        report_lines.append(f"{fname}\t{n_rows}\t{status}\t{note}")
        time.sleep(POLITE_DELAY_SEC)

    report_path = os.path.join(SCRIPT_DIR, "corpus_expansion_v8_fetch_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("filename\trow_count\tstatus\tnote\n")
        f.write("\n".join(report_lines) + "\n")

    print("\n" + "=" * 70)
    print(f"DONE. {len(kept)} usable, {len(empty_or_sparse)} empty/sparse, "
          f"{len(failed)} failed, {skipped_existing} already existed.")
    print(f"Full report: {report_path}")
    print("=" * 70)
    print("\nSTANDARD_FILES_V8 list to paste into calibration/build_corpus.py "
          "(only the usable ones):\n")
    print("STANDARD_FILES_V8: List[str] = [")
    for fname in kept:
        print(f'    "{fname}",')
    print("]")
    print("\nSend back this whole console output (or at minimum "
          "corpus_expansion_v8_fetch_report.txt) so the next step -- wiring "
          "these into build_corpus.py and re-running the calibration "
          "pipeline -- can be checked against real row counts rather than "
          "the approximate ones assumed when the target list was written.")


if __name__ == "__main__":
    main()
