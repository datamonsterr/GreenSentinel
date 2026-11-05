-- Rollback for 20261007090000_benchmark_schema_sync (issue #248).
-- Restores pre-#248 nullability and CHECKs. Tester isolation COMMENTs are kept
-- (documentation only, harmless to retain).

-- Guard: restoring NOT NULL fails on rows that gained nulls under #248.
-- Fail fast with a clear error instead of a cryptic constraint violation.
do $$
declare
    n_cov bigint;
    n_gap bigint;
begin
    select count(*) into n_cov from app.feature_sets where telemetry_coverage is null;
    select count(*) into n_gap from app.feature_sets where max_gap_s is null;
    if n_cov > 0 or n_gap > 0 then
        raise exception 'rollback blocked: app.feature_sets holds % null telemetry_coverage and % null max_gap_s rows; backfill or delete them before restoring NOT NULL', n_cov, n_gap;
    end if;
end;
$$;

alter table app.feature_sets alter column telemetry_coverage set not null;
alter table app.feature_sets alter column max_gap_s set not null;

alter table app.simulation_labels drop constraint if exists simulation_labels_expected_category_check;
alter table app.simulation_labels add constraint simulation_labels_expected_category_check
    check (expected_category in ('ERR-02', 'ERR-05', 'no_violation', 'insufficient_evidence'));

alter table app.simulation_runs drop constraint if exists simulation_runs_scenario_check;
alter table app.simulation_runs add constraint simulation_runs_scenario_check
    check (scenario in ('intentional_dic', 'traffic_gridlock', 'technical_dropout', 'fake_gps', 'gps_jitter'));
