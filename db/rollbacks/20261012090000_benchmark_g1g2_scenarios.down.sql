-- Rollback for 20261012090000_benchmark_g1g2_scenarios.sql:
-- restore the pre-G1/G2 scenario CHECK.
alter table app.simulation_runs drop constraint if exists simulation_runs_scenario_check;
alter table app.simulation_runs add constraint simulation_runs_scenario_check
    check (scenario in ('intentional_dic', 'traffic_gridlock', 'technical_dropout', 'fake_gps', 'gps_jitter',
        'normal_trip', 'route_deviation', 'gps_spoofing', 'driver_stall_cancel'));
