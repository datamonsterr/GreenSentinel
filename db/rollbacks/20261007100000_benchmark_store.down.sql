-- Rollback for 20261007100000_benchmark_store (issue #251).
-- Drops in reverse dependency order: predictions -> runs -> datasets.
drop index if exists app.idx_benchmark_predictions_run_label;
drop index if exists app.idx_benchmark_predictions_run_trip;
drop table if exists app.benchmark_predictions;
drop table if exists app.benchmark_runs;
drop table if exists app.benchmark_datasets;
