# -*- coding: utf-8 -*-
"""
calibration/build_corpus.py -- Assemble the labeled >=50-dataset
calibration corpus (Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md
Sections 4-5): every "real" file inventoried from Dataset/ that carries a
genuine, usable earthquake-catalog schema, normalised into the canonical
DATA-CERTIFY CSV format via prepare_dataset.py (standard files) or
calibration/parsers.py (the 3 non-standard-schema files), PLUS a curated
set of deliberately-degraded synthetic "known-bad" variants built from
calibration/corrupt.py, so the corpus spans both known-trustworthy and
known-problematic examples as the theory docs require.

Labeling policy (approved by the user before this module was written,
per the standing "don't act on ambiguous methodology without asking"
instruction): every REAL file here is a genuine catalog sourced from an
authoritative seismological agency (USGS ComCat, ISC-GEM, GeoNet NZ, CSN
Chile, or a published ground-motion research compilation) -- there is no
independent way for this project to verify that one authentic agency
export is somehow "more fabricated" than another, so fabricating a
known_bad label for any of them would be dishonest. All real files are
therefore labeled known_good; the known_bad side of the corpus comes
entirely from the DISCLOSED, deliberately-injected corruptions in
calibration/corrupt.py and the two synthetic total-fabrication
generators -- exactly the "mix real + generate corrupted variants"
corpus design the user selected when asked.

Usage:
    python3 calibration/build_corpus.py
Writes canonical datasets under datasets/<name>/records.csv (same
convention prepare_dataset.py already uses) and a manifest at
calibration/corpus_manifest.csv.

DISCLOSED CORRECTION (2026-07-05, found during an independent
re-verification pass on the finished calibration work): the original
version of this script's inventory (STANDARD_FILES + special +
EXCLUDED_NON_CATALOG_FILES) accounted for 56 of the 58 files in the
user's original file list -- 2 real USGS ComCat GeoJSON exports,
`ishikawa_202401.json` and `japan_2023-.json`, had been silently missed:
neither processed into the corpus nor recorded as an intentional
exclusion. A systematic set-difference check against the user's original
list caught this gap. Both files were inspected and confirmed to be
genuine, distinct real earthquake catalogs (different date ranges,
magnitude filters, and row counts from every already-included export --
not duplicates of the CSV-format ComCat exports already in
STANDARD_FILES, e.g. `ishikawa_202401_query.csv` is a different export
than `ishikawa_202401.json`). They are GeoJSON FeatureCollections, not
the flat-CSV ComCat schema `prepare_dataset.py`'s CANDIDATES mapping
expects, so they needed their own parser -- see `GEOJSON_FILES` below and
`calibration/parsers.py::prepare_usgs_geojson`. Fixing this grew the
corpus from 71 to 73 datasets (50 real known_good, up from 48) and
required re-running the EWM/threshold calibration; see
`calibration/ewm_report.md` and `calibration/threshold_report.md` for the
updated numbers. This fix is recorded here (not just applied ad hoc) so a
future from-scratch rebuild of the corpus reproduces the corrected
73-dataset state rather than silently regressing to the original,
incomplete 71-dataset one.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import prepare_dataset as _pd_mod
from calibration import parsers, corrupt
from data_certify.schema import load_dataset_csv, save_dataset_csv

DATASET_DIR = ROOT / "Dataset"
DATASETS_OUT = ROOT / "datasets"
MANIFEST_PATH = Path(__file__).resolve().parent / "corpus_manifest.csv"

# Standard USGS-ComCat-schema real files -- auto-detected fully by
# prepare_dataset.py's existing CANDIDATES mapping, no overrides needed.
# (Confirmed via `head -1` against every Dataset/*.csv file during task
# #43's inspection -- these 42 all share the exact ComCat header.)
STANDARD_FILES: List[str] = [
    "202505_tokyo.csv", "202506_turkey.csv", "202507_Kamchatka.csv",
    "202509_Kamchatka.csv", "202510_philippines.csv", "2025_03_myanmar.csv",
    "202604_tohoku_japan.csv", "202606_philippines.csv",
    "afghanistan_20231008_query.csv", "afghanistan_20231015_query.csv",
    "afghanistan_2025_09_01.csv", "all_month.csv", "greece_2024_2025.csv",
    "haiti_20210814_query.csv", "ishikawa_202401_query.csv",
    "ishikawa_202411_query.csv", "ishikawa_2024_query.csv",
    "japan-20190101_20211203_query.csv", "japan_2000_2023_query.csv",
    "japan_20190101-20211009_query.csv", "japan_20220317_query.csv",
    "japan_20220319_query.csv", "japan_saitama_202407_202501.csv",
    "miyazaki_2024-2025.csv", "morocco_20230908_query.csv",
    "peru_20250616.csv", "potvilla_2024012.csv", "taiwan_20240403_query.csv",
    "taiwan_20240423_query.csv", "taiwan_2024_query.csv", "taiwan_202501.csv",
    "tibet_202501.csv", "tohoku_2005_2011.csv", "tohoku_202511.csv",
    "tohoku_202512.csv", "tohoku_202606.csv", "tokara_202506.csv",
    "tonga_20210101_20220117_query.csv", "turkey_202504.csv",
    "usgs_current.csv", "usgs_main.csv", "venezuela_202606.csv",
    "yamanashi_202606.csv",
]

# 7th-pass corpus expansion (2026-07-07): 11 additional real USGS ComCat
# catalogs covering major historical earthquake sequences from regions
# previously underrepresented in the corpus (Central America/Caribbean,
# South Asia, sub-Saharan/East Africa rift analogues via PNG, Southeast
# Asia, Middle East, South America Andes, Mediterranean Europe). Sourced
# via USGS FDSN Event Web Service CSV export (same schema/pipeline as
# STANDARD_FILES above -- confirmed via `head -1` to share the identical
# ComCat header before being added here). Added per the paper-readiness
# discussion of 2026-07-07: expanding the calibration corpus so the
# bootstrap-quantified weight uncertainty (see bootstrap_stability_report.md)
# can be re-measured on a larger, more geographically diverse sample.
STANDARD_FILES_V7: List[str] = [
    "indonesia_palu_2018.csv", "ridgecrest_california_2019.csv",
    "amatrice_norcia_italy_2016.csv", "anchorage_alaska_2018.csv",
    "chiapas_mexico_2017.csv", "gorkha_nepal_2015.csv", "haiti_2010.csv",
    "kahramanmaras_turkey_2023.csv", "kermanshah_iran_2017.csv",
    "muisne_pedernales_ecuador_2016.csv", "png_highlands_2018.csv",
]
STANDARD_FILES = STANDARD_FILES + STANDARD_FILES_V7

# 8th-pass corpus expansion (2026-07-10): 144 additional real USGS ComCat
# catalogs, fetched via calibration/fetch_corpus_expansion_v8.py (see that
# script's docstring for the full rationale) to fill major geographic gaps
# left after the 7th pass -- mainland China, the Indian subcontinent, most
# of Central/South America beyond Chile/Ecuador/Peru/Mexico, the Caribbean
# beyond Haiti, the Balkans, East Africa's rift, most of the Middle East,
# Russia's Far East/Siberia/Caucasus, Central Asia, Hawaii, several
# low-seismicity edge cases (Switzerland, Germany, Greenland, Australia),
# and induced/volcanic-regime contrasts (Oklahoma wastewater injection,
# Yellowstone, Iceland). Of these 144, 105 are distinct new regions/named
# historical sequences and 39 are a second, EARLIER, non-overlapping
# time-window of a region already covered by one of those 105 or by an
# original (7th-pass-or-earlier) STANDARD_FILES entry -- generated
# programmatically by fetch_corpus_expansion_v8.py's
# _add_early_window_variants(), same convention already used extensively
# for Japan in the pre-existing corpus. 16 originally-planned targets came
# back empty/too-sparse (<15 rows: Jamaica, Spain-Lorca, Saudi Arabia,
# Brazil, Suriname/Guyana, Oman, Ghana, Tuvalu/Kiribati, South Korea, plus
# 7 of their "_early" variants) and were excluded -- see
# corpus_expansion_v8_fetch_report.txt for every target's actual row count.
# Grew the corpus from 89 to 233 datasets (61->205 real known_good); see
# Docs/02_Calibration_and_Validation/DATA-CERTIFY_Current_State_and_Limitations_Summary.md
# Section 4.1#5 for the bootstrap-CV motivation and
# calibration/bootstrap_stability_report.md for the re-measured numbers
# after this expansion.
STANDARD_FILES_V8: List[str] = [
    "china_sichuan_2008.csv", "china_yunnan_general.csv",
    "china_xinjiang_general.csv", "india_gujarat_bhuj_2001.csv",
    "india_kashmir_2005.csv", "india_assam_general.csv",
    "pakistan_balochistan_2013.csv", "colombia_andes_general.csv",
    "argentina_sanjuan_general.csv", "bolivia_deep_general.csv",
    "guatemala_general.csv", "elsalvador_2001.csv", "costarica_general.csv",
    "panama_general.csv", "puertorico_2020_ponce.csv",
    "dominicanrepublic_general.csv", "croatia_petrinja_2020.csv",
    "albania_durres_2019.csv", "portugal_azores_general.csv",
    "tanzania_rift_general.csv", "drc_rift_general.csv",
    "mozambique_general.csv", "iraq_halabja_2017.csv", "lebanon_general.csv",
    "russia_sakhalin_general.csv", "russia_baikal_general.csv",
    "usa_hawaii_kilauea_2018.csv", "usa_california_southnapa_2014.csv",
    "usa_cascadia_general.csv", "canada_britishcolumbia_general.csv",
    "australia_general.csv", "vanuatu_general.csv",
    "solomonislands_general.csv", "fiji_general.csv", "samoa_general.csv",
    "centralasia_kyrgyzstan_tajikistan.csv", "uzbekistan_general.csv",
    "mongolia_gobialtai_general.csv", "china_qinghai_yushu_2010.csv",
    "china_gansu_general.csv", "china_taiwanstrait_general.csv",
    "china_hebei_general.csv", "china_shanxi_general.csv",
    "china_tibet_plateau_general.csv", "india_uttarakhand_general.csv",
    "india_andaman_general.csv", "bangladesh_general.csv",
    "pakistan_general.csv", "nepal_sikkim_general.csv",
    "colombia_armenia_1999.csv", "peru_pisco_2007.csv",
    "peru_arequipa_2001.csv", "ecuador_general.csv",
    "chile_iquique_2014.csv", "chile_maule_2010.csv",
    "venezuela_general.csv", "nicaragua_general.csv", "cuba_general.csv",
    "trinidadtobago_general.csv", "honduras_general.csv",
    "mexico_oaxaca_general.csv", "iceland_general.csv",
    "iceland_reykjanes_2021.csv", "norway_general.csv",
    "switzerland_general.csv", "romania_vrancea_general.csv",
    "bulgaria_general.csv", "turkey_izmit_1999.csv", "turkey_van_2011.csv",
    "france_general.csv", "germany_general.csv", "iran_bam_2003.csv",
    "iran_ahar_varzaghan_2012.csv", "yemen_general.csv",
    "jordan_general.csv", "israel_deadsea_general.csv", "syria_general.csv",
    "egypt_general.csv", "ethiopia_general.csv", "kenya_general.csv",
    "algeria_boumerdes_2003.csv", "morocco_alhoceima_2004.csv",
    "southafrica_general.csv", "malawi_general.csv", "madagascar_general.csv",
    "russia_kurilislands_general.csv", "kazakhstan_general.csv",
    "turkmenistan_general.csv", "russia_caucasus_general.csv",
    "azerbaijan_general.csv", "usa_yellowstone_general.csv",
    "usa_newmadrid_general.csv", "usa_oklahoma_induced_general.csv",
    "usa_puertorico_general.csv", "canada_quebec_general.csv",
    "mexico_baja_general.csv", "greenland_general.csv",
    "newzealand_kaikoura_2016.csv", "papuanewguinea_general.csv",
    "newcaledonia_general.csv", "marianaislands_general.csv",
    "guam_general.csv", "indonesia_sumatra_general.csv",
    "indonesia_java_general.csv", "northkorea_general.csv",
    "china_yunnan_general_early.csv", "china_xinjiang_general_early.csv",
    "india_assam_general_early.csv", "colombia_andes_general_early.csv",
    "argentina_sanjuan_general_early.csv", "bolivia_deep_general_early.csv",
    "guatemala_general_early.csv", "costarica_general_early.csv",
    "panama_general_early.csv", "dominicanrepublic_general_early.csv",
    "portugal_azores_general_early.csv", "tanzania_rift_general_early.csv",
    "drc_rift_general_early.csv", "russia_sakhalin_general_early.csv",
    "russia_baikal_general_early.csv", "usa_cascadia_general_early.csv",
    "canada_britishcolumbia_general_early.csv", "australia_general_early.csv",
    "vanuatu_general_early.csv", "solomonislands_general_early.csv",
    "fiji_general_early.csv", "samoa_general_early.csv",
    "centralasia_kyrgyzstan_tajikistan_early.csv",
    "uzbekistan_general_early.csv", "mongolia_gobialtai_general_early.csv",
    "china_gansu_general_early.csv", "india_uttarakhand_general_early.csv",
    "india_andaman_general_early.csv", "bangladesh_general_early.csv",
    "ecuador_general_early.csv", "nicaragua_general_early.csv",
    "cuba_general_early.csv", "iceland_general_early.csv",
    "switzerland_general_early.csv", "yemen_general_early.csv",
    "ethiopia_general_early.csv", "kazakhstan_general_early.csv",
    "usa_yellowstone_general_early.csv", "indonesia_sumatra_general_early.csv",
]
STANDARD_FILES = STANDARD_FILES + STANDARD_FILES_V8

# 9th-pass corpus expansion (2026-07-10/11): PLACEHOLDER pending
# fetch_corpus_expansion_v9.py's actual run. That script targets ~300 net
# new real catalogs (349 candidates, over-fetched to absorb the usual
# EMPTY/SPARSE yield loss) via three non-overlapping-by-construction
# mechanisms: "_recent" windows (later than every 8th-pass window),
# "_early"/"_early2"/"_early3" windows (progressively earlier, zero
# overlap with each other or the modern window), and ~20 brand-new
# regions. Run that script, then paste ONLY the printed
# "usable" filenames below (do not guess -- the whole point of running it
# is that live USGS row counts, not assumed ones, decide what's usable).
# This expansion exists specifically so the 10-level graduated fabrication
# ladder (calibration/corrupt.py's fabricate_level1..9, 270 new datasets
# added to build_fabricated_datasets() below) does not flip the corpus
# from known_good-majority to known_bad-majority -- see this project's
# own conversation record (2026-07-10) for the explicit user decision to
# grow real alongside fabricated/corrupted rather than accept that flip.
# Populated 2026-07-11 from the actual fetch_corpus_expansion_v9.py run's
# corpus_expansion_v9_fetch_report.txt: 303 net new real catalogs (of the
# 349 candidates). Deliberately EXCLUDES every filename the report marked
# "SKIPPED (already present)" -- those are files fetch_corpus_expansion_v8.py
# already wrote and that are already counted in STANDARD_FILES_V8; including
# them again here would double-count the same real events under a second
# STANDARD_FILES entry pointing at the identical file. Real: 205 -> 508.
STANDARD_FILES_V9: List[str] = [
    "china_sichuan_2008_recent.csv", "china_yunnan_general_recent.csv",
    "china_xinjiang_general_recent.csv", "india_gujarat_bhuj_2001_recent.csv",
    "india_kashmir_2005_recent.csv", "india_assam_general_recent.csv",
    "pakistan_balochistan_2013_recent.csv", "colombia_andes_general_recent.csv",
    "argentina_sanjuan_general_recent.csv", "bolivia_deep_general_recent.csv",
    "guatemala_general_recent.csv", "elsalvador_2001_recent.csv",
    "costarica_general_recent.csv", "panama_general_recent.csv",
    "puertorico_2020_ponce_recent.csv", "dominicanrepublic_general_recent.csv",
    "albania_durres_2019_recent.csv", "portugal_azores_general_recent.csv",
    "tanzania_rift_general_recent.csv", "drc_rift_general_recent.csv",
    "iraq_halabja_2017_recent.csv", "russia_sakhalin_general_recent.csv",
    "russia_baikal_general_recent.csv", "usa_hawaii_kilauea_2018_recent.csv",
    "usa_california_southnapa_2014_recent.csv", "usa_cascadia_general_recent.csv",
    "canada_britishcolumbia_general_recent.csv", "australia_general_recent.csv",
    "vanuatu_general_recent.csv", "solomonislands_general_recent.csv",
    "fiji_general_recent.csv", "samoa_general_recent.csv",
    "centralasia_kyrgyzstan_tajikistan_recent.csv", "uzbekistan_general_recent.csv",
    "china_qinghai_yushu_2010_recent.csv", "china_gansu_general_recent.csv",
    "china_taiwanstrait_general_recent.csv", "china_tibet_plateau_general_recent.csv",
    "india_uttarakhand_general_recent.csv", "india_andaman_general_recent.csv",
    "bangladesh_general_recent.csv", "pakistan_general_recent.csv",
    "nepal_sikkim_general_recent.csv", "colombia_armenia_1999_recent.csv",
    "peru_pisco_2007_recent.csv", "peru_arequipa_2001_recent.csv",
    "ecuador_general_recent.csv", "chile_iquique_2014_recent.csv",
    "chile_maule_2010_recent.csv", "venezuela_general_recent.csv",
    "nicaragua_general_recent.csv", "cuba_general_recent.csv",
    "honduras_general_recent.csv", "mexico_oaxaca_general_recent.csv",
    "iceland_general_recent.csv", "iceland_reykjanes_2021_recent.csv",
    "romania_vrancea_general_recent.csv", "turkey_izmit_1999_recent.csv",
    "turkey_van_2011_recent.csv", "france_general_recent.csv",
    "iran_bam_2003_recent.csv", "iran_ahar_varzaghan_2012_recent.csv",
    "yemen_general_recent.csv", "syria_general_recent.csv",
    "ethiopia_general_recent.csv", "kenya_general_recent.csv",
    "algeria_boumerdes_2003_recent.csv", "morocco_alhoceima_2004_recent.csv",
    "southafrica_general_recent.csv", "russia_kurilislands_general_recent.csv",
    "kazakhstan_general_recent.csv", "turkmenistan_general_recent.csv",
    "russia_caucasus_general_recent.csv", "azerbaijan_general_recent.csv",
    "usa_yellowstone_general_recent.csv", "usa_newmadrid_general_recent.csv",
    "usa_oklahoma_induced_general_recent.csv", "usa_puertorico_general_recent.csv",
    "canada_quebec_general_recent.csv", "mexico_baja_general_recent.csv",
    "greenland_general_recent.csv", "newzealand_kaikoura_2016_recent.csv",
    "papuanewguinea_general_recent.csv", "newcaledonia_general_recent.csv",
    "marianaislands_general_recent.csv", "guam_general_recent.csv",
    "indonesia_sumatra_general_recent.csv", "indonesia_java_general_recent.csv",
    "cyprus_general_recent.csv", "poland_general_recent.csv",
    "myanmar_sagaing_general_recent.csv", "vietnam_general_recent.csv",
    "philippines_luzon_general_recent.csv", "philippines_mindanao_general_recent.csv",
    "usa_virginia_2011_recent.csv", "usa_nevada_basinrange_general_recent.csv",
    "usa_utah_wasatch_general_recent.csv", "haiti_2010_recent.csv",
    "guadeloupe_martinique_general_recent.csv",
    "china_yunnan_general_early2.csv", "china_yunnan_general_early3.csv",
    "china_xinjiang_general_early2.csv", "china_xinjiang_general_early3.csv",
    "india_assam_general_early2.csv", "india_assam_general_early3.csv",
    "colombia_andes_general_early2.csv", "colombia_andes_general_early3.csv",
    "argentina_sanjuan_general_early2.csv", "argentina_sanjuan_general_early3.csv",
    "bolivia_deep_general_early2.csv", "bolivia_deep_general_early3.csv",
    "guatemala_general_early2.csv", "guatemala_general_early3.csv",
    "costarica_general_early2.csv", "costarica_general_early3.csv",
    "panama_general_early2.csv", "panama_general_early3.csv",
    "dominicanrepublic_general_early2.csv", "dominicanrepublic_general_early3.csv",
    "portugal_azores_general_early2.csv", "portugal_azores_general_early3.csv",
    "tanzania_rift_general_early2.csv", "tanzania_rift_general_early3.csv",
    "drc_rift_general_early2.csv", "drc_rift_general_early3.csv",
    "mozambique_general_early2.csv",
    "russia_sakhalin_general_early2.csv", "russia_sakhalin_general_early3.csv",
    "russia_baikal_general_early2.csv", "russia_baikal_general_early3.csv",
    "usa_cascadia_general_early2.csv", "usa_cascadia_general_early3.csv",
    "canada_britishcolumbia_general_early2.csv", "canada_britishcolumbia_general_early3.csv",
    "australia_general_early2.csv", "australia_general_early3.csv",
    "vanuatu_general_early2.csv", "vanuatu_general_early3.csv",
    "solomonislands_general_early2.csv", "solomonislands_general_early3.csv",
    "fiji_general_early2.csv", "fiji_general_early3.csv",
    "samoa_general_early2.csv", "samoa_general_early3.csv",
    "centralasia_kyrgyzstan_tajikistan_early2.csv", "centralasia_kyrgyzstan_tajikistan_early3.csv",
    "uzbekistan_general_early2.csv", "uzbekistan_general_early3.csv",
    "mongolia_gobialtai_general_early2.csv", "china_gansu_general_early2.csv",
    "china_taiwanstrait_general_early.csv", "china_taiwanstrait_general_early2.csv",
    "china_hebei_general_early.csv", "china_hebei_general_early2.csv",
    "china_hebei_general_early3.csv", "china_shanxi_general_early.csv",
    "china_shanxi_general_early2.csv", "china_tibet_plateau_general_early.csv",
    "china_tibet_plateau_general_early2.csv", "china_tibet_plateau_general_early3.csv",
    "india_uttarakhand_general_early2.csv", "india_uttarakhand_general_early3.csv",
    "india_andaman_general_early2.csv", "india_andaman_general_early3.csv",
    "bangladesh_general_early2.csv", "bangladesh_general_early3.csv",
    "pakistan_general_early.csv", "pakistan_general_early2.csv",
    "pakistan_general_early3.csv", "nepal_sikkim_general_early.csv",
    "ecuador_general_early2.csv", "ecuador_general_early3.csv",
    "venezuela_general_early.csv", "venezuela_general_early2.csv",
    "venezuela_general_early3.csv", "nicaragua_general_early2.csv",
    "nicaragua_general_early3.csv", "cuba_general_early2.csv",
    "trinidadtobago_general_early.csv", "trinidadtobago_general_early2.csv",
    "honduras_general_early.csv", "honduras_general_early2.csv",
    "honduras_general_early3.csv", "mexico_oaxaca_general_early.csv",
    "mexico_oaxaca_general_early2.csv", "mexico_oaxaca_general_early3.csv",
    "iceland_general_early2.csv", "iceland_general_early3.csv",
    "norway_general_early.csv", "norway_general_early2.csv",
    "switzerland_general_early2.csv", "romania_vrancea_general_early.csv",
    "romania_vrancea_general_early2.csv", "bulgaria_general_early.csv",
    "bulgaria_general_early2.csv", "france_general_early.csv",
    "france_general_early2.csv", "germany_general_early.csv",
    "germany_general_early2.csv", "yemen_general_early2.csv",
    "yemen_general_early3.csv", "jordan_general_early.csv",
    "jordan_general_early2.csv", "israel_deadsea_general_early.csv",
    "syria_general_early.csv", "syria_general_early2.csv",
    "egypt_general_early.csv", "egypt_general_early2.csv",
    "ethiopia_general_early2.csv", "ethiopia_general_early3.csv",
    "kenya_general_early2.csv", "southafrica_general_early.csv",
    "southafrica_general_early2.csv", "southafrica_general_early3.csv",
    "malawi_general_early.csv", "malawi_general_early2.csv",
    "russia_kurilislands_general_early.csv", "russia_kurilislands_general_early2.csv",
    "russia_kurilislands_general_early3.csv", "kazakhstan_general_early2.csv",
    "kazakhstan_general_early3.csv", "turkmenistan_general_early.csv",
    "turkmenistan_general_early2.csv", "turkmenistan_general_early3.csv",
    "russia_caucasus_general_early.csv", "russia_caucasus_general_early2.csv",
    "russia_caucasus_general_early3.csv", "azerbaijan_general_early.csv",
    "azerbaijan_general_early2.csv", "azerbaijan_general_early3.csv",
    "usa_yellowstone_general_early2.csv", "usa_yellowstone_general_early3.csv",
    "usa_newmadrid_general_early.csv", "usa_newmadrid_general_early2.csv",
    "usa_newmadrid_general_early3.csv", "usa_oklahoma_induced_general_early.csv",
    "usa_puertorico_general_early.csv", "usa_puertorico_general_early2.csv",
    "usa_puertorico_general_early3.csv", "canada_quebec_general_early.csv",
    "canada_quebec_general_early2.csv", "mexico_baja_general_early.csv",
    "mexico_baja_general_early2.csv", "mexico_baja_general_early3.csv",
    "greenland_general_early.csv", "greenland_general_early2.csv",
    "greenland_general_early3.csv", "papuanewguinea_general_early.csv",
    "papuanewguinea_general_early2.csv", "papuanewguinea_general_early3.csv",
    "newcaledonia_general_early.csv", "newcaledonia_general_early2.csv",
    "newcaledonia_general_early3.csv", "tuvalu_kiribati_general_early2.csv",
    "marianaislands_general_early.csv", "marianaislands_general_early2.csv",
    "marianaislands_general_early3.csv", "guam_general_early.csv",
    "guam_general_early2.csv", "guam_general_early3.csv",
    "indonesia_sumatra_general_early2.csv", "indonesia_sumatra_general_early3.csv",
    "indonesia_java_general_early.csv", "indonesia_java_general_early2.csv",
    "indonesia_java_general_early3.csv", "cyprus_general_early.csv",
    "cyprus_general_early2.csv", "slovenia_general_early.csv",
    "slovenia_general_early2.csv", "austria_general_early.csv",
    "austria_general_early2.csv", "poland_general_early.csv",
    "poland_general_early2.csv", "myanmar_sagaing_general_early.csv",
    "myanmar_sagaing_general_early2.csv", "myanmar_sagaing_general_early3.csv",
    "laos_general_early.csv", "laos_general_early2.csv",
    "thailand_general_early.csv", "thailand_general_early2.csv",
    "vietnam_general_early.csv", "vietnam_general_early2.csv",
    "philippines_luzon_general_early.csv", "philippines_luzon_general_early2.csv",
    "philippines_luzon_general_early3.csv", "philippines_mindanao_general_early.csv",
    "philippines_mindanao_general_early2.csv", "philippines_mindanao_general_early3.csv",
    "bhutan_general_early.csv", "italy_sicily_etna_general_early.csv",
    "italy_sicily_etna_general_early2.csv", "usa_nevada_basinrange_general_early.csv",
    "usa_nevada_basinrange_general_early2.csv", "usa_nevada_basinrange_general_early3.csv",
    "usa_utah_wasatch_general_early.csv", "usa_utah_wasatch_general_early2.csv",
    "usa_utah_wasatch_general_early3.csv", "guadeloupe_martinique_general_early.csv",
    "guadeloupe_martinique_general_early2.csv", "guadeloupe_martinique_general_early3.csv",
    "botswana_general_early.csv", "botswana_general_early2.csv",
    "botswana_general_early3.csv",
]
STANDARD_FILES = STANDARD_FILES + STANDARD_FILES_V9

# Files inspected and confirmed NOT to be point-event earthquake catalogs
# (excluded per task #43's inspection): wildfire perimeters, an opinion
# survey, a region polygon, admin-boundary shapefiles/GeoJSON. Listed
# here (not silently omitted) so the exclusion is auditable.
EXCLUDED_NON_CATALOG_FILES: List[str] = [
    "earthquake.csv", "CA_Perimeters_NIFC_FIRIS_public_view.csv",
    "CA_Perimeters_NIFC_FIRIS_public_view.geojson",
    "polygon_nannkai (2).csv", "gadm41_JPN_0.shp", "gadm41_JPN_0.shx",
    "gadm41_JPN_1.json", "gadm41_JPN_2.json",
]

# Real USGS ComCat GeoJSON FeatureCollection exports -- NOT the flat-CSV
# ComCat schema STANDARD_FILES expects, so they need parsers.prepare_usgs_geojson
# instead of prepare_dataset.py's CANDIDATES-based CSV parser. Added
# 2026-07-05 per the DISCLOSED CORRECTION in this module's docstring above
# -- both were present in the user's original file list but missed by the
# initial build; confirmed genuine and distinct from every already-included
# CSV export before being added here.
GEOJSON_FILES: List[str] = [
    "ishikawa_202401.json",   # Ishikawa region, 2023-12-25 to 2024-01-24, M>=4.5, 46 features
    "japan_2023-.json",       # Japan region, 2023-01-01 to 2024-02-03, M>=4.5, 644 features
]


def _dataset_name_for(raw_filename: str) -> str:
    stem = Path(raw_filename).stem
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in stem)
    return f"real_{safe}"


def build_real_datasets() -> List[Dict]:
    """Normalise every real file into datasets/<name>/records.csv. Returns
    a list of manifest row dicts. Never raises on a single-file failure --
    logs it and continues, consistent with prepare_dataset.py's own
    disclosed-not-fatal error handling for malformed rows."""
    rows: List[Dict] = []

    for name in ("nz", "chile"):
        path = DATASETS_OUT / name / "records.csv"
        if not path.exists():
            print(f"[build_real] WARNING: expected pre-existing canonical dataset "
                  f"'{name}' not found at {path} -- skipping.")
            continue
        try:
            ds = load_dataset_csv(path, name=name)
            rows.append({
                "dataset_id": name, "source_file": f"Dataset/earthquakes_{name}.csv",
                "category": "real", "label": "known_good", "corruption_type": "",
                "severity": "", "n_records": ds.n,
                "notes": "Pre-existing canonical dataset from the project's original NZ/Chile build.",
            })
        except Exception as e:
            print(f"[build_real] FAILED to load pre-existing '{name}': {e}")

    for fname in STANDARD_FILES:
        src = DATASET_DIR / fname
        name = _dataset_name_for(fname)
        if not src.exists():
            print(f"[build_real] WARNING: {src} not found -- skipping.")
            continue
        try:
            out_path = _pd_mod.prepare(
                input_path=src, dataset_name=name, column_overrides={}, interactive=False,
            )
            ds = load_dataset_csv(out_path, name=name)
            rows.append({
                "dataset_id": name, "source_file": f"Dataset/{fname}",
                "category": "real", "label": "known_good", "corruption_type": "",
                "severity": "", "n_records": ds.n,
                "notes": "Standard USGS ComCat CSV schema, auto-detected by prepare_dataset.py.",
            })
        except Exception as e:
            print(f"[build_real] FAILED on {fname}: {type(e).__name__}: {e}")
            traceback.print_exc()

    for fname in GEOJSON_FILES:
        src = DATASET_DIR / fname
        name = _dataset_name_for(fname)
        if not src.exists():
            print(f"[build_real] WARNING: {src} not found -- skipping.")
            continue
        try:
            out_path = parsers.prepare_usgs_geojson(src, name)
            ds = load_dataset_csv(out_path, name=name)
            rows.append({
                "dataset_id": name, "source_file": f"Dataset/{fname}",
                "category": "real", "label": "known_good", "corruption_type": "",
                "severity": "", "n_records": ds.n,
                "notes": "USGS ComCat GeoJSON FeatureCollection export, parsed via "
                         "parsers.prepare_usgs_geojson. Added 2026-07-05 per this "
                         "module's docstring DISCLOSED CORRECTION -- was present in "
                         "the user's original file list but missed by the initial build.",
            })
        except Exception as e:
            print(f"[build_real] FAILED on {fname}: {type(e).__name__}: {e}")
            traceback.print_exc()

    special = [
        ("earthquake1.csv", "real_earthquake1", parsers.prepare_earthquake1,
         "NOAA/ISC-GEM significant earthquakes 1965-2016; Type-filtered to "
         "'Earthquake' rows only (Explosion/Nuclear Explosion/Rock Burst dropped)."),
        ("Events.csv", "real_events_atkinson", parsers.prepare_events,
         "Atkinson/NGA-West3 ground-motion research catalog; 6-column Y/M/D/H/M/S merge."),
        ("PastHugeEarthquakeinNankai.csv", "real_nankai_historical", parsers.prepare_nankai,
         "Historical Nankai-trough catalog, 684-1946 AD; 8/13 rows have origin_time=NaT "
         "because their dates predate datetime64[ns]'s representable floor (1677-09-21) -- "
         "a disclosed STORAGE-FORMAT limitation, not a genuine defect in the source. "
         "No depth ever reported by this source (left blank, not fabricated)."),
    ]
    for fname, name, fn, note in special:
        src = DATASET_DIR / fname
        if not src.exists():
            print(f"[build_real] WARNING: {src} not found -- skipping.")
            continue
        try:
            out_path = fn(src, name)
            ds = load_dataset_csv(out_path, name=name)
            rows.append({
                "dataset_id": name, "source_file": f"Dataset/{fname}",
                "category": "real", "label": "known_good", "corruption_type": "",
                "severity": "", "n_records": ds.n, "notes": note,
            })
        except Exception as e:
            print(f"[build_real] FAILED on {fname}: {type(e).__name__}: {e}")
            traceback.print_exc()

    return rows


# Chosen to (a) cover every corruption TYPE in calibration/corrupt.py,
# (b) span all three severities, (c) draw from a diverse mix of source
# real datasets (different regions/sizes) rather than corrupting the same
# one repeatedly, so the corrupted half of the corpus is not itself a
# near-duplicate cluster.
CORRUPTION_PLAN: List[Dict] = [
    {"source": "real_all_month", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_all_month", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_japan_2000_2023_query", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_japan_2000_2023_query", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_usgs_main", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_usgs_main", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_HIGH},
    {"source": "nz", "fn": "inject_missingness", "severity": corrupt.SEVERITY_LOW},
    {"source": "nz", "fn": "inject_missingness", "severity": corrupt.SEVERITY_MED},
    {"source": "nz", "fn": "inject_missingness", "severity": corrupt.SEVERITY_HIGH},
    {"source": "chile", "fn": "depth_implausible", "severity": corrupt.SEVERITY_LOW},
    {"source": "chile", "fn": "depth_implausible", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_morocco_20230908_query", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_morocco_20230908_query", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_tonga_20210101_20220117_query", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_MED},
    {"source": "real_haiti_20210814_query", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
    {"source": "real_earthquake1", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_MED},
    {"source": "real_events_atkinson", "fn": "inject_missingness", "severity": corrupt.SEVERITY_MED},
    {"source": "real_greece_2024_2025", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_MED},
    {"source": "real_taiwan_2024_query", "fn": "depth_implausible", "severity": corrupt.SEVERITY_MED},
    # 7th-pass additions (2026-07-07): 4 more corrupted derivatives drawn
    # from the newly-added real datasets, chosen to (a) preserve the
    # corpus's ~50:19 real:corrupted ratio at the new ~61:23 scale and
    # (b) span 4 distinct corruption types across 4 distinct new source
    # regions, consistent with this plan's existing diversity rationale.
    {"source": "real_chiapas_mexico_2017", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_MED},
    {"source": "real_kahramanmaras_turkey_2023", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_MED},
    {"source": "real_gorkha_nepal_2015", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
    {"source": "real_png_highlands_2018", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_MED},
    # 8th-pass additions (2026-07-10): 50 more corrupted derivatives drawn
    # from the 144 new real datasets added by STANDARD_FILES_V8, chosen to
    # (a) roughly preserve the corpus's ~real:corrupted ratio at the new
    # ~205:73 scale (was 61:23), (b) cycle evenly through all 6 corruption
    # TYPEs and all 3 severities (round-robin, index i -> fn[i%6],
    # severity[i%3]), and (c) draw from 50 distinct new source regions
    # (never the same source twice) spanning every continent added in this
    # pass, consistent with this plan's pre-existing diversity rationale.
    {"source": "real_china_sichuan_2008", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_india_kashmir_2005", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
    {"source": "real_colombia_andes_general", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_guatemala_general", "fn": "inject_missingness", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_puertorico_2020_ponce", "fn": "depth_implausible", "severity": corrupt.SEVERITY_MED},
    {"source": "real_croatia_petrinja_2020", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_tanzania_rift_general", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_iraq_halabja_2017", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
    {"source": "real_russia_sakhalin_general", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_usa_hawaii_kilauea_2018", "fn": "inject_missingness", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_usa_cascadia_general", "fn": "depth_implausible", "severity": corrupt.SEVERITY_MED},
    {"source": "real_australia_general", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_vanuatu_general", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_centralasia_kyrgyzstan_tajikistan", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
    {"source": "real_china_qinghai_yushu_2010", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_india_andaman_general", "fn": "inject_missingness", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_pakistan_general", "fn": "depth_implausible", "severity": corrupt.SEVERITY_MED},
    {"source": "real_ecuador_general", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_chile_maule_2010", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_venezuela_general", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
    {"source": "real_mexico_oaxaca_general", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_iceland_general", "fn": "inject_missingness", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_switzerland_general", "fn": "depth_implausible", "severity": corrupt.SEVERITY_MED},
    {"source": "real_turkey_izmit_1999", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_france_general", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_germany_general", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
    {"source": "real_iran_bam_2003", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_yemen_general", "fn": "inject_missingness", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_syria_general", "fn": "depth_implausible", "severity": corrupt.SEVERITY_MED},
    {"source": "real_ethiopia_general", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_algeria_boumerdes_2003", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_southafrica_general", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
    {"source": "real_russia_kurilislands_general", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_kazakhstan_general", "fn": "inject_missingness", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_usa_yellowstone_general", "fn": "depth_implausible", "severity": corrupt.SEVERITY_MED},
    {"source": "real_usa_oklahoma_induced_general", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_usa_puertorico_general", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_canada_quebec_general", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
    {"source": "real_greenland_general", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_newzealand_kaikoura_2016", "fn": "inject_missingness", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_papuanewguinea_general", "fn": "depth_implausible", "severity": corrupt.SEVERITY_MED},
    {"source": "real_indonesia_sumatra_general", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_indonesia_java_general", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_northkorea_general", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
    {"source": "real_china_xinjiang_general", "fn": "inject_duplicates", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_bangladesh_general", "fn": "inject_missingness", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_nepal_sikkim_general", "fn": "depth_implausible", "severity": corrupt.SEVERITY_MED},
    {"source": "real_honduras_general", "fn": "timestamp_collision", "severity": corrupt.SEVERITY_HIGH},
    {"source": "real_romania_vrancea_general", "fn": "coordinate_jitter", "severity": corrupt.SEVERITY_LOW},
    {"source": "real_malawi_general", "fn": "magnitude_gr_violation", "severity": corrupt.SEVERITY_MED},
]

# 9th-pass additions (2026-07-10/11): 100 more corrupted derivatives, drawn
# from 100 DISTINCT real sources never previously corrupted (of the 139
# real datasets never used in CORRUPTION_PLAN above at the time this was
# written -- a mix of long-standing STANDARD_FILES entries, 7th/8th-pass
# additions, and 3 of the 8th-pass "_early" variants -- verified by manual
# cross-reference against every "source" value already in this list, not
# guessed). Added specifically to keep the corpus known_good-majority
# after the 270 new fabricated_level1..9 datasets below (see
# STANDARD_FILES_V9's comment above for the full rationale) -- NOT because
# corrupted:fabricated need to track each other 1:1, just because both are
# growing at once and only real-side growth (STANDARD_FILES_V9) plus this
# addition together keep known_bad from becoming the majority. Same
# round-robin convention as the 8th pass: fn cycles through all 6
# CORRUPTIONS types (i % 6), severity cycles LOW/MED/HIGH (i % 3).
_NINTH_PASS_CORRUPTION_SOURCES: List[str] = [
    "real_202505_tokyo", "real_202506_turkey", "real_202507_Kamchatka",
    "real_202509_Kamchatka", "real_202510_philippines", "real_2025_03_myanmar",
    "real_202604_tohoku_japan", "real_202606_philippines",
    "real_afghanistan_20231008_query", "real_afghanistan_20231015_query",
    "real_afghanistan_2025_09_01", "real_ishikawa_202401_query",
    "real_ishikawa_202411_query", "real_ishikawa_2024_query",
    "real_japan-20190101_20211203_query", "real_japan_20190101-20211009_query",
    "real_japan_20220317_query", "real_japan_20220319_query",
    "real_japan_saitama_202407_202501", "real_miyazaki_2024-2025",
    "real_peru_20250616", "real_potvilla_2024012", "real_taiwan_20240403_query",
    "real_taiwan_20240423_query", "real_taiwan_202501", "real_tibet_202501",
    "real_tohoku_2005_2011", "real_tohoku_202511", "real_tohoku_202512",
    "real_tohoku_202606", "real_tokara_202506", "real_turkey_202504",
    "real_usgs_current", "real_venezuela_202606", "real_yamanashi_202606",
    "real_indonesia_palu_2018", "real_ridgecrest_california_2019",
    "real_amatrice_norcia_italy_2016", "real_anchorage_alaska_2018",
    "real_haiti_2010", "real_kermanshah_iran_2017",
    "real_muisne_pedernales_ecuador_2016", "real_china_yunnan_general",
    "real_india_gujarat_bhuj_2001", "real_india_assam_general",
    "real_pakistan_balochistan_2013", "real_argentina_sanjuan_general",
    "real_bolivia_deep_general", "real_elsalvador_2001", "real_costarica_general",
    "real_panama_general", "real_dominicanrepublic_general",
    "real_albania_durres_2019", "real_portugal_azores_general",
    "real_drc_rift_general", "real_mozambique_general", "real_lebanon_general",
    "real_russia_baikal_general", "real_usa_california_southnapa_2014",
    "real_canada_britishcolumbia_general", "real_solomonislands_general",
    "real_fiji_general", "real_samoa_general", "real_uzbekistan_general",
    "real_mongolia_gobialtai_general", "real_china_gansu_general",
    "real_china_taiwanstrait_general", "real_china_hebei_general",
    "real_china_shanxi_general", "real_china_tibet_plateau_general",
    "real_india_uttarakhand_general", "real_colombia_armenia_1999",
    "real_peru_pisco_2007", "real_peru_arequipa_2001", "real_chile_iquique_2014",
    "real_nicaragua_general", "real_cuba_general", "real_trinidadtobago_general",
    "real_iceland_reykjanes_2021", "real_norway_general", "real_bulgaria_general",
    "real_turkey_van_2011", "real_iran_ahar_varzaghan_2012", "real_jordan_general",
    "real_israel_deadsea_general", "real_egypt_general", "real_kenya_general",
    "real_morocco_alhoceima_2004", "real_madagascar_general",
    "real_turkmenistan_general", "real_russia_caucasus_general",
    "real_azerbaijan_general", "real_usa_newmadrid_general",
    "real_mexico_baja_general", "real_newcaledonia_general",
    "real_marianaislands_general", "real_guam_general",
    "real_china_yunnan_general_early", "real_china_xinjiang_general_early",
    "real_india_assam_general_early",
]
_CORRUPTION_FN_CYCLE = [
    "coordinate_jitter", "magnitude_gr_violation", "inject_duplicates",
    "inject_missingness", "depth_implausible", "timestamp_collision",
]
_SEVERITY_CYCLE = [corrupt.SEVERITY_LOW, corrupt.SEVERITY_MED, corrupt.SEVERITY_HIGH]
for _i, _src in enumerate(_NINTH_PASS_CORRUPTION_SOURCES):
    CORRUPTION_PLAN.append({
        "source": _src,
        "fn": _CORRUPTION_FN_CYCLE[_i % len(_CORRUPTION_FN_CYCLE)],
        "severity": _SEVERITY_CYCLE[_i % len(_SEVERITY_CYCLE)],
    })


def build_corrupted_datasets() -> List[Dict]:
    rows: List[Dict] = []
    for i, spec in enumerate(CORRUPTION_PLAN):
        source_path = DATASETS_OUT / spec["source"] / "records.csv"
        if not source_path.exists():
            print(f"[build_corrupt] WARNING: source '{spec['source']}' not built -- skipping.")
            continue
        try:
            base_ds = load_dataset_csv(source_path, name=spec["source"])
            fn = corrupt.CORRUPTIONS[spec["fn"]]
            rng = np.random.RandomState(1000 + i)
            corrupted, desc = fn(base_ds, spec["severity"], rng)
            sev_label = ("low" if spec["severity"] <= corrupt.SEVERITY_LOW
                         else "high" if spec["severity"] >= corrupt.SEVERITY_HIGH else "med")
            name = f"corrupt_{spec['source']}_{spec['fn']}_{sev_label}"
            corrupted.name = name
            out_path = DATASETS_OUT / name / "records.csv"
            save_dataset_csv(corrupted, out_path)
            rows.append({
                "dataset_id": name, "source_file": f"derived from {spec['source']}",
                "category": "corrupted", "label": "known_bad",
                "corruption_type": spec["fn"], "severity": sev_label,
                "n_records": corrupted.n, "notes": desc,
            })
        except Exception as e:
            print(f"[build_corrupt] FAILED on {spec}: {type(e).__name__}: {e}")
            traceback.print_exc()
    return rows


def build_fabricated_datasets() -> List[Dict]:
    rows: List[Dict] = []
    specs = [
        ("fabricated_naive_1", corrupt.fabricate_naive, 1500, 101),
        ("fabricated_naive_2", corrupt.fabricate_naive, 800, 102),
        ("fabricated_sophisticated_1", corrupt.fabricate_sophisticated, 1500, 201),
        ("fabricated_sophisticated_2", corrupt.fabricate_sophisticated, 3000, 202),
        # 7th-pass addition (2026-07-07): 1 more fabricated catalog to keep
        # the fabricated:real ratio (~4/50=0.08) roughly constant at the
        # new ~61-real scale (5/61=0.082).
        ("fabricated_sophisticated_3", corrupt.fabricate_sophisticated, 2000, 203),
        # 8th-pass additions (2026-07-10): 12 more fabricated catalogs (6
        # naive, 6 sophisticated) to keep the fabricated:real ratio
        # (5/61=0.082) roughly constant at the new ~205-real scale
        # (17/205=0.083), alongside the 50 new corrupted derivatives above.
        ("fabricated_naive_3", corrupt.fabricate_naive, 1200, 104),
        ("fabricated_naive_4", corrupt.fabricate_naive, 2000, 105),
        ("fabricated_naive_5", corrupt.fabricate_naive, 600, 106),
        ("fabricated_naive_6", corrupt.fabricate_naive, 900, 107),
        ("fabricated_naive_7", corrupt.fabricate_naive, 1700, 108),
        ("fabricated_naive_8", corrupt.fabricate_naive, 1100, 109),
        ("fabricated_sophisticated_4", corrupt.fabricate_sophisticated, 1000, 204),
        ("fabricated_sophisticated_5", corrupt.fabricate_sophisticated, 2500, 205),
        ("fabricated_sophisticated_6", corrupt.fabricate_sophisticated, 1800, 206),
        ("fabricated_sophisticated_7", corrupt.fabricate_sophisticated, 3500, 207),
        ("fabricated_sophisticated_8", corrupt.fabricate_sophisticated, 1300, 208),
        ("fabricated_sophisticated_9", corrupt.fabricate_sophisticated, 2200, 209),
    ]
    # 9th-pass additions (2026-07-10/11): 270 new fabricated datasets = 9
    # graduated realism levels (calibration/corrupt.py's fabricate_level1..9;
    # see LEVEL_DESCRIPTIONS there for exactly what each level adds) x 30
    # datasets/level x 1500 rows/dataset, per explicit user request. Level
    # 10 (fabricate_level10_adversarial) is DELIBERATELY NOT included here --
    # see calibration/build_adversarial_corpus.py, which builds it into a
    # separate corpus/manifest never fed into this pipeline's
    # EWM/threshold calibration, to avoid calibrating weights/thresholds
    # against the exact adversarial construction being evaluated.
    for _level in range(1, 10):
        _fn = getattr(corrupt, f"fabricate_level{_level}")
        for _k in range(30):
            specs.append((f"fabricated_level{_level}_{_k + 1}", _fn, 1500, 1000 + _level * 100 + _k))
    for name, fn, n, seed in specs:
        ds = fn(n, np.random.RandomState(seed), name=name)
        out_path = DATASETS_OUT / name / "records.csv"
        save_dataset_csv(ds, out_path)
        if "naive" in name:
            kind = "naive (uniform magnitude + uniform 2D coordinate scatter)"
        elif "sophisticated" in name:
            kind = ("sophisticated (genuine GR-law b~1.0 + fault-line-clustered coordinates, "
                    "defeats every intrinsic check -- construction reused from "
                    "tests/test_adversarial.py's make_gamed_fabricated_catalog)")
        elif "level" in name:
            _lvl = int(name.split("level")[1].split("_")[0])
            kind = f"graduated realism level {_lvl}/10 (see corrupt.LEVEL_DESCRIPTIONS[{_lvl}]): {corrupt.LEVEL_DESCRIPTIONS[_lvl]}"
        else:
            kind = "unspecified fabrication construction"
        rows.append({
            "dataset_id": name, "source_file": "synthetic (calibration/corrupt.py)",
            "category": "fabricated", "label": "known_bad", "corruption_type": "full_fabrication",
            "severity": "n/a", "n_records": ds.n,
            "notes": f"Total fabrication, {kind}, seed={seed}.",
        })
    return rows


def main() -> None:
    all_rows: List[Dict] = []
    print("=" * 70)
    print("STEP 1/3: building real datasets")
    print("=" * 70)
    all_rows.extend(build_real_datasets())

    print("=" * 70)
    print("STEP 2/3: building corrupted (known-bad) variants")
    print("=" * 70)
    all_rows.extend(build_corrupted_datasets())

    print("=" * 70)
    print("STEP 3/3: building fully-fabricated (known-bad) catalogs")
    print("=" * 70)
    all_rows.extend(build_fabricated_datasets())

    df = pd.DataFrame(all_rows)
    df.to_csv(MANIFEST_PATH, index=False)

    n_good = int((df["label"] == "known_good").sum())
    n_bad = int((df["label"] == "known_bad").sum())
    print("=" * 70)
    print(f"Corpus assembled: {len(df)} datasets total "
          f"({n_good} known_good, {n_bad} known_bad).")
    print(f"Manifest written -> {MANIFEST_PATH}")
    print("=" * 70)


if __name__ == "__main__":
    main()
