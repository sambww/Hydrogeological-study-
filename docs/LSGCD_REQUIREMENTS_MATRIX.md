# LSGCD Hydrogeological Report Guidelines (11-11-2022) - requirements matrix

| Item | Requirement | Report section | Code | Automated? |
|---|---|---|---|---|
| II.B.1 | Spacing compliance or exception | 1 | `analysis/spacing.py` | yes (exception documentation: reviewer) |
| II.B.2(a) | Schematic well construction diagram | 2, Table 2, schematic figure | `figures/well_schematic.py` | yes |
| II.B.2(b) | Anticipated lithology | 2 | intake `anticipated_lithology`; `review.opinions.lithology_basis` | reviewer |
| II.B.2(c) | Location maps (county, property) | Intro, 1 | `figures/location_map.py`, `property_map.py` | yes (county/parcel GeoJSON optional) |
| II.B.3(a) | Aquifer identification with District staff | 4 | `review.opinions.aquifer_identification` | reviewer |
| II.B.3(b) | Surface/subsurface geology, recharge features | 3, 4 | static block; `review.opinions.recharge_features` | reviewer |
| II.B.3(c)(d) | Target zone depth, screen intervals, thickness | 4 | `analysis/aquifer_params.py`, context | yes |
| II.B.3(e)(f) | Confined/unconfined; confining thickness | 4 | intake `confinement`; `review.opinions.confinement` | reviewer |
| II.B.3(g) | T, K, S from GAM or site data, tabulated | 4, Table 3 | `analysis/aquifer_params.py` | yes |
| II.B.3(h) | Registered/permitted wells within max(1/2 mi, spacing) | 1, Table 1, wells figure | `data/wells.py` | yes |
| II.B.3(i) | Streams/springs within 1 mile | 4 | `data/hydrography.py` | yes (data supplied) |
| II.B.4 | Water quality from literature and well reports | 5 | `data/water_quality.py`, WQ maps, Tables 4-5 | yes + reviewer interpretation |
| II.B.5(a)(i-iii) | 24-h and max-production simulations, results, methodology | 6.1-6.x | `analysis/scenarios.py`, `theis.py` | yes |
| II.B.5(a)(iv) | Cone-of-depression maps (well only; system) | 6 figures | `figures/drawdown_map.py` | yes |
| II.B.5(b) | Interference among system wells | 6.x matrix table | `analysis/interference.py` | yes |
| II.B.5(c) | Tabulated impacts at nearby wells (24 h and max) | 6 impact tables | `analysis/scenarios.py` | yes |
| I.C | Stamped by Texas P.G./P.E. | seal block | `review.yaml` | reviewer |
| III.1 | Geophysical logs (res/induction + SP/gamma, open hole, LAS) | Post report 2, log inventory table | `analysis/asbuilt.py`, `data/las.py` | yes (interpretation: reviewer) |
| III.2 | PWS sampling per TCEQ | Post report 4 | `data/water_quality.py` | reviewer confirms completeness |
| III.3 | Test water levels; specific capacity and transmissivity | Post report 3, Appendix C | `analysis/pumptest.py` | yes |
| III.4 | Aquifer conditions and well/pump parameter table | Post report 1, Table 1 | `analysis/asbuilt.py` | yes |
| III.5 | Field parameters | Post report 4 table | intake `as_built.field_params` | yes |
| III.6 | Post-construction lab analyses | Post report 4 tables | `data/water_quality.py` | yes |

Spacing multipliers configured (`districts/lsgcd.yaml`): Chicot/Evangeline 2.0 ft/gpm, Jasper 1.5, Catahoula 1.0 -
verify against the current Rule 3.3 before each submittal.
