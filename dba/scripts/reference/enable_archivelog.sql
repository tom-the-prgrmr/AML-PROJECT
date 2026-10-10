-- REFERENCE ONLY: never run here (needs SYSDBA on the CDB root and a restart of the database).
-- ARCHIVELOG mode is required for RMAN online backups and point-in-time recovery.
-- The restart steps are SQL*Plus commands, kept as comments so the file stays valid for
-- split_oracle_script:
--   SHUTDOWN IMMEDIATE
--   STARTUP MOUNT
ALTER SYSTEM SET db_recovery_file_dest_size = 10G SCOPE = BOTH
/
ALTER SYSTEM SET db_recovery_file_dest = '/opt/oracle/oradata/fra' SCOPE = BOTH
/
ALTER DATABASE ARCHIVELOG
/
ALTER DATABASE OPEN
/
-- Check afterwards: SELECT log_mode FROM v$database
