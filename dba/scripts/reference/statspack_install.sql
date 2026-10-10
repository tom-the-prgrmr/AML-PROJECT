-- REFERENCE ONLY: never run here. Statspack is the no-extra-licence alternative to AWR.
-- Run as SYSDBA in the pluggable database. The installer is a SQL*Plus script, so it is kept in a
-- comment to leave this file valid for split_oracle_script:
--   @?/rdbms/admin/spcreate.sql
--   -- afterwards, as PERFSTAT:
--   EXEC STATSPACK.SNAP
--   @?/rdbms/admin/spreport.sql
SELECT snap_id, snap_time FROM stats$snapshot ORDER BY snap_id DESC FETCH FIRST 10 ROWS ONLY
/
