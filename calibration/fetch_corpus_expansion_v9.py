#!/usr/bin/env python3
"""
fetch_corpus_expansion_v9.py -- "9th-pass" corpus expansion fetch script.

WHY THIS EXISTS (2026-07-10): the user is adding a 10-level graduated
fabrication realism ladder (calibration/corrupt.py's fabricate_level1..
fabricate_level10_adversarial, 9 levels x 30 datasets = 270 new
"known_bad" fabricated datasets going into the calibration corpus, plus a
held-out level-10 adversarial set of 30 more that is NOT part of
calibration -- see calibration/build_adversarial_corpus.py). Added alone,
that would flip the corpus from known_good-majority (69.5% at the
8th-pass, 295-dataset scale) to known_bad-majority (~63.5%), which the
user explicitly rejected in favor of also growing the REAL side of the
corpus to preserve a known_good majority.

This script targets ~300 NET NEW real earthquake catalogs (over-fetching
to ~349 candidates to absorb the usual EMPTY/SPARSE yield loss -- the
8th pass fetched 160 candidates for 144 usable, a ~90% yield; some of
this pass's candidates are deliberately higher-risk pre-1990s time
windows, so a somewhat lower yield is expected and disclosed rather than
assumed away).

APPROACH -- three independent, all NON-OVERLAPPING-BY-CONSTRUCTION ways
of adding real data, none of which re-slice a window that is already
part of the corpus (re-slicing an existing window would create records
that are a SUBSET of an already-included dataset, violating the
bootstrap's i.i.d.-ish resampling assumption -- this was deliberately
avoided, not overlooked):

  1. "_recent" variant: every 8th-pass base target (114 filenames, both
     "general window" and "named historical sequence" ones) gets a NEW,
     later, non-overlapping window running from its ORIGINAL end date to
     just short of today (2026-07-08) -- genuinely new real seismicity
     that did not exist yet when the 8th pass's windows were chosen.
     (114 candidates)

  2. "_early" variant for the 41 "general window" 8th-pass targets that
     did NOT already get one in the 8th pass (the 8th pass gave 46 of
     the 87 general-window targets an _early variant; this pass covers
     the remaining 41), using the same convention: 10 years immediately
     before the original window's start, zero overlap.
     (41 candidates)

  3. "_early2" / "_early3" variants for ALL 87 general-window 8th-pass
     targets (regardless of whether they already have an _early from the
     8th pass or a new one from this pass) -- two further, consecutive,
     non-overlapping 15-year steps further back in time
     (start-25y..start-10y, then start-45y..start-25y). These are
     higher-risk: many regional/moderate-magnitude catalogs have thin or
     unreliable USGS ComCat coverage before ~1970-1980, so a higher
     EMPTY/SPARSE rate is expected here specifically -- this is disclosed
     up front, not discovered as a surprise after the run.
     (87 + 87 = 174 candidates)

  4. A curated list of ~20 brand-new regions/named sequences not present
     anywhere in the corpus through the 8th pass (see NEW_REGIONS below),
     for genuine geographic diversity rather than only re-partitioning
     time within already-covered regions.
     (20 candidates)

Total candidates: 114 + 41 + 174 + 20 = 349.

Same USGS FDSN Event Web Service CSV export, same schema, same
zero-special-casing STANDARD_FILES pickup convention as every prior pass.

USAGE
-----
    python fetch_corpus_expansion_v9.py

No third-party packages required. Safe to re-run (skips already-downloaded
files). Writes corpus_expansion_v9_fetch_report.txt and prints a ready-to-
paste STANDARD_FILES_V9 list at the end (usable entries only).
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
# output report (corpus_expansion_v9_fetch_report.txt) next to itself.
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
MIN_USABLE_ROWS = 15
TODAY_ISO = "2026-07-08T00:00:00"  # a few days before the actual current date, safely in the past

# ---------------------------------------------------------------------------
# The 8th pass's base 114 targets, reproduced verbatim here (same filename,
# box, and window) so this script can derive non-overlapping _recent /
# _early / _early2 / _early3 variants from them without needing to import
# fetch_corpus_expansion_v8.py (which is a standalone, already-run script).
# Format: (output_filename, minlat, maxlat, minlon, maxlon, start_iso,
# end_iso, min_magnitude, human-readable note).
# ---------------------------------------------------------------------------
BASE_TARGETS = [
    ("china_sichuan_2008.csv", 29.0, 33.5, 101.0, 106.0, "2008-05-01T00:00:00", "2008-09-01T00:00:00", 4.0, "Wenchuan sequence"),
    ("china_yunnan_general.csv", 22.0, 28.5, 98.0, 104.0, "2010-01-01T00:00:00", "2020-01-01T00:00:00", 4.5, "Yunnan general"),
    ("china_xinjiang_general.csv", 35.0, 42.0, 73.0, 90.0, "2010-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Xinjiang/Tian Shan general"),
    ("india_gujarat_bhuj_2001.csv", 22.0, 25.0, 68.5, 71.5, "2001-01-20T00:00:00", "2001-06-01T00:00:00", 3.5, "Bhuj sequence"),
    ("india_kashmir_2005.csv", 33.0, 35.5, 72.5, 75.5, "2005-10-01T00:00:00", "2006-02-01T00:00:00", 3.5, "Kashmir sequence"),
    ("india_assam_general.csv", 24.0, 28.5, 89.5, 97.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "NE India/Assam general"),
    ("pakistan_balochistan_2013.csv", 26.0, 28.5, 64.5, 67.0, "2013-09-01T00:00:00", "2014-01-01T00:00:00", 3.5, "Awaran sequence"),
    ("colombia_andes_general.csv", 1.0, 8.0, -77.0, -72.0, "2010-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Colombian Andes general"),
    ("argentina_sanjuan_general.csv", -33.0, -28.0, -70.5, -66.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "San Juan/Mendoza general"),
    ("bolivia_deep_general.csv", -22.0, -15.0, -70.0, -63.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Bolivia deep-focus general"),
    ("guatemala_general.csv", 13.0, 17.5, -92.5, -88.0, "2010-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Guatemala general"),
    ("elsalvador_2001.csv", 12.5, 14.5, -90.0, -87.5, "2001-01-01T00:00:00", "2001-05-01T00:00:00", 3.5, "El Salvador sequence"),
    ("costarica_general.csv", 8.0, 11.5, -86.5, -82.5, "2010-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Costa Rica general"),
    ("panama_general.csv", 6.5, 9.5, -83.5, -77.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Panama general"),
    ("puertorico_2020_ponce.csv", 17.5, 18.7, -67.5, -66.0, "2019-12-01T00:00:00", "2020-06-01T00:00:00", 3.0, "Ponce/Indios sequence"),
    ("dominicanrepublic_general.csv", 17.5, 20.0, -72.0, -68.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Dominican Republic general"),
    ("jamaica_general.csv", 16.5, 19.0, -79.0, -75.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Jamaica general"),
    ("croatia_petrinja_2020.csv", 44.5, 46.0, 15.5, 17.0, "2020-12-01T00:00:00", "2021-03-01T00:00:00", 3.0, "Petrinja sequence"),
    ("albania_durres_2019.csv", 40.5, 42.0, 19.0, 20.5, "2019-09-01T00:00:00", "2020-01-01T00:00:00", 3.0, "Durres sequence"),
    ("spain_lorca_2011.csv", 37.0, 38.5, -2.5, -0.5, "2011-05-01T00:00:00", "2011-08-01T00:00:00", 3.0, "Lorca sequence"),
    ("portugal_azores_general.csv", 36.5, 40.0, -32.0, -24.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Azores general"),
    ("tanzania_rift_general.csv", -10.0, -2.0, 29.0, 36.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Tanzania/western rift general"),
    ("drc_rift_general.csv", -5.0, 0.5, 27.5, 30.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "DRC/Lake Kivu rift general"),
    ("mozambique_general.csv", -20.0, -12.0, 33.0, 40.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Mozambique general"),
    ("iraq_halabja_2017.csv", 34.0, 36.0, 44.5, 46.5, "2017-11-01T00:00:00", "2018-02-01T00:00:00", 3.0, "Halabja sequence"),
    ("saudiarabia_harrat_general.csv", 22.5, 26.5, 37.0, 40.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Harrat Lunayyir general"),
    ("lebanon_general.csv", 33.0, 34.7, 35.0, 36.7, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.0, "Lebanon general"),
    ("russia_sakhalin_general.csv", 45.5, 55.0, 141.5, 145.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Sakhalin general"),
    ("russia_baikal_general.csv", 50.5, 56.0, 102.0, 111.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Lake Baikal rift general"),
    ("usa_hawaii_kilauea_2018.csv", 18.8, 20.3, -156.2, -154.7, "2018-04-01T00:00:00", "2018-10-01T00:00:00", 3.0, "Kilauea 2018 sequence"),
    ("usa_california_southnapa_2014.csv", 37.8, 38.6, -122.6, -121.9, "2014-08-01T00:00:00", "2014-11-01T00:00:00", 2.5, "South Napa sequence"),
    ("usa_cascadia_general.csv", 40.0, 49.0, -125.5, -121.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.0, "Cascadia general"),
    ("canada_britishcolumbia_general.csv", 48.0, 55.0, -132.0, -122.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "British Columbia general"),
    ("australia_general.csv", -39.0, -10.0, 112.0, 154.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Australia general"),
    ("vanuatu_general.csv", -21.0, -12.0, 166.0, 172.0, "2010-01-01T00:00:00", "2020-01-01T00:00:00", 4.5, "Vanuatu general"),
    ("solomonislands_general.csv", -12.0, -5.0, 154.0, 163.0, "2010-01-01T00:00:00", "2020-01-01T00:00:00", 4.5, "Solomon Islands general"),
    ("fiji_general.csv", -21.0, -15.0, 176.0, 180.0, "2010-01-01T00:00:00", "2020-01-01T00:00:00", 4.5, "Fiji general"),
    ("samoa_general.csv", -15.5, -12.5, -173.0, -170.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Samoa general"),
    ("centralasia_kyrgyzstan_tajikistan.csv", 36.5, 43.5, 67.0, 76.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Kyrgyzstan/Tajikistan general"),
    ("uzbekistan_general.csv", 38.0, 43.0, 60.0, 70.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Uzbekistan general"),
    ("mongolia_gobialtai_general.csv", 44.0, 49.5, 90.0, 100.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Gobi-Altai/Mongolia general"),
    ("china_qinghai_yushu_2010.csv", 32.0, 34.5, 95.5, 98.5, "2010-04-01T00:00:00", "2010-08-01T00:00:00", 3.0, "Yushu sequence"),
    ("china_gansu_general.csv", 33.0, 37.0, 100.0, 107.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Gansu general"),
    ("china_taiwanstrait_general.csv", 23.0, 26.0, 117.0, 121.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Taiwan Strait general"),
    ("china_hebei_general.csv", 36.0, 41.0, 113.0, 119.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Hebei/North China Plain general"),
    ("china_shanxi_general.csv", 34.0, 40.0, 110.0, 114.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Shanxi general"),
    ("china_tibet_plateau_general.csv", 28.0, 35.0, 80.0, 92.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Tibetan plateau general"),
    ("india_uttarakhand_general.csv", 29.0, 31.5, 78.0, 81.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Uttarakhand general"),
    ("india_andaman_general.csv", 6.0, 14.0, 92.0, 94.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Andaman-Nicobar general"),
    ("bangladesh_general.csv", 20.5, 26.5, 88.0, 92.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Bangladesh general"),
    ("pakistan_general.csv", 24.0, 37.0, 61.0, 77.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Pakistan general"),
    ("nepal_sikkim_general.csv", 26.5, 28.5, 87.5, 89.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Nepal/Sikkim border general"),
    ("colombia_armenia_1999.csv", 3.5, 5.5, -76.5, -74.5, "1999-01-01T00:00:00", "1999-04-01T00:00:00", 3.0, "Armenia/Quindio sequence"),
    ("peru_pisco_2007.csv", -15.0, -12.5, -77.0, -75.0, "2007-08-01T00:00:00", "2007-11-01T00:00:00", 3.0, "Pisco sequence"),
    ("peru_arequipa_2001.csv", -18.0, -15.0, -73.0, -70.5, "2001-06-01T00:00:00", "2001-09-01T00:00:00", 3.0, "Arequipa sequence"),
    ("ecuador_general.csv", -5.0, 2.0, -81.0, -75.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Ecuador general"),
    ("chile_iquique_2014.csv", -21.0, -18.0, -71.5, -69.0, "2014-03-01T00:00:00", "2014-06-01T00:00:00", 3.5, "Iquique sequence"),
    ("chile_maule_2010.csv", -37.0, -34.0, -74.0, -71.0, "2010-02-01T00:00:00", "2010-05-01T00:00:00", 3.5, "Maule sequence"),
    ("venezuela_general.csv", 7.0, 12.0, -73.0, -60.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Venezuela general"),
    ("brazil_general.csv", -20.0, -3.0, -55.0, -35.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Brazil general"),
    ("suriname_guyana_general.csv", 2.0, 8.0, -61.0, -54.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Suriname/Guyana general"),
    ("nicaragua_general.csv", 10.5, 15.0, -87.5, -83.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Nicaragua general"),
    ("cuba_general.csv", 19.5, 23.5, -85.0, -74.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Cuba general"),
    ("trinidadtobago_general.csv", 9.5, 11.5, -62.0, -60.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Trinidad and Tobago general"),
    ("honduras_general.csv", 13.0, 17.0, -89.5, -83.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Honduras general"),
    ("mexico_oaxaca_general.csv", 15.0, 18.0, -98.0, -94.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Oaxaca general"),
    ("iceland_general.csv", 63.0, 66.5, -24.5, -13.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.0, "Iceland general"),
    ("iceland_reykjanes_2021.csv", 63.7, 64.2, -22.7, -21.7, "2021-01-01T00:00:00", "2021-06-01T00:00:00", 2.5, "Reykjanes 2021 sequence"),
    ("norway_general.csv", 58.0, 71.0, 4.0, 31.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Norway general"),
    ("switzerland_general.csv", 45.5, 47.8, 5.9, 10.5, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "Switzerland general"),
    ("romania_vrancea_general.csv", 45.0, 46.5, 26.0, 27.5, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Vrancea general"),
    ("bulgaria_general.csv", 41.0, 44.5, 22.0, 29.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Bulgaria general"),
    ("turkey_izmit_1999.csv", 40.0, 41.2, 29.0, 31.0, "1999-08-01T00:00:00", "1999-11-01T00:00:00", 3.0, "Izmit sequence"),
    ("turkey_van_2011.csv", 38.0, 39.5, 42.5, 44.5, "2011-10-01T00:00:00", "2012-01-01T00:00:00", 3.0, "Van sequence"),
    ("france_general.csv", 42.0, 48.0, -1.0, 8.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.0, "France general"),
    ("germany_general.csv", 47.0, 55.0, 6.0, 15.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "Germany general"),
    ("iran_bam_2003.csv", 28.0, 30.0, 57.5, 59.5, "2003-12-01T00:00:00", "2004-03-01T00:00:00", 3.0, "Bam sequence"),
    ("iran_ahar_varzaghan_2012.csv", 37.5, 39.0, 46.0, 48.0, "2012-08-01T00:00:00", "2012-11-01T00:00:00", 3.0, "Ahar-Varzaghan sequence"),
    ("yemen_general.csv", 12.0, 19.0, 42.0, 54.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Yemen general"),
    ("oman_general.csv", 16.0, 26.0, 52.0, 60.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Oman general"),
    ("jordan_general.csv", 29.0, 33.5, 34.5, 39.5, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.0, "Jordan general"),
    ("israel_deadsea_general.csv", 29.5, 33.5, 34.5, 36.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "Dead Sea transform general"),
    ("syria_general.csv", 32.0, 37.5, 35.5, 42.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Syria general"),
    ("egypt_general.csv", 22.0, 32.0, 25.0, 35.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Egypt general"),
    ("ethiopia_general.csv", 3.0, 15.0, 33.0, 48.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Ethiopia general"),
    ("kenya_general.csv", -5.0, 5.0, 34.0, 42.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Kenya general"),
    ("algeria_boumerdes_2003.csv", 36.0, 37.5, 2.5, 4.5, "2003-05-01T00:00:00", "2003-08-01T00:00:00", 3.0, "Boumerdes sequence"),
    ("morocco_alhoceima_2004.csv", 34.5, 35.7, -4.5, -3.0, "2004-02-01T00:00:00", "2004-05-01T00:00:00", 3.0, "Al Hoceima 2004 sequence"),
    ("southafrica_general.csv", -34.0, -22.0, 16.0, 33.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "South Africa general"),
    ("malawi_general.csv", -17.0, -9.0, 32.0, 36.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Malawi general"),
    ("ghana_accra_general.csv", 4.0, 11.0, -3.5, 1.5, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Ghana general"),
    ("madagascar_general.csv", -26.0, -11.0, 42.5, 51.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Madagascar general"),
    ("russia_kurilislands_general.csv", 43.0, 51.0, 145.0, 157.0, "2010-01-01T00:00:00", "2020-01-01T00:00:00", 4.5, "Kuril Islands general"),
    ("kazakhstan_general.csv", 40.0, 55.0, 46.0, 87.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Kazakhstan general"),
    ("turkmenistan_general.csv", 35.0, 42.5, 52.0, 66.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Turkmenistan general"),
    ("russia_caucasus_general.csv", 42.0, 45.0, 44.0, 49.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Russian Caucasus general"),
    ("azerbaijan_general.csv", 38.0, 42.0, 45.0, 50.5, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Azerbaijan general"),
    ("usa_yellowstone_general.csv", 44.0, 45.2, -111.3, -109.7, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "Yellowstone general"),
    ("usa_newmadrid_general.csv", 35.0, 38.0, -91.0, -88.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "New Madrid general"),
    ("usa_oklahoma_induced_general.csv", 34.5, 37.0, -99.0, -95.0, "2010-01-01T00:00:00", "2018-01-01T00:00:00", 3.0, "Oklahoma induced general"),
    ("usa_puertorico_general.csv", 17.5, 19.0, -68.0, -65.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Puerto Rico general"),
    ("canada_quebec_general.csv", 45.0, 48.0, -76.0, -70.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "Quebec general"),
    ("mexico_baja_general.csv", 28.0, 33.0, -117.0, -112.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Baja California general"),
    ("greenland_general.csv", 60.0, 83.0, -55.0, -20.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Greenland general"),
    ("newzealand_kaikoura_2016.csv", -43.0, -41.5, 172.5, 175.0, "2016-11-01T00:00:00", "2017-02-01T00:00:00", 3.0, "Kaikoura sequence"),
    ("papuanewguinea_general.csv", -10.0, -2.0, 141.0, 153.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Papua New Guinea general"),
    ("newcaledonia_general.csv", -23.0, -19.0, 163.0, 169.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "New Caledonia general"),
    ("tuvalu_kiribati_general.csv", -11.0, 4.0, 172.0, 180.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Tuvalu/Kiribati general"),
    ("marianaislands_general.csv", 12.0, 21.0, 143.0, 147.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Mariana Islands general"),
    ("guam_general.csv", 12.0, 15.0, 143.0, 146.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Guam general"),
    ("indonesia_sumatra_general.csv", -6.0, 6.0, 94.0, 104.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Sumatra general"),
    ("indonesia_java_general.csv", -9.0, -5.0, 105.0, 115.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.5, "Java general"),
    ("southkorea_gyeongju_2016.csv", 35.5, 36.2, 128.8, 129.5, "2016-08-01T00:00:00", "2016-11-01T00:00:00", 2.5, "Gyeongju sequence"),
    ("northkorea_general.csv", 38.0, 43.0, 124.0, 131.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "North Korea general"),
]

# Filenames that are tight, named historical-sequence windows (a few months
# around one mainshock) rather than multi-year "general seismicity" windows
# -- these get a "_recent" background-seismicity variant only, never
# _early/_early2/_early3 (an "earlier version of a 3-month sequence window"
# is not a meaningful construct the way an earlier general-seismicity window
# is).
NAMED_SEQUENCE_FILES = {
    "china_sichuan_2008.csv", "india_gujarat_bhuj_2001.csv", "india_kashmir_2005.csv",
    "pakistan_balochistan_2013.csv", "elsalvador_2001.csv", "croatia_petrinja_2020.csv",
    "albania_durres_2019.csv", "spain_lorca_2011.csv", "china_qinghai_yushu_2010.csv",
    "colombia_armenia_1999.csv", "peru_pisco_2007.csv", "peru_arequipa_2001.csv",
    "chile_iquique_2014.csv", "chile_maule_2010.csv", "iran_bam_2003.csv",
    "iran_ahar_varzaghan_2012.csv", "algeria_boumerdes_2003.csv", "morocco_alhoceima_2004.csv",
    "turkey_izmit_1999.csv", "turkey_van_2011.csv", "usa_hawaii_kilauea_2018.csv",
    "usa_california_southnapa_2014.csv", "newzealand_kaikoura_2016.csv",
    "southkorea_gyeongju_2016.csv", "iraq_halabja_2017.csv", "puertorico_2020_ponce.csv",
    "iceland_reykjanes_2021.csv",
}

# Brand-new regions/sequences absent from the corpus through the 8th pass --
# genuine geographic diversity, not a re-partition of an existing window.
NEW_REGIONS = [
    ("cyprus_general.csv", 33.5, 36.0, 32.0, 35.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.0, "Cyprus general"),
    ("slovenia_general.csv", 45.4, 46.9, 13.3, 16.6, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "Slovenia general"),
    ("austria_general.csv", 46.4, 49.0, 9.5, 17.2, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "Austria general"),
    ("poland_general.csv", 49.0, 54.8, 14.0, 24.2, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "Poland general (incl. mining-induced)"),
    ("srilanka_general.csv", 5.9, 9.9, 79.6, 82.0, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.0, "Sri Lanka general (very low-rate)"),
    ("myanmar_sagaing_general.csv", 18.0, 26.0, 94.0, 97.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Sagaing fault, Myanmar general"),
    ("laos_general.csv", 14.0, 22.5, 100.0, 107.7, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Laos general"),
    ("thailand_general.csv", 5.5, 20.5, 97.3, 105.6, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Thailand general"),
    ("vietnam_general.csv", 8.5, 23.4, 102.1, 109.5, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Vietnam general"),
    ("philippines_luzon_general.csv", 13.0, 19.0, 119.5, 122.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Luzon, Philippines general"),
    ("philippines_mindanao_general.csv", 5.0, 10.0, 122.0, 127.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Mindanao, Philippines general"),
    ("bhutan_general.csv", 26.7, 28.3, 88.7, 92.1, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Bhutan general"),
    ("italy_sicily_etna_general.csv", 37.4, 38.1, 14.7, 15.4, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "Mt. Etna, Sicily general (volcanic swarm regime)"),
    ("usa_virginia_2011.csv", 37.5, 38.2, -78.2, -77.3, "2011-08-01T00:00:00", "2011-11-01T00:00:00", 2.0, "Mineral, Virginia mainshock sequence"),
    ("usa_nevada_basinrange_general.csv", 37.0, 42.0, -119.5, -114.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.0, "Nevada Basin and Range general"),
    ("usa_utah_wasatch_general.csv", 39.0, 42.0, -112.5, -111.0, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 2.5, "Utah Wasatch Front general"),
    ("haiti_2010.csv", 17.9, 19.2, -73.5, -71.6, "2010-01-01T00:00:00", "2010-06-01T00:00:00", 3.0, "Haiti 2010 mainshock sequence"),
    ("guadeloupe_martinique_general.csv", 14.0, 17.0, -63.0, -60.5, "2005-01-01T00:00:00", "2022-01-01T00:00:00", 3.5, "Guadeloupe/Martinique general"),
    ("sudan_general.csv", 8.0, 22.0, 21.8, 38.6, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Sudan general"),
    ("botswana_general.csv", -26.9, -17.8, 19.9, 29.4, "2000-01-01T00:00:00", "2022-01-01T00:00:00", 4.0, "Botswana general"),
]
NEW_REGIONS_GENERAL = [t for t in NEW_REGIONS if "sequence" not in t[8] and "mainshock" not in t[8]]


def _shift_year(iso_str: str, delta_years: int) -> str:
    year = int(iso_str[:4])
    return f"{year + delta_years}{iso_str[4:]}"


def _build_variants():
    targets = []

    # 1. _recent: every base target + every new-region target gets a later,
    # non-overlapping window from its original end to just before today.
    for fn, minlat, maxlat, minlon, maxlon, start_iso, end_iso, min_mag, note in BASE_TARGETS + NEW_REGIONS:
        base = fn[:-4]
        targets.append((
            f"{base}_recent.csv", minlat, maxlat, minlon, maxlon, end_iso, TODAY_ISO, min_mag,
            f"{note} -- later, non-overlapping window ({end_iso[:4]}-2026) capturing seismicity "
            f"that postdates the 8th/9th-pass original window",
        ))

    general_pool = [t for t in BASE_TARGETS if t[0] not in NAMED_SEQUENCE_FILES] + NEW_REGIONS_GENERAL

    for fn, minlat, maxlat, minlon, maxlon, start_iso, end_iso, min_mag, note in general_pool:
        base = fn[:-4]
        # 2. _early (only meaningful/new for targets not already given one in
        # the 8th pass -- but re-adding it here is harmless/idempotent since
        # this script also SKIPS files that already exist on disk).
        early_end = start_iso
        early_start = _shift_year(start_iso, -10)
        targets.append((
            f"{base}_early.csv", minlat, maxlat, minlon, maxlon, early_start, early_end, min_mag,
            f"{note} -- earlier (pre-{start_iso[:4]}), non-overlapping window",
        ))
        # 3. _early2: immediately before _early, zero overlap with it.
        early2_end = early_start
        early2_start = _shift_year(start_iso, -25)
        targets.append((
            f"{base}_early2.csv", minlat, maxlat, minlon, maxlon, early2_start, early2_end, min_mag,
            f"{note} -- further-earlier window, immediately preceding the _early window (zero overlap)",
        ))
        # 4. _early3: immediately before _early2. Higher EMPTY/SPARSE risk by
        # design (pre-1970s/80s USGS ComCat coverage is thin for many
        # regions) -- disclosed, not hidden.
        early3_end = early2_start
        early3_start = _shift_year(start_iso, -45)
        targets.append((
            f"{base}_early3.csv", minlat, maxlat, minlon, maxlon, early3_start, early3_end, min_mag,
            f"{note} -- second further-earlier window, immediately preceding _early2 (zero overlap); "
            f"higher risk of thin/no USGS ComCat coverage this far back, by design",
        ))

    return targets


TARGETS = _build_variants()


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
        "format": "csv", "starttime": start_iso, "endtime": end_iso,
        "minlatitude": minlat, "maxlatitude": maxlat,
        "minlongitude": minlon, "maxlongitude": maxlon,
        "minmagnitude": min_mag, "orderby": "time",
    }
    return f"{USGS_BASE}?{urllib.parse.urlencode(params)}"


def main():
    os.makedirs(DATASET_DIR, exist_ok=True)
    report_lines = []
    kept = []
    skipped_existing = 0
    empty_or_sparse = []
    failed = []

    print(f"Fetching {len(TARGETS)} new corpus-expansion (9th-pass) targets from USGS ComCat...")
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
        n_rows = max(0, len(reader) - 1)

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

    report_path = os.path.join(SCRIPT_DIR, "corpus_expansion_v9_fetch_report.txt")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("filename\trow_count\tstatus\tnote\n")
        f.write("\n".join(report_lines) + "\n")

    print("\n" + "=" * 70)
    print(f"DONE. {len(kept)} usable, {len(empty_or_sparse)} empty/sparse, "
          f"{len(failed)} failed, {skipped_existing} already existed.")
    print(f"Full report: {report_path}")
    print("=" * 70)
    print("\nSTANDARD_FILES_V9 list to paste into calibration/build_corpus.py "
          "(only the usable ones):\n")
    print("STANDARD_FILES_V9 = [")
    for fname in kept:
        print(f'    "{fname}",')
    print("]")
    print(f"\n(Target was ~300 net new; got {len(kept)}. If well short of 300, "
          "the _early3 tier is the expected source of most losses -- widen "
          "MIN_USABLE_ROWS-failing boxes/windows or accept the smaller total, "
          "your call.)")
    print("\nSend back this whole console output (or at minimum "
          "corpus_expansion_v9_fetch_report.txt) so the next step can be "
          "checked against real row counts.")


if __name__ == "__main__":
    main()
