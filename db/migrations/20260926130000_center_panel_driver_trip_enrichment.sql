-- Migration: Center panel driver and trip enrichment
-- Adds avatar, metrics (rating, acceptance_rate, cancellation_rate, total_trips) to drivers
-- Adds match_type ('now', 'auto'), fare_amount_vnd, and addresses to trips
-- Ensures status supports completed, picking up, coming
set search_path = app, extensions, public;

-- 1. Enrich drivers with avatar and operational metrics
alter table app.drivers
    add column if not exists avatar_url text,
    add column if not exists rating numeric(3,2) default 4.85 check (rating is null or (rating >= 1.0 and rating <= 5.0)),
    add column if not exists acceptance_rate numeric(5,2) default 92.5 check (acceptance_rate is null or (acceptance_rate >= 0 and acceptance_rate <= 100)),
    add column if not exists cancellation_rate numeric(5,2) default 2.1 check (cancellation_rate is null or (cancellation_rate >= 0 and cancellation_rate <= 100)),
    add column if not exists total_trips integer default 1250 check (total_trips is null or total_trips >= 0);

-- 2. Enrich trips with match_type ('now', 'auto') and fare_amount_vnd
alter table app.trips
    add column if not exists match_type text default 'auto' check (match_type is null or match_type in ('now', 'auto')),
    add column if not exists fare_amount_vnd integer check (fare_amount_vnd is null or fare_amount_vnd >= 0);

-- 3. Relax/expand trips status check constraint to support 'coming' and 'picking_up' alongside standard states
alter table app.trips drop constraint if exists trips_status_check;
alter table app.trips add constraint trips_status_check
    check (status in ('requested', 'matched', 'driver_arriving', 'in_progress', 'completed', 'cancelled', 'coming', 'picking_up'));

-- 4. Backfill synthetic/random metrics and avatars for existing drivers
update app.drivers
set
    avatar_url = coalesce(avatar_url, 'https://api.dicebear.com/7.x/bottts/svg?seed=' || coalesce(external_ref, id::text)),
    rating = coalesce(rating, round((4.65 + (('x' || substring(md5(id::text || 'rating'), 1, 4))::bit(16)::int % 33)::numeric / 100.0), 2)),
    acceptance_rate = coalesce(acceptance_rate, round((90.0 + (('x' || substring(md5(id::text || 'acceptance'), 1, 4))::bit(16)::int % 90)::numeric / 10.0), 1)),
    cancellation_rate = coalesce(cancellation_rate, round((0.8 + (('x' || substring(md5(id::text || 'cancellation'), 1, 4))::bit(16)::int % 25)::numeric / 10.0), 1)),
    total_trips = coalesce(total_trips, 550 + (('x' || substring(md5(id::text || 'trips'), 1, 4))::bit(16)::int % 2400)),
    profile_provenance = jsonb_set(
        jsonb_set(
            jsonb_set(
                profile_provenance,
                '{rating}',
                to_jsonb(round((4.65 + (('x' || substring(md5(id::text || 'rating'), 1, 4))::bit(16)::int % 33)::numeric / 100.0), 2))
            ),
            '{acceptance_rate}',
            to_jsonb(round((90.0 + (('x' || substring(md5(id::text || 'acceptance'), 1, 4))::bit(16)::int % 90)::numeric / 10.0), 1))
        ),
        '{cancellation_rate}',
        to_jsonb(round((0.8 + (('x' || substring(md5(id::text || 'cancellation'), 1, 4))::bit(16)::int % 25)::numeric / 10.0), 1))
    )
where avatar_url is null or rating is null or total_trips is null;

-- 5. Backfill match_type and fare_amount_vnd for existing trips
update app.trips
set
    match_type = case
        when (('x' || substring(md5(id::text), 1, 2))::bit(8)::int % 2) = 0 then 'now'
        else 'auto'
    end,
    fare_amount_vnd = coalesce(fare_amount_vnd, 45000 + (('x' || substring(md5(id::text || 'fare'), 1, 4))::bit(16)::int % 28) * 10000)
where match_type is null or fare_amount_vnd is null;

-- 6. Backfill missing pickup and dropoff addresses for trips with NULL addresses
update app.trips
set
    pickup_address = case (('x' || substring(md5(id::text || 'p'), 1, 2))::bit(8)::int % 6)
        when 0 then 'Sân bay Quốc tế Nội Bài, Sóc Sơn, Hà Nội'
        when 1 then 'Hồ Hoàn Kiếm, Tràng Tiền, Hoàn Kiếm, Hà Nội'
        when 2 then 'Vinhomes Ocean Park, Đa Tốn, Gia Lâm, Hà Nội'
        when 3 then 'Vincom Center Metropolis, 29 Liễu Giai, Ba Đình, Hà Nội'
        when 4 then 'Bến xe Mỹ Đình, Phạm Hùng, Nam Từ Liêm, Hà Nội'
        else 'Đại học VinUni, Vinhomes Ocean Park, Gia Lâm, Hà Nội'
    end,
    dropoff_address = case (('x' || substring(md5(id::text || 'd'), 1, 2))::bit(8)::int % 6)
        when 0 then 'Keangnam Landmark 72, Phạm Hùng, Nam Từ Liêm, Hà Nội'
        when 1 then 'Lotte Center Hà Nội, 54 Liễu Giai, Ba Đình, Hà Nội'
        when 2 then 'Times City, 458 Minh Khai, Hai Bà Trưng, Hà Nội'
        when 3 then 'Royal City, 72A Nguyễn Trãi, Thanh Xuân, Hà Nội'
        when 4 then 'Ga Hà Nội, 120 Lê Duẩn, Hoàn Kiếm, Hà Nội'
        else 'Bệnh viện Bạch Mai, 78 Giải Phóng, Đống Đa, Hà Nội'
    end,
    district = case (('x' || substring(md5(id::text || 'dist'), 1, 2))::bit(8)::int % 4)
        when 0 then 'Hoàn Kiếm'
        when 1 then 'Ba Đình'
        when 2 then 'Nam Từ Liêm'
        else 'Gia Lâm'
    end
where pickup_address is null or dropoff_address is null;

-- 7. Ensure diverse trip statuses representing completed, picking up, coming
update app.trips
set status = case (('x' || substring(md5(id::text || 'status'), 1, 2))::bit(8)::int % 5)
    when 0 then 'completed'
    when 1 then 'picking_up'
    when 2 then 'coming'
    when 3 then 'in_progress'
    else status
end
where status in ('requested', 'matched');

-- Set a portion of active trips to coming and picking_up for clear UI demonstration
update app.trips
set status = 'coming'
where id in (select id from app.trips where status in ('in_progress', 'cancelled') limit 8);

update app.trips
set status = 'picking_up'
where id in (select id from app.trips where status in ('in_progress', 'cancelled') and status != 'coming' limit 8);

-- 8. Ensure indices
create index if not exists idx_drivers_rating on app.drivers (rating);
create index if not exists idx_trips_match_type on app.trips (match_type);
create index if not exists idx_trips_status on app.trips (status);
