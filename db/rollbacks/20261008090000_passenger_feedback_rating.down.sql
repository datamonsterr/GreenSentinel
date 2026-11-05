-- Rollback for 20261008090000_passenger_feedback_rating (issue #270).
-- Drops the rating column added by the forward migration.
alter table app.passenger_feedback drop column if exists rating_smallint;
