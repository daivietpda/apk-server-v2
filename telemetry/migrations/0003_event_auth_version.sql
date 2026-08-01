ALTER TABLE events ADD COLUMN auth_version TEXT NOT NULL DEFAULT 'legacy';
CREATE INDEX IF NOT EXISTS idx_events_auth_version_received_at
  ON events(auth_version, received_at DESC);
