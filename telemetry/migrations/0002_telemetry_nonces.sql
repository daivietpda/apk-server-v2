CREATE TABLE IF NOT EXISTS telemetry_nonces (
  nonce TEXT PRIMARY KEY NOT NULL,
  expires_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_telemetry_nonces_expires_at
  ON telemetry_nonces(expires_at);
