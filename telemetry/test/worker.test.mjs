import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import worker, { safeEqual, validatePayload } from "../src/worker.js";

const valid = {
  schemaVersion: "1",
  deviceId: "123e4567-e89b-12d3-a456-426614174000",
  event: "install_completed",
  eventTime: "1785420000",
  runId: "20260730-120000-123",
  state: "running",
  phase: "install",
  packageName: "com.example.tv",
  versionCode: "42",
  releaseId: "v3-test",
  endpoint: "https://apk.daivietpda.com/",
  message: "Installed",
  model: "TV Box",
  sdk: "29",
  romVersion: "build-1",
  runtimeVersion: "2.2-telemetry1",
};

test("constant-time comparison returns expected result", () => {
  assert.equal(safeEqual("same-token", "same-token"), true);
  assert.equal(safeEqual("same-token", "other-token"), false);
  assert.equal(safeEqual("short", "longer"), false);
});

test("valid telemetry payload is normalized", () => {
  const item = validatePayload(valid);
  assert.equal(item.deviceId, valid.deviceId);
  assert.equal(item.packageName, "com.example.tv");
});

test("hardware-style and unexpected fields cannot bypass validation", () => {
  assert.throws(() => validatePayload({ ...valid, event: "device_serial" }), /invalid event/);
  assert.throws(() => validatePayload({ ...valid, endpoint: "https://evil.example/" }), /invalid endpoint/);
  assert.throws(() => validatePayload({ ...valid, message: "bad\nline" }), /invalid message/);
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
