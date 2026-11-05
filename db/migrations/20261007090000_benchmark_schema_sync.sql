-- Issue #248 (schema-sync part): align DDL with DATA_MODEL null/C CHECK semantics.
-- Rollback: db/rollbacks/20261007090000_benchmark_schema_sync.down.sql
--
-- 1. feature_sets.telemetry_coverage and max_gap_s become NULLABLE.
--    DATA_MODEL: "Null is not zero". PR #43 writes 0 + flag today; nullable
--    columns let missingness stay null instead of coerced zero. Data preserved
--    (ALTER COLUMN only relaxes nullability; existing 0 values untouched).
-- 2. Extend CHECKs, keeping original auto-generated constraint names from 0001:
--    simulation_labels_expected_category_check + ERR-01/ERR-03/ERR-04;
--    simulation_runs_scenario_check + normal_trip/route_deviation/
--    gps_spoofing/driver_stall_cancel (old scenario names kept).
-- 3. Tester test_* tables are NOT moved: decision 2026-10-04 keeps them
--    isolated where they live; COMMENTs below record that decision.

-- 1. Nullable coverage/gap (range CHECKs stay: non-null values still bounded).
alter table app.feature_sets alter column telemetry_coverage drop not null;
alter table app.feature_sets alter column max_gap_s drop not null;

-- 2a. simulation_labels: full ERR taxonomy for extension.
alter table app.simulation_labels drop constraint if exists simulation_labels_expected_category_check;
alter table app.simulation_labels add constraint simulation_labels_expected_category_check
    check (expected_category in ('ERR-01', 'ERR-02', 'ERR-03', 'ERR-04', 'ERR-05', 'no_violation', 'insufficient_evidence'));

-- 2b. simulation_runs: new generator scenarios, old names kept.
alter table app.simulation_runs drop constraint if exists simulation_runs_scenario_check;
alter table app.simulation_runs add constraint simulation_runs_scenario_check
    check (scenario in ('intentional_dic', 'traffic_gridlock', 'technical_dropout', 'fake_gps', 'gps_jitter',
        'normal_trip', 'route_deviation', 'gps_spoofing', 'driver_stall_cancel'));

-- 3. Isolation decision 2026-10-04: test_* tables stay where they are
-- (public schema per the isolation decision); moving live tables out of scope.
-- Guarded DO block: comments whichever schema the tables resolve in.
do $$
declare
    t text;
    q text;
begin
    foreach t in array array['test_plans', 'test_definition_revisions', 'test_runs',
        'test_controls', 'test_samples', 'test_events', 'test_messages',
        'test_notifications', 'test_outbox', 'test_idempotency_keys']
    loop
        if to_regclass(concat('public.', t)) is not null then
            q := format('comment on table public.%I is %L', t,
                'Tester isolation table. Decision 2026-10-04: lives in public schema, NOT moved into app schema (out of scope for #248).');
            execute q;
        elsif to_regclass(concat('app.', t)) is not null then
            q := format('comment on table app.%I is %L', t,
                'Tester isolation table. Decision 2026-10-04: NOT moved into app schema (out of scope for #248).');
            execute q;
        end if;
    end loop;
end;
$$;
