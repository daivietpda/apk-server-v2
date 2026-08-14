import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import test from "node:test";
import { readFile } from "node:fs/promises";
import worker, {
  canonicalEvent, RateLimiter, readBodyLimited, safeEqual, stats,
  takeDistributedRateLimit, validatePayload,
} from "../src/worker.js";

const valid = {
  schemaVersion: "2",
  deviceId: "00000000-0000-4000-8000-aabbccddeeff",
  macAddress: "aa:bb:cc:dd:ee:ff",
  event: "preinstall_registered",
  eventTime: "1785420000",
  runId: "20260730-120000-123",
  state: "installed",
  phase: "preinstall",
  packageName: "",
  versionCode: "",
  releaseId: "v3-test",
  endpoint: "https://apk.daivietpda.com/",
  message: "Initial preinstall completed",
  model: "TV Box",
  sdk: "29",
  romVersion: "build-1",
  runtimeVersion: "2.5-enrollment",
  authVersion: "2",
  nonce: "nonce_for_validation_12345",
  signature: "A".repeat(43),
};

const ingestToken = "x".repeat(32);

function signedPayload(overrides = {}) {
  const payload = {
    ...valid,
    eventTime: String(Math.floor(Date.now() / 1000)),
    runtimeVersion: "2.5-enrollment",
    authVersion: "2",
    nonce: "nonce_for_test_request_123",
    ...overrides,
  };
  payload.signature = createHmac("sha256", ingestToken).update(canonicalEvent(payload)).digest("base64url");
  return payload;
}

function enrollmentPayload(overrides = {}) {
  return signedPayload({
    schemaVersion: "2",
    deviceId: "00000000-0000-4000-8000-aabbccddeeff",
    macAddress: "aa:bb:cc:dd:ee:ff",
    event: "preinstall_registered",
    state: "installed",
    phase: "preinstall",
    packageName: "",
    versionCode: "",
    message: "Initial preinstall completed",
    runtimeVersion: "2.5-enrollment",
    nonce: "nonce_for_enrollment_12345",
    ...overrides,
  });
}

function ingestDatabase() {
  const nonces = new Map();
  const writes = [];
  const batches = [];
  const DB = {
    prepare(sql) {
      let values = [];
      const statement = {
        sql,
        bind(...next) { values = next; return statement; },
        async run() {
          writes.push(sql);
          if (sql.includes("INSERT INTO telemetry_nonces")) {
            if (nonces.has(values[0])) throw new Error("UNIQUE constraint failed");
            nonces.set(values[0], values[1]);
          }
          if (sql.includes("DELETE FROM telemetry_nonces")) {
            for (const [nonce, expiresAt] of nonces) {
              if (expiresAt < values[0]) nonces.delete(nonce);
            }
          }
          return { success: true };
        },
      };
      return statement;
    },
    async batch(statements) {
      batches.push(statements.map((statement) => statement.sql));
      return [];
    },
  };
  return { RATE_LIMITER: rateLimiterBinding(), DB, writes, batches };
}
function rateLimiterBinding(sharedWindows = new Map()) {
  const nonceBuckets = new Map();
  return {
    idFromName(name) { return name; },
    get(objectId) {
      return {
        async fetch(_request, init) {
          const input = JSON.parse(init.body);
          if (input.type === "nonce") {
            const values = nonceBuckets.get(objectId) || new Set();
            if (values.has(input.nonce)) return Response.json({ ok: true, allowed: false });
            values.add(input.nonce);
            nonceBuckets.set(objectId, values);
            return Response.json({ ok: true, allowed: true });
          }
          const { limit, nowMs } = input;
          const previous = sharedWindows.get(objectId);
          const current = previous && nowMs >= previous.windowStart && nowMs - previous.windowStart < 60_000
            ? previous
            : { windowStart: nowMs, count: 0 };
          if (current.count >= limit) return Response.json({ ok: true, allowed: false });
          sharedWindows.set(objectId, { windowStart: current.windowStart, count: current.count + 1 });
          return Response.json({ ok: true, allowed: true });
        },
      };
    },
  };
}

function durableObjectState() {
  const values = new Map();
  return {
    storage: {
      async transaction(callback) {
        return callback({
          async get(key) { return values.get(key); },
          async put(key, value) { values.set(key, value); },
        });
      },
    },
  };
}

function signedRequest(payload) {
  return new Request("https://apk.daivietpda.com/api/v2/telemetry", {
    method: "POST",
    headers: { "X-Telemetry-Key": ingestToken, "Content-Type": "application/json", "CF-Connecting-IP": "192.0.2.10" },
    body: JSON.stringify(payload),
  });
}

test("constant-time comparison returns expected result", () => {
  assert.equal(safeEqual("same-token", "same-token"), true);
  assert.equal(safeEqual("same-token", "other-token"), false);
  assert.equal(safeEqual("short", "longer"), false);
});

