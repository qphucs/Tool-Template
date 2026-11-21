-- Run on the trusted license-service database (Neon), never from the desktop client.
CREATE TABLE IF NOT EXISTS app_licenses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    license_hash CHAR(64) UNIQUE NOT NULL,
    customer_name TEXT NOT NULL DEFAULT '',
    bound_device_hash CHAR(64),
    bound_device_name TEXT,
    bound_device_os TEXT,
    device_bound_at TIMESTAMPTZ,
    plan TEXT NOT NULL DEFAULT 'standard',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_validated_at TIMESTAMPTZ
);

-- Safe migration for databases created with the earlier schema.
ALTER TABLE app_licenses ADD COLUMN IF NOT EXISTS id UUID;
ALTER TABLE app_licenses ADD COLUMN IF NOT EXISTS customer_name TEXT NOT NULL DEFAULT '';
ALTER TABLE app_licenses ADD COLUMN IF NOT EXISTS bound_device_hash CHAR(64);
ALTER TABLE app_licenses ADD COLUMN IF NOT EXISTS bound_device_name TEXT;
ALTER TABLE app_licenses ADD COLUMN IF NOT EXISTS bound_device_os TEXT;
ALTER TABLE app_licenses ADD COLUMN IF NOT EXISTS device_bound_at TIMESTAMPTZ;
UPDATE app_licenses SET id = gen_random_uuid() WHERE id IS NULL;
ALTER TABLE app_licenses ALTER COLUMN id SET DEFAULT gen_random_uuid();
ALTER TABLE app_licenses ALTER COLUMN id SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS app_licenses_id_idx ON app_licenses (id);

CREATE INDEX IF NOT EXISTS app_licenses_active_expiry_idx
    ON app_licenses (is_active, expires_at);
