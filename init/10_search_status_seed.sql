INSERT INTO search_status(status_code, status_label, from_status, to_status, transition_allowed, is_terminal, semantic, sla_scalar, bucket)
VALUES
  ('PENDING','Pending',NULL,'IN_PROGRESS',TRUE,FALSE,'ACTIVE',1.00,'ACTIVE'),
  ('IN_PROGRESS','In Progress','PENDING','IN_PROGRESS',TRUE,FALSE,'ACTIVE',1.00,'ACTIVE'),
  ('WAITING_VENDOR','Waiting Vendor','IN_PROGRESS','WAITING_VENDOR',TRUE,FALSE,'WAITING',1.20,'WAITING'),
  ('COMPLETE','Complete','IN_PROGRESS','COMPLETE',TRUE,TRUE,'DONE',1.00,'DONE'),
  ('CANCELLED','Cancelled',NULL,'CANCELLED',TRUE,TRUE,'DONE',1.00,'DONE'),
  ('REOPENED','Reopened',NULL,'IN_PROGRESS',TRUE,FALSE,'ACTIVE',1.50,'ACTIVE')
ON CONFLICT (status_code) DO NOTHING;
