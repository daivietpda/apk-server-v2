CREATE TABLE IF NOT EXISTS devices (
  device_id TEXT PRIMARY KEY,
  first_seen INTEGER NOT NULL,
  last_seen INTEGER NOT NULL,
  last_event TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT '',
  phase TEXT NOT NULL DEFAULT '',
  current_package TEXT NOT NULL DEFAULT '',
  version_code TEXT NOT NULL DEFAULT '',
  release_id TEXT NOT NULL DEFAULT '',
  endpoint TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  sdk TEXT NOT NULL DEFAULT '',
  rom_version TEXT NOT NULL DEFAULT '',
  runtime_version TEXT NOT NULL DEFAULT '',
  last_message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_devices_last_seen ON devices(last_seen DESC);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  device_id TEXT NOT NULL,
  received_at INTEGER NOT NULL,
  event_time INTEGER NOT NULL,
  event TEXT NOT NULL,
  run_id TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT '',
  phase TEXT NOT NULL DEFAULT '',
  package_name TEXT NOT NULL DEFAULT '',
  version_code TEXT NOT NULL DEFAULT '',
  release_id TEXT NOT NULL DEFAULT '',
  endpoint TEXT NOT NULL DEFAULT '',
  message TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_received_at ON events(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_event_received ON events(event, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_device_received ON events(device_id, received_at DESC);
