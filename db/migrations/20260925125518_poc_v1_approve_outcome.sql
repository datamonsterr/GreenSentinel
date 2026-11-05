-- APPROVE confirms the violation without creating a sanction.
-- Rollback: remove approve rows only after exporting/reviewing them, then restore
-- the previous constraint. Never coerce approval decisions into a different outcome.
alter table app.adjudications drop constraint if exists adjudications_outcome_check;
alter table app.adjudications add constraint adjudications_outcome_check
    check (outcome in ('dismiss', 'approve', 'reject', 'warn', 'fine', 'suspend'));
