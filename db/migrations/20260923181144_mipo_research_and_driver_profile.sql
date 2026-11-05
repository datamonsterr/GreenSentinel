set search_path = app, extensions, public;

alter table app.drivers
    add column if not exists display_name text,
    add column if not exists birth_date date,
    add column if not exists profile_provenance jsonb not null default '{}'::jsonb;

alter table app.telemetry_points
    add column if not exists anomaly_type text check (anomaly_type is null or anomaly_type in (
        'gps_jitter', 'gps_dropout', 'mock_location', 'route_deviation', 'prolonged_stop'
    )),
    add column if not exists anomaly_score double precision check (
        anomaly_score is null or anomaly_score between 0 and 1
    );

alter table app.route_snapshots
    add column if not exists leg text not null default 'destination'
        check (leg in ('pickup', 'destination'));

create unique index if not exists uq_route_snapshot_assignment_leg
    on app.route_snapshots (assignment_id, leg);

create index if not exists idx_driver_birth_date on app.drivers (birth_date);
create index if not exists idx_telemetry_anomaly on app.telemetry_points (assignment_id, occurred_at)
    where anomaly_type is not null;

create table if not exists app.research_trajectories (
    id uuid primary key default gen_random_uuid(),
    source text not null,
    source_revision text not null,
    source_sha256 text not null,
    source_row integer not null,
    variant text not null check (variant in ('normal', 'outlier')),
    label text not null,
    points_xy jsonb not null,
    point_count integer not null check (point_count > 0),
    imported_at timestamptz not null default now(),
    unique (source, source_revision, source_row)
);

create index if not exists idx_research_trajectories_source
    on app.research_trajectories (source, source_revision, variant);

alter function app.reject_mutation() set search_path = app, extensions, pg_catalog;
