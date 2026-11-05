drop policy if exists driver_admission_sanctions_org_read on app.driver_admission_sanctions;
drop table if exists app.driver_admission_sanctions;
delete from app.policy_versions where version = 'greensentinel-demo-admission-v1' and is_demo_policy = true;
