# Data sources and drop-in file formats

All inputs are local files described in `data/manifest.yaml`. Nothing is fetched at run time. Live connectors
(Phase 2, `hydrostudy/connectors/`) will populate these files from the public sources below on a machine with
internet access; the formats stay the same.

| Key | What | Source (public) | How to obtain |
|---|---|---|---|
| `district_wells` | Registered and permitted wells near the site | LSGCD well database (public well map on lonestargcd.org; District staff provide exports on request per Guidelines II.B.3(h)) | Request an export or download from the well map; map columns in the manifest |
| (supplement) | Well reports with depth/screen | TWDB Submitted Drillers Reports (SDR) bulk download `SDRDownload.zip`; TWDB Groundwater Database `GWDBDownload.zip` (pipe-delimited, nightly) | Filter by county / radius; append rows to `district_wells.csv` |
| `water_quality` | Sample results for nearby PWS wells and TWDB wells | TCEQ Drinking Water Viewer (dwv.tceq.texas.gov, CSV export of chemical results by PWS); TWDB GWDB water-quality tables | Export and reshape to the long format below |
| aquifer parameters | T, K, S and layer top/bottom at the site | TWDB Northern Gulf Coast GAM v4.1 (adopted Jan 2026) or HAGM (Kasmarek 2013, cited in the 2022 guidelines) | Read model arrays at the site cell (Phase 2 script `scripts/build_gam_lookup.py`); enter values with citation in `intake.yaml` |
| `streams` | Streams/ponds within 1 mile | USGS National Hydrography Dataset (ArcGIS REST) | Export GeoJSON (WGS84) with a `name` property |
| `parcels`, `boundary` | Parcel lines and the applicant's property | Montgomery County open data (MCAD tax parcels, ArcGIS Hub) | Export GeoJSON (WGS84) |
| `county` | County outline | TxDOT / TNRIS county boundaries | Export GeoJSON (WGS84) |
| `springs_csv` | Springs near the site | TWDB GWDB springs table | CSV with `name, lat, lon, source`; features within 1 mile are listed automatically |
| `gam_lookup` | GAM T/K/S and layer top/bottom at the site cell plus a neighborhood grid | HAGM model archive (USGS SIR 2012-5154) or Northern Gulf Coast GAM v4.1 files (TWDB glfc_n page) | `python scripts/build_gam_lookup.py --engine mf6|mf2k ... --out data/gam_lookup.json` (run on a machine with the model files; not exercised in the sandbox) |
| elevation | Ground elevation | USGS EPQS point service | Enter `elevation_ft_msl` in intake |
| springs | Springs within 1 mile | TWDB GWDB springs | Record search result in manifest `springs:` |

## `district_wells.csv` columns
`registration_no, permit_no, owner, address, city, total_depth_ft, screen_intervals, aquifer, status, lat, lon`
(`screen_intervals` like `600-655; 700-720`; blank cells become "N/A"; aquifer inferred from screen midpoint when blank).
Other column names can be mapped in the manifest: `columns: {registration_no: "Well Registration No."}`.

## `water_quality_samples.csv` columns (long format)
`well_id, well_name, source, sample_date (YYYY-MM-DD), lat, lon, depth_ft, aquifer, constituent, value, units, qualifier`
Constituent keys: `ph, tds, no3, no2, as, f, al, cu, fe, mn, zn, pb, so4, cl, hardness, gross_alpha, gross_beta, ra_combined, uranium`.
Qualifier `<` or `ND` marks below-detection values. Units are normalized to the TCEQ reference units (`hydrostudy/reference/tceq_limits.yaml`).

## Manifest example
```yaml
files:
  district_wells: {path: district_wells.csv, source: "LSGCD export 2026-09-01", retrieved: "2026-09-01", crs: EPSG:4326}
  water_quality:  {path: water_quality_samples.csv, source: "TCEQ DWV export", retrieved: "2026-09-01"}
  streams:        {path: streams.geojson, source: "USGS NHD", retrieved: "2026-09-01", crs: EPSG:4326}
hydrography_notes:
  - {name: "Dry Creek", type: stream, within_1_mile: true, source: "USGS NHD"}
springs: {searched: true, source: "TWDB GWDB", found: []}
```
Every file's SHA-256, row count and source are written to `build/provenance.json` and Appendix B.

## Property boundary (`boundary`)
GeoJSON polygon(s) of the applicant's tract in WGS84 (`site.boundary_geojson` in `intake.yaml`, e.g. `data/boundary.geojson`).
When present, the nearest-boundary distance of every well is computed from the polygon and used unless the intake
states a value; a stated value that differs from the polygon distance by more than 10% raises a
`BOUNDARY_DISTANCE_MISMATCH` review flag. Parcels (`parcels`) are drawn on the property map; the county outline
(`county`) on the location map; streams/ponds (`streams`, features need a `name` and optional `type`) on the wells map
and in the hydrography statement.

## GAM lookup (`gam_lookup`)
`data/gam_lookup.json` written by `scripts/build_gam_lookup.py`. When an aquifer's `params.t_ft2d`, `s`, `k_ftd`,
`top_ft_bgl` or `bottom_ft_bgl` are omitted in `intake.yaml` they are taken from the lookup (`params.source.kind: gam`),
the citation is filled from the file, and three raster figures (T, K, S around the site) are inserted after the
parameter table. A stated transmissivity that differs from the lookup by more than 25% raises a `GAM_MISMATCH` flag.
The script reads MODFLOW 6 (GULF-2023 / GAM v4.x) or MODFLOW-2000 (HAGM) files with flopy (`pip install -e .[gam]`).
