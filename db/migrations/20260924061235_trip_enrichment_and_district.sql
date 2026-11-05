set search_path = app, extensions, public;

alter table app.trips
    add column if not exists pickup_address text,
    add column if not exists dropoff_address text,
    add column if not exists district text;

alter table app.passengers
    add column if not exists display_name text,
    add column if not exists phone_number text;

alter table app.vehicles
    add column if not exists model text;

create index if not exists idx_trips_district on app.trips (district);
