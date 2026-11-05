-- Migration: 20261003220000_rbac_roles_manager_and_fraud_analyst.sql
-- Purpose: Support fraud_analyst, driver, and manager roles in app.principal_roles and reject outcome in adjudications.

set search_path = app, extensions, public;

-- 1. Update app.principal_roles check constraint to include 'fraud_analyst' and 'manager'
alter table app.principal_roles drop constraint if exists principal_roles_role_check;
alter table app.principal_roles add constraint principal_roles_role_check
    check (role in ('analyst', 'fraud_analyst', 'senior_analyst', 'demo_operator', 'admin', 'manager', 'driver'));

-- 2. Update app.adjudications outcome check constraint to include 'reject'
alter table app.adjudications drop constraint if exists adjudications_outcome_check;
alter table app.adjudications add constraint adjudications_outcome_check
    check (outcome in ('dismiss', 'approve', 'reject', 'warn', 'fine', 'suspend'));

-- 3. Update app.case_agent_messages role check constraint to include 'manager'
alter table app.case_agent_messages drop constraint if exists case_agent_messages_role_check;
alter table app.case_agent_messages add constraint case_agent_messages_role_check
    check (role in ('user', 'assistant', 'analyst', 'driver', 'driver_agent', 'manager', 'fraud_analyst'));