test("valid telemetry payload is normalized", () => {
  const item = validatePayload(valid);
  assert.equal(item.deviceId, valid.deviceId);
  assert.equal(item.macAddress, "aa:bb:cc:dd:ee:ff");
});

test("stats groups total devices by normalized model and SDK", async () => {
  const groupRows = [
    { model: 'Leap-S1', sdk: '29', deviceCount: 4 },
    { model: 'Không xác định', sdk: '34', deviceCount: 1 },
  ];
  const env = {
    DB: {
      prepare(sql) {
        const statement = {
          bind() { return statement; },
          async first() {
            if (sql.includes('COUNT(*) AS totalDevices')) {
              return { totalDevices: 5 };
            }
            return { downloads24h: 0, installs24h: 0, failures24h: 0 };
          },
          async all() {
            if (sql.includes('AS deviceCount')) return { results: groupRows };
            if (sql.includes('auth_version AS authVersion')) return { results: [{ authVersion: '2', events: 4 }, { authVersion: 'legacy', events: 1 }] };
            return { results: [] };
          },
        };
        return statement;
      },
    },
  };
  const result = await stats(env);
  assert.equal(result.totalDevices, 5);
  assert.deepEqual(result.deviceGroups, groupRows);
  assert.equal(result.deviceGroups.reduce((sum, item) => sum + item.deviceCount, 0), result.totalDevices);
  assert.equal("onlineDevices" in result, false);
});

test("hardware-style and unexpected fields cannot bypass validation", () => {
  assert.throws(() => validatePayload({ ...valid, event: "device_serial" }), /invalid event/);
  assert.throws(() => validatePayload({ ...valid, endpoint: "https://evil.example/" }), /invalid endpoint/);
  assert.throws(() => validatePayload({ ...valid, message: "bad\nline" }), /invalid message/);
  assert.throws(() => validatePayload({ ...valid, event: "heartbeat" }), /invalid event/);
  assert.throws(() => validatePayload({ ...enrollmentPayload(), macAddress: "not-a-mac" }), /invalid macAddress/);
});

test("health endpoint does not require database or credentials", async () => {
  const response = await worker.fetch(new Request("https://apk.daivietpda.com/api/v2/health"), {});
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { ok: true, service: "apk-server-v2-telemetry" });
});

test("authenticated storage health verifies manifest payloads and helper", async () => {
  const dashboardToken = "d".repeat(32);
  const manifest = {
    schemaVersion: 3,
    releaseId: "v3-storage-test",
    packages: [{
      packageName: "com.example.tv",
      versionCode: 42,
      payload: { path: "payload/com.example.tv-42-aaaaaaaaaaaa.apk", sha256: "a".repeat(64), size: 123 },
    }],
  };
  const bucket = {
    async get(key) {
      assert.equal(key, "manifest.json");
      return { size: 512, uploaded: new Date("2026-07-31T00:00:00Z"), async json() { return manifest; } };
    },
    async head(key) {
      if (key === manifest.packages[0].payload.path) return { size: 123 };
      if (key === "remote-preinstall.jar") return { size: 456 };
      return null;
    },
  };
  const request = new Request("https://apk.daivietpda.com/api/v2/storage-health", {
    headers: { Authorization: `Basic ${Buffer.from(`admin:${dashboardToken}`).toString("base64")}` },
  });
  const response = await worker.fetch(request, { DASHBOARD_TOKEN: dashboardToken, ARTIFACTS: bucket });
  assert.equal(response.status, 200);
  const result = await response.json();
  assert.equal(result.ok, true);
  assert.equal(result.releaseId, "v3-storage-test");
  assert.equal(result.presentObjects, 2);
  assert.equal(result.declaredObjects, 2);
});

