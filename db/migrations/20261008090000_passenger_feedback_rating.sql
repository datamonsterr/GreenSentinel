-- Issue #270: passenger_feedback star rating (1-5, null allowed).
-- Rollback: db/rollbacks/20261008090000_passenger_feedback_rating.down.sql
--
-- Vanilla-Postgres safe: smallint + CHECK only. NULL passes the CHECK, so
-- unrated feedback stays null without a NOT VALID dance.

alter table app.passenger_feedback
    add column rating_smallint smallint check (rating_smallint between 1 and 5);
