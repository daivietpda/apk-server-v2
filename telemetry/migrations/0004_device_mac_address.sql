ALTER TABLE devices ADD COLUMN mac_address TEXT NOT NULL DEFAULT '';

DROP INDEX IF EXISTS idx_devices_last_seen;

CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_mac_address
  ON devices(mac_address)
  WHERE mac_address <> '';
