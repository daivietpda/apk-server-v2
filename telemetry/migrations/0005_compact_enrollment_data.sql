CREATE TABLE devices_enrollment_compact (
  device_id TEXT PRIMARY KEY,
  first_seen INTEGER NOT NULL,
  release_id TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  sdk TEXT NOT NULL DEFAULT '',
  rom_version TEXT NOT NULL DEFAULT '',
  runtime_version TEXT NOT NULL DEFAULT '',
  mac_address TEXT NOT NULL DEFAULT ''
);

INSERT INTO devices_enrollment_compact (
  device_id, first_seen, release_id, model, sdk, rom_version, runtime_version, mac_address
)
SELECT device_id, first_seen, release_id, model, sdk, rom_version, runtime_version, mac_address
FROM devices;

DROP TABLE devices;
ALTER TABLE devices_enrollment_compact RENAME TO devices;

CREATE UNIQUE INDEX idx_devices_mac_address
  ON devices(mac_address)
  WHERE mac_address <> '';

DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS telemetry_nonces;
