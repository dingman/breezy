# Open-Meteo `/v1/previous-runs` probe (P2 Probe A)

## EVIDENCE ONLY - NEVER INGEST

These captures must NEVER be ingested into the production forecast
catalog. Backfilling them under a plausible retrieval timestamp would
be backdating and would violate the point-in-time forecast design.

**A forecast archive cannot produce a backtest, because a backtest also
needs prices, and prices are forward-only and permanently
unrecoverable.** What a forecast archive produces is a forecast-error /
calibration dataset.

Host: `api.open-meteo.com` (settlement host NOT touched)
Transport: `breezy.ingest.probe_transport.ProbeTransport`, max_body_bytes=524288
Request budget: 24 hard; spent 22.
Planned steps: 22

## Outcomes

| # | label | status | bytes | outcome |
|--:|---|--:|--:|---|
| 1 | `q1_baseline_unkeyed` | 404 | 35 | ok |
| 2 | `q2_previous_day_7` | 404 | 35 | ok |
| 3 | `q2_previous_day_boundary_probe` | 404 | 35 | ok |
| 4 | `q2_previous_day_far_boundary` | 404 | 35 | ok |
| 5 | `q2_hourly_variable_naming` | 404 | 35 | ok |
| 6 | `q3_archive_depth_2024` | 404 | 35 | ok |
| 7 | `q3_archive_depth_2022` | 404 | 35 | ok |
| 8 | `q3_archive_depth_2019` | 404 | 35 | ok |
| 9 | `q4_anchor_daily_window` | 404 | 35 | ok |
| 10 | `q4_anchor_single_day_control` | 404 | 35 | ok |
| 11 | `q4_anchor_second_site` | 404 | 35 | ok |
| 12 | `q5_publication_lag_today` | 404 | 35 | ok |
| 13 | `q5_publication_lag_yesterday` | 404 | 35 | ok |
| 14 | `q6_restatement_key_capture` | 404 | 35 | ok |
| 15 | `q6_restatement_key_capture_older` | 404 | 35 | ok |
| 16 | `q7_model_best_match` | 404 | 35 | ok |
| 17 | `q7_model_ecmwf_ifs025` | 404 | 35 | ok |
| 18 | `q7_model_gfs_seamless` | 404 | 35 | ok |
| 19 | `q7_model_icon_seamless` | 404 | 35 | ok |
| 20 | `q7_model_meteofrance_seamless` | 404 | 35 | ok |
| 21 | `q8_licence_and_error_shape` | 404 | 35 | ok |
| 22 | `q9_largest_plausible_payload` | 404 | 35 | ok |

## Question coverage

- `q1_unkeyed_and_on_which_host`: planned ['q1_baseline_unkeyed']; answered ['q1_baseline_unkeyed']
- `q2_variable_naming_and_real_max_n`: planned ['q2_previous_day_7', 'q2_previous_day_boundary_probe', 'q2_previous_day_far_boundary', 'q2_hourly_variable_naming']; answered ['q2_previous_day_7', 'q2_previous_day_boundary_probe', 'q2_previous_day_far_boundary', 'q2_hourly_variable_naming']
- `q3_archive_depth_for_one_site`: planned ['q3_archive_depth_2024', 'q3_archive_depth_2022', 'q3_archive_depth_2019']; answered ['q3_archive_depth_2024', 'q3_archive_depth_2022', 'q3_archive_depth_2019']
- `q4_valid_time_or_run_time_anchored`: planned ['q4_anchor_daily_window', 'q4_anchor_single_day_control', 'q4_anchor_second_site']; answered ['q4_anchor_daily_window', 'q4_anchor_single_day_control', 'q4_anchor_second_site']
- `q5_observable_publication_lag`: planned ['q5_publication_lag_today', 'q5_publication_lag_yesterday']; answered ['q5_publication_lag_today', 'q5_publication_lag_yesterday']
- `q6_values_ever_restated`: planned ['q6_restatement_key_capture', 'q6_restatement_key_capture_older']; answered ['q6_restatement_key_capture', 'q6_restatement_key_capture_older']
- `q7_accepted_model_identifiers`: planned ['q7_model_best_match', 'q7_model_ecmwf_ifs025', 'q7_model_gfs_seamless', 'q7_model_icon_seamless', 'q7_model_meteofrance_seamless']; answered ['q7_model_best_match', 'q7_model_ecmwf_ifs025', 'q7_model_gfs_seamless', 'q7_model_icon_seamless', 'q7_model_meteofrance_seamless']
- `q8_licence_terms_text_verbatim`: planned ['q8_licence_and_error_shape']; answered ['q8_licence_and_error_shape']
- `q9_response_sizes_for_a_body_cap`: planned ['q1_baseline_unkeyed', 'q9_largest_plausible_payload']; answered ['q1_baseline_unkeyed', 'q9_largest_plausible_payload']

## Findings

- None recorded.
