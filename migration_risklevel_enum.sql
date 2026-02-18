-- Detect current ENUM labels in production
SELECT t.typname AS enum_name, e.enumlabel AS enum_value, e.enumsortorder
FROM pg_type t
JOIN pg_enum e ON t.oid = e.enumtypid
WHERE t.typname = 'risklevel'
ORDER BY e.enumsortorder;

-- Option A (recommended): safely normalize existing lowercase enum labels to uppercase.
-- This preserves type OID and avoids touching table data.
ALTER TYPE risklevel RENAME VALUE 'low' TO 'LOW';
ALTER TYPE risklevel RENAME VALUE 'medium' TO 'MEDIUM';
ALTER TYPE risklevel RENAME VALUE 'high' TO 'HIGH';
ALTER TYPE risklevel RENAME VALUE 'critical' TO 'CRITICAL';

-- Option B (fallback for very old Postgres versions without RENAME VALUE): recreate type safely.
-- BEGIN;
-- ALTER TYPE risklevel RENAME TO risklevel_old;
-- CREATE TYPE risklevel AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL');
-- ALTER TABLE messages
--   ALTER COLUMN risk_level TYPE risklevel
--   USING upper(risk_level::text)::risklevel;
-- ALTER TABLE violations
--   ALTER COLUMN severity TYPE risklevel
--   USING upper(severity::text)::risklevel;
-- DROP TYPE risklevel_old;
-- COMMIT;