test("Worker uses the R2 binding read-only", async () => {
  const source = await readFile(new URL("../src/worker.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /ARTIFACTS\.(?:put|delete|createMultipartUpload)\s*\(/);
});

test("ingest rejects missing secret before touching D1", async () => {
  const request = new Request("https://apk.daivietpda.com/api/v2/telemetry", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(valid),
  });
  const response = await worker.fetch(request, { INGEST_TOKEN: "x".repeat(32) });
  assert.equal(response.status, 401);
});

test("signed telemetry replays are harmless insert-only requests", async () => {
  const env = { INGEST_TOKEN: ingestToken, ...ingestDatabase() };
  const payload = signedPayload();
  const first = await worker.fetch(signedRequest(payload), env);
  assert.equal(first.status, 202);
  const replay = await worker.fetch(signedRequest(payload), env);
  assert.equal(replay.status, 202);
  assert.equal(env.writes.some((sql) => /UPDATE|INSERT INTO events|telemetry_nonces/.test(sql)), false);
  assert.ok(env.writes.every((sql) => sql.includes("ON CONFLICT DO NOTHING")));
});


test("initial preinstall enrollment stores MAC with no event or nonce D1 writes", async () => {
  const database = ingestDatabase();
  const env = { INGEST_TOKEN: ingestToken, ...database };
  const payload = enrollmentPayload();
  const response = await worker.fetch(signedRequest(payload), env);
  assert.equal(response.status, 202);
  assert.equal(database.writes.some((sql) => sql.includes("telemetry_nonces")), false);
  assert.equal(database.writes.some((sql) => sql.includes("INSERT INTO events")), false);
  assert.match(database.writes[0], /mac_address/);
  assert.match(database.writes[0], /ON CONFLICT DO NOTHING/);
  const replay = await worker.fetch(signedRequest(payload), env);
  assert.equal(replay.status, 202);
});

test("legacy heartbeat is rejected before D1", async () => {
  const database = ingestDatabase();
  const payload = { ...enrollmentPayload(), schemaVersion: "1", event: "heartbeat" };
  const response = await worker.fetch(signedRequest(payload), { INGEST_TOKEN: ingestToken, ...database });
  assert.equal(response.status, 400);
  assert.deepEqual(database.writes, []);
});

test("forged signature and stale timestamp are rejected before D1 writes", async () => {
  const forged = signedPayload();
  forged.signature = "A".repeat(43);
  const stale = signedPayload({ eventTime: String(Math.floor(Date.now() / 1000) - 601) });
  const forgedResponse = await worker.fetch(signedRequest(forged), { INGEST_TOKEN: ingestToken, ...ingestDatabase() });
  const staleResponse = await worker.fetch(signedRequest(stale), { INGEST_TOKEN: ingestToken, ...ingestDatabase() });
  assert.equal(forgedResponse.status, 400);
  assert.equal(staleResponse.status, 400);
});

test("Durable Object rate limit is atomic and resets only after its window", async () => {
  const limiter = new RateLimiter(durableObjectState());
  const request = (nowMs) => new Request("https://rate-limit/check", {
    method: "POST",
    body: JSON.stringify({ limit: 1, nowMs }),
  });
  assert.deepEqual(await (await limiter.fetch(request(1_000))).json(), { ok: true, allowed: true });
  assert.deepEqual(await (await limiter.fetch(request(1_001))).json(), { ok: true, allowed: false });
  assert.deepEqual(await (await limiter.fetch(request(61_000))).json(), { ok: true, allowed: true });
});

test("distributed rate limit spans simulated Worker isolates without exposing raw identity", async () => {
  const sharedWindows = new Map();
  const firstIsolate = { RATE_LIMITER: rateLimiterBinding(sharedWindows) };
  const secondIsolate = { RATE_LIMITER: rateLimiterBinding(sharedWindows) };
  assert.equal(await takeDistributedRateLimit(firstIsolate, "ip", "192.0.2.77", 1, 1_000), true);
  assert.equal(await takeDistributedRateLimit(secondIsolate, "ip", "192.0.2.77", 1, 1_001), false);
  assert.equal([...sharedWindows.keys()].some((key) => key.includes("192.0.2.77")), false);
});

test("denied IP limit rejects telemetry even when the shared credential remains below its limit", async () => {
  const env = { INGEST_TOKEN: ingestToken, ...ingestDatabase() };
  for (let index = 0; index < 60; index += 1) {
    const deviceSuffix = index.toString(16).padStart(12, "0");
    const response = await worker.fetch(signedRequest(signedPayload({
      deviceId: "123e4567-e89b-12d3-a456-" + deviceSuffix,
      macAddress: "",
      nonce: "nonce_for_rate_limit_" + index.toString().padStart(3, "0"),
    })), env);
    assert.equal(response.status, 202);
  }
  const blocked = await worker.fetch(signedRequest(signedPayload({
    deviceId: "123e4567-e89b-12d3-a456-ffffffffffff",
    macAddress: "",
    nonce: "nonce_for_rate_limit_blocked",
  })), env);
  assert.equal(blocked.status, 429);
});

function chunkedRequest(chunks, headers = {}) {
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Request("https://apk.daivietpda.com/api/v2/telemetry", {
    method: "POST",
    headers,
    body: stream,
    duplex: "half",
  });
}

test("stream reader accepts exactly MAX_BODY_BYTES without Content-Length", async () => {
  const raw = await readBodyLimited(chunkedRequest(["a".repeat(2048), "b".repeat(2048)]));
  assert.equal(raw.length, 4096);
});

test("stream reader stops oversized chunked body before D1", async () => {
  const request = chunkedRequest(["a".repeat(4096), "b"], { "X-Telemetry-Key": "x".repeat(32) });
  const response = await worker.fetch(request, { INGEST_TOKEN: "x".repeat(32), ...ingestDatabase() });
  assert.equal(response.status, 413);
  assert.deepEqual(await response.json(), { ok: false, error: "payload too large" });
});

test("stream reader rejects oversized declared Content-Length", async () => {
  await assert.rejects(
    () => readBodyLimited(chunkedRequest(["{}"], { "Content-Length": "4097" })),
    RangeError,
  );
});
