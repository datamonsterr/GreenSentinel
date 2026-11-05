set search_path = app, extensions, public;

alter table if exists preset_batch_trips
    add column if not exists driver_id uuid references drivers(id) on delete set null,
    add column if not exists driver_name text;

create index if not exists idx_preset_batch_trips_driver on preset_batch_trips(driver_id);
