set search_path = app, extensions, public;

drop index if exists idx_preset_batch_trips_driver;

alter table if exists preset_batch_trips
    drop column if exists driver_id,
    drop column if exists driver_name;
