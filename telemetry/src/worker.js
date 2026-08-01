const ALLOWED_EVENTS = new Set([
  "heartbeat", "run_started", "manifest_loaded", "manifest_failed",
  "download_started", "download_completed", "download_failed",
  "install_started", "install_completed", "install_failed",
  "uninstall_started", "uninstall_completed", "uninstall_failed",
  "run_completed", "run_failed",
]);
const ALLOWED_ENDPOINTS = new Set([
  "", "failover-auto", "https://apk.daivietpda.com/",
  "https://daivietpda.github.io/apk-server-v2/",
]);
const MAX_BODY_BYTES = 4096;
const ONLINE_WINDOW_SECONDS = 600;
const EVENT_RETENTION_DAYS = 90;
const STORAGE_CACHE_SECONDS = 120;
const MAX_MANIFEST_BYTES = 2 * 1024 * 1024;
const AUTH_VERSION = "2";
const MAX_EVENT_SKEW_SECONDS = 600;
const NONCE_TTL_SECONDS = 900;
const NONCE_EXPIRY_MARGIN_SECONDS = 60;
const LEGACY_AUTH_MODES = new Set(["allow", "observe", "reject"]);
const RATE_WINDOW_MS = 60_000;
const IP_RATE_LIMIT = 60;
const DEVICE_RATE_LIMIT = 30;
// All ROMs currently share this credential, so this limit is deliberately high.
const CREDENTIAL_RATE_LIMIT = 10_000;
let cachedStorageHealth = null;
const SECURITY_HEADERS = {
  "Cache-Control": "no-store",
  "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
};

export function safeEqual(left, right) {
  if (typeof left !== "string" || typeof right !== "string") return false;
  let mismatch = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    mismatch |= (left.charCodeAt(index % Math.max(1, left.length)) || 0)
      ^ (right.charCodeAt(index % Math.max(1, right.length)) || 0);
  }
  return mismatch === 0;
}

function cleanString(value, name, maxLength, emptyAllowed = true) {
  if (typeof value !== "string" || value.length > maxLength || (!emptyAllowed && value.length === 0)
      || /[\u0000-\u001f\u007f]/.test(value)) {
    throw new Error(`invalid ${name}`);
  }
  return value;
}

function cleanDigits(value, name, maxLength, emptyAllowed = true) {
  cleanString(value, name, maxLength, emptyAllowed);
  if (value !== "" && !/^[0-9]+$/.test(value)) throw new Error(`invalid ${name}`);
  return value;
}

export function validatePayload(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("invalid JSON object");
  if (input.schemaVersion !== "1") throw new Error("unsupported schemaVersion");
  const deviceId = cleanString(input.deviceId, "deviceId", 36, false).toLowerCase();
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(deviceId)) {
    throw new Error("invalid deviceId");
  }
  const event = cleanString(input.event, "event", 32, false);
  if (!ALLOWED_EVENTS.has(event)) throw new Error("invalid event");
  const endpoint = cleanString(input.endpoint, "endpoint", 160);
  if (!ALLOWED_ENDPOINTS.has(endpoint)) throw new Error("invalid endpoint");
  const suppliedAuthFields = [input.authVersion, input.nonce, input.signature]
    .filter((value) => value !== undefined).length;
  if (suppliedAuthFields !== 0 && suppliedAuthFields !== 3) throw new Error("incomplete authentication fields");
  const authenticated = suppliedAuthFields === 3;
  if (authenticated) {
    if (input.authVersion !== AUTH_VERSION) throw new Error("unsupported authentication version");
    if (typeof input.nonce !== "string" || !/^[A-Za-z0-9_-]{22,64}$/.test(input.nonce)) throw new Error("invalid nonce");
    if (typeof input.signature !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(input.signature)) throw new Error("invalid signature");
  }
  return {
    deviceId,
    event,
    eventTime: cleanDigits(input.eventTime, "eventTime", 13, false),
    runId: cleanString(input.runId, "runId", 64),
    state: cleanString(input.state, "state", 24),
    phase: cleanString(input.phase, "phase", 32),
    packageName: cleanString(input.packageName, "packageName", 160),
    versionCode: cleanDigits(input.versionCode, "versionCode", 20),
    releaseId: cleanString(input.releaseId, "releaseId", 96),
    endpoint,
    message: cleanString(input.message, "message", 240),
    model: cleanString(input.model, "model", 96),
    sdk: cleanDigits(input.sdk, "sdk", 3),
    romVersion: cleanString(input.romVersion, "romVersion", 128),
    runtimeVersion: cleanString(input.runtimeVersion, "runtimeVersion", 40, false),
    authVersion: authenticated ? AUTH_VERSION : "",
    nonce: authenticated ? input.nonce : "",
    signature: authenticated ? input.signature : "",
  };
}

export function canonicalEvent(item) {
  return [
    "apk-server-v2-telemetry", AUTH_VERSION, item.deviceId, item.event, item.eventTime, item.runId,
    item.state, item.phase, item.packageName, item.versionCode, item.releaseId, item.endpoint,
    item.message, item.model, item.sdk, item.romVersion, item.runtimeVersion, item.nonce,
  ].join("\n");
}

function base64UrlBytes(value) {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("invalid signature");
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
  const binary = atob(padded);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

export async function verifyRequestAuthentication(item, token, nowSeconds) {
  if (!item.authVersion) return { authenticated: false };
  const eventTime = Number(item.eventTime);
  if (!Number.isSafeInteger(eventTime) || Math.abs(nowSeconds - eventTime) > MAX_EVENT_SKEW_SECONDS) {
    throw new Error("event timestamp is outside the allowed window");
  }
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(token), { name: "HMAC", hash: "SHA-256" }, false, ["verify"],
  );
  const verified = await crypto.subtle.verify(
    "HMAC", key, base64UrlBytes(item.signature), new TextEncoder().encode(canonicalEvent(item)),
  );
  if (!verified) throw new Error("invalid request signature");
  return { authenticated: true };
}

export function nonceExpirySeconds(eventTime, nowSeconds) {
  if (!Number.isSafeInteger(eventTime) || !Number.isSafeInteger(nowSeconds)) {
    throw new Error("invalid nonce expiry timestamp");
  }
  return Math.max(
    nowSeconds + NONCE_TTL_SECONDS,
    Math.max(nowSeconds, eventTime) + MAX_EVENT_SKEW_SECONDS + NONCE_EXPIRY_MARGIN_SECONDS,
  );
}

export function legacyAuthMode(env) {
  const mode = env.LEGACY_AUTH_MODE || "allow";
  if (!LEGACY_AUTH_MODES.has(mode)) throw new Error("invalid LEGACY_AUTH_MODE");
  return mode;
}

function clientAddress(request) {
  const value = request.headers.get("CF-Connecting-IP") || "unknown";
  return /^[0-9a-fA-F:.]{3,64}$/.test(value) ? value : "unknown";
}

async function rateLimitObjectName(scope, identity) {
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode("apk-server-v2-rate-limit:" + scope + ":" + identity),
  );
  return scope + ":" + Array.from(
    new Uint8Array(bytes),
    (value) => value.toString(16).padStart(2, "0"),
  ).join("");
}

export async function takeDistributedRateLimit(env, scope, identity, limit, nowMs = Date.now()) {
  if (!env.RATE_LIMITER || typeof env.RATE_LIMITER.idFromName !== "function") {
    throw new Error("rate limiter binding is unavailable");
  }
  const objectId = env.RATE_LIMITER.idFromName(await rateLimitObjectName(scope, identity));
  const response = await env.RATE_LIMITER.get(objectId).fetch("https://rate-limit/check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ limit, nowMs }),
  });
  if (!response.ok) throw new Error("rate limiter request failed");
  const result = await response.json();
  if (!result || typeof result.allowed !== "boolean") throw new Error("rate limiter response is invalid");
  return result.allowed;
}

export class RateLimiter {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    if (request.method !== "POST") return json({ ok: false, error: "method not allowed" }, 405);
    let input;
    try {
      input = await request.json();
    } catch (_) {
      return json({ ok: false, error: "invalid rate limit request" }, 400);
    }
    const limit = Number(input && input.limit);
    const nowMs = Number(input && input.nowMs);
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > CREDENTIAL_RATE_LIMIT
        || !Number.isSafeInteger(nowMs) || nowMs < 0) {
      return json({ ok: false, error: "invalid rate limit request" }, 400);
    }
    const allowed = await this.state.storage.transaction(async (storage) => {
      const previous = await storage.get("window");
      const current = previous && Number.isSafeInteger(previous.windowStart)
        && Number.isSafeInteger(previous.count) && previous.count > 0
        && nowMs >= previous.windowStart && nowMs - previous.windowStart < RATE_WINDOW_MS
        ? previous
        : { windowStart: nowMs, count: 0 };
      if (current.count >= limit) return false;
      await storage.put("window", { windowStart: current.windowStart, count: current.count + 1 });
      return true;
    });
    return json({ ok: true, allowed });
  }
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...SECURITY_HEADERS, "Content-Type": "application/json; charset=utf-8" },
  });
}

function unauthorized() {
  return new Response("Authentication required", {
    status: 401,
    headers: { ...SECURITY_HEADERS, "WWW-Authenticate": 'Basic realm="APK Server V2 Telemetry"' },
  });
}

function isAdmin(request, env) {
  if (!env.DASHBOARD_TOKEN || env.DASHBOARD_TOKEN.length < 24) return false;
  const authorization = request.headers.get("Authorization") || "";
  if (!authorization.startsWith("Basic ")) return false;
  try {
    const decoded = atob(authorization.slice(6));
    const separator = decoded.indexOf(":");
    return separator >= 0 && safeEqual(decoded.slice(0, separator), "admin")
      && safeEqual(decoded.slice(separator + 1), env.DASHBOARD_TOKEN);
  } catch (_) {
    return false;
  }
}

export async function readBodyLimited(request, maximumBytes = MAX_BODY_BYTES) {
  const contentLength = request.headers.get("Content-Length");
  if (contentLength !== null) {
    if (!/^[0-9]+$/.test(contentLength)) throw new Error("invalid Content-Length");
    if (Number(contentLength) > maximumBytes) throw new RangeError("payload too large");
  }
  if (!request.body) return "";
  const reader = request.body.getReader();
  const chunks = [];
  let total = 0;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maximumBytes) {
        await reader.cancel("payload too large");
        throw new RangeError("payload too large");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

async function ingest(request, env, context) {
  if (!env.INGEST_TOKEN || env.INGEST_TOKEN.length < 32
      || !safeEqual(request.headers.get("X-Telemetry-Key") || "", env.INGEST_TOKEN)) {
    return json({ ok: false, error: "unauthorized" }, 401);
  }
  const nowMs = Date.now();
  let allowed;
  let ipAllowed;
  try {
    [allowed, ipAllowed] = await Promise.all([
      takeDistributedRateLimit(env, "credential", env.INGEST_TOKEN, CREDENTIAL_RATE_LIMIT, nowMs),
      takeDistributedRateLimit(env, "ip", clientAddress(request), IP_RATE_LIMIT, nowMs),
    ]);
  } catch (error) {
    console.error("telemetry rate limiter unavailable", error);
    return json({ ok: false, error: "rate limiter unavailable" }, 503);
  }
  if (!allowed || !ipAllowed) {
    return json({ ok: false, error: "rate limit exceeded" }, 429);
  }
  let raw;
  try {
    raw = await readBodyLimited(request);
  } catch (error) {
    if (error instanceof RangeError) return json({ ok: false, error: "payload too large" }, 413);
    return json({ ok: false, error: "invalid request body" }, 400);
  }
  let item;
  try {
    item = validatePayload(JSON.parse(raw));
  } catch (error) {
    return json({ ok: false, error: error.message }, 400);
  }
  let legacyMode;
  try {
    legacyMode = legacyAuthMode(env);
  } catch (error) {
    console.error("telemetry legacy auth mode is invalid", error);
    return json({ ok: false, error: "invalid server configuration" }, 500);
  }
  if (!item.authVersion && legacyMode === "reject") {
    return json({ ok: false, error: "legacy telemetry is disabled" }, 403);
  }
  const now = Math.floor(Date.now() / 1000);
  try {
    allowed = await takeDistributedRateLimit(env, "device", item.deviceId, DEVICE_RATE_LIMIT, nowMs);
  } catch (error) {
    console.error("telemetry rate limiter unavailable", error);
    return json({ ok: false, error: "rate limiter unavailable" }, 503);
  }
  if (!allowed) {
    return json({ ok: false, error: "rate limit exceeded" }, 429);
  }
  let authenticated;
  try {
    authenticated = await verifyRequestAuthentication(item, env.INGEST_TOKEN, now);
  } catch (error) {
    return json({ ok: false, error: error.message }, 400);
  }
  if (authenticated.authenticated) {
    try {
      await env.DB.prepare(
        "INSERT INTO telemetry_nonces (nonce, expires_at) VALUES (?, ?)",
      ).bind(item.nonce, nonceExpirySeconds(Number(item.eventTime), now)).run();
    } catch (_) {
      return json({ ok: false, error: "replayed request" }, 409);
    }
  }
  const eventTime = Number(item.eventTime);
  const upsert = env.DB.prepare(`
    INSERT INTO devices (
      device_id, first_seen, last_seen, last_event, state, phase, current_package,
      version_code, release_id, endpoint, model, sdk, rom_version, runtime_version, last_message
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(device_id) DO UPDATE SET
      last_seen=excluded.last_seen,
      last_event=excluded.last_event,
      state=CASE WHEN excluded.state='' THEN devices.state ELSE excluded.state END,
      phase=CASE WHEN excluded.phase='' THEN devices.phase ELSE excluded.phase END,
      current_package=CASE WHEN excluded.current_package='' THEN devices.current_package ELSE excluded.current_package END,
      version_code=CASE WHEN excluded.version_code='' THEN devices.version_code ELSE excluded.version_code END,
      release_id=CASE WHEN excluded.release_id='' THEN devices.release_id ELSE excluded.release_id END,
      endpoint=CASE WHEN excluded.endpoint='' THEN devices.endpoint ELSE excluded.endpoint END,
      model=CASE WHEN excluded.model='' THEN devices.model ELSE excluded.model END,
      sdk=CASE WHEN excluded.sdk='' THEN devices.sdk ELSE excluded.sdk END,
      rom_version=CASE WHEN excluded.rom_version='' THEN devices.rom_version ELSE excluded.rom_version END,
      runtime_version=excluded.runtime_version,
      last_message=CASE WHEN excluded.last_message='' THEN devices.last_message ELSE excluded.last_message END
  `).bind(item.deviceId, now, now, item.event, item.state, item.phase, item.packageName,
    item.versionCode, item.releaseId, item.endpoint, item.model, item.sdk, item.romVersion,
    item.runtimeVersion, item.message);
  const insert = env.DB.prepare(`
    INSERT INTO events (
      device_id, received_at, event_time, event, run_id, state, phase, package_name,
      version_code, release_id, endpoint, message, auth_version
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(item.deviceId, now, eventTime, item.event, item.runId, item.state, item.phase,
    item.packageName, item.versionCode, item.releaseId, item.endpoint, item.message,
    authenticated.authenticated ? AUTH_VERSION : "legacy");
  await env.DB.batch([upsert, insert]);
  if (context && Math.random() < 0.01) {
    const cutoff = now - EVENT_RETENTION_DAYS * 86400;
    context.waitUntil(env.DB.prepare("DELETE FROM events WHERE received_at < ?").bind(cutoff).run());
    if (authenticated.authenticated) {
      context.waitUntil(env.DB.prepare("DELETE FROM telemetry_nonces WHERE expires_at < ?").bind(now).run());
    }
  }
  return json({ ok: true }, 202);
}

export async function stats(env) {
  const now = Math.floor(Date.now() / 1000);
  const onlineAfter = now - ONLINE_WINDOW_SECONDS;
  const dayAfter = now - 86400;
  const [summary, outcomes, authVersions, deviceGroups, recent, downloads, failures] = await Promise.all([
    env.DB.prepare(`
      SELECT COUNT(*) AS totalDevices,
        COALESCE(SUM(CASE WHEN last_seen >= ? THEN 1 ELSE 0 END), 0) AS onlineDevices,
        COALESCE(SUM(CASE WHEN last_seen >= ? AND state='running'
          AND phase IN ('download-payload','install','uninstall') THEN 1 ELSE 0 END), 0) AS activeInstalls
      FROM devices
    `).bind(onlineAfter, onlineAfter).first(),
    env.DB.prepare(`
      SELECT
        COALESCE(SUM(CASE WHEN event='download_completed' THEN 1 ELSE 0 END), 0) AS downloads24h,
        COALESCE(SUM(CASE WHEN event='install_completed' THEN 1 ELSE 0 END), 0) AS installs24h,
        COALESCE(SUM(CASE WHEN event IN ('run_failed','install_failed','download_failed','uninstall_failed','manifest_failed') THEN 1 ELSE 0 END), 0) AS failures24h
      FROM events WHERE received_at >= ?
    `).bind(dayAfter).first(),
    env.DB.prepare(`
      SELECT auth_version AS authVersion, COUNT(*) AS events
      FROM events WHERE received_at >= ?
      GROUP BY auth_version ORDER BY auth_version ASC
    `).bind(dayAfter).all(),
    env.DB.prepare(`
      SELECT
        CASE WHEN TRIM(COALESCE(model, ''))='' THEN 'Không xác định' ELSE TRIM(model) END AS model,
        CASE WHEN TRIM(COALESCE(sdk, ''))='' THEN 'Không xác định' ELSE TRIM(sdk) END AS sdk,
        COUNT(*) AS deviceCount,
        COALESCE(SUM(CASE WHEN last_seen >= ? THEN 1 ELSE 0 END), 0) AS onlineDevices
      FROM devices
      GROUP BY
        CASE WHEN TRIM(COALESCE(model, ''))='' THEN 'Không xác định' ELSE TRIM(model) END,
        CASE WHEN TRIM(COALESCE(sdk, ''))='' THEN 'Không xác định' ELSE TRIM(sdk) END
      ORDER BY deviceCount DESC, model ASC, sdk ASC
    `).bind(onlineAfter).all(),
    env.DB.prepare(`
      SELECT device_id AS deviceId, last_seen AS lastSeen, last_event AS lastEvent, state, phase,
        current_package AS packageName, release_id AS releaseId, endpoint, model, sdk,
        rom_version AS romVersion, runtime_version AS runtimeVersion, last_message AS message
      FROM devices ORDER BY last_seen DESC LIMIT 100
    `).all(),
    env.DB.prepare(`
      SELECT package_name AS packageName, version_code AS versionCode, COUNT(*) AS downloads
      FROM events WHERE event='download_completed'
      GROUP BY package_name, version_code ORDER BY downloads DESC LIMIT 50
    `).all(),
    env.DB.prepare(`
      SELECT received_at AS receivedAt, device_id AS deviceId, event, package_name AS packageName, message
      FROM events WHERE event IN ('run_failed','install_failed','download_failed','uninstall_failed','manifest_failed')
      ORDER BY received_at DESC LIMIT 50
    `).all(),
  ]);
  return {
    generatedAt: now,
    onlineWindowSeconds: ONLINE_WINDOW_SECONDS,
    ...summary,
    ...outcomes,
    authVersions: authVersions.results || [],
    deviceGroups: deviceGroups.results || [],
    recentDevices: recent.results || [],
    downloads: downloads.results || [],
    recentFailures: failures.results || [],
  };
}

export async function storageHealth(env) {
  const now = Math.floor(Date.now() / 1000);
  if (cachedStorageHealth && cachedStorageHealth.expiresAt > now) return cachedStorageHealth.value;
  let value;
  try {
    if (!env.ARTIFACTS) throw new Error("R2 binding unavailable");
    const object = await env.ARTIFACTS.get("manifest.json");
    if (!object) throw new Error("manifest.json is missing from R2");
    if (!Number.isFinite(object.size) || object.size <= 0 || object.size > MAX_MANIFEST_BYTES) {
      throw new Error("R2 manifest size is invalid");
    }
    const manifest = await object.json();
    if (manifest.schemaVersion !== 3 || typeof manifest.releaseId !== "string"
        || !Array.isArray(manifest.packages)) {
      throw new Error("R2 manifest schema is invalid");
    }
    const missingObjects = [];
    const sizeMismatches = [];
    let declaredBytes = 0;
    for (const item of manifest.packages) {
      const payload = item && item.payload;
      if (!payload || typeof payload.path !== "string" || !payload.path.startsWith("payload/")
          || !Number.isSafeInteger(payload.size) || payload.size <= 0) {
        throw new Error("R2 manifest payload metadata is invalid");
      }
      declaredBytes += payload.size;
      const head = await env.ARTIFACTS.head(payload.path);
      if (!head) missingObjects.push(payload.path);
      else if (head.size !== payload.size) sizeMismatches.push(payload.path);
    }
    const helper = await env.ARTIFACTS.head("remote-preinstall.jar");
    if (!helper) missingObjects.push("remote-preinstall.jar");
    value = {
      ok: missingObjects.length === 0 && sizeMismatches.length === 0,
      releaseId: manifest.releaseId,
      manifestUpdatedAt: object.uploaded instanceof Date ? object.uploaded.toISOString() : "",
      declaredObjects: manifest.packages.length + 1,
      presentObjects: manifest.packages.length + 1 - missingObjects.length,
      missingObjects,
      sizeMismatches,
      declaredBytes,
      checkedAt: new Date(now * 1000).toISOString(),
    };
  } catch (error) {
    console.error("R2 storage health failed", error);
    value = {
      ok: false,
      error: error && error.message ? error.message : "storage health failed",
      releaseId: "",
      declaredObjects: 0,
      presentObjects: 0,
      missingObjects: [],
      sizeMismatches: [],
      declaredBytes: 0,
      checkedAt: new Date(now * 1000).toISOString(),
    };
  }
  cachedStorageHealth = { expiresAt: now + STORAGE_CACHE_SECONDS, value };
  return value;
}

const DASHBOARD = `<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>APK Server V2 Telemetry</title><style>
:root{color-scheme:dark;font-family:system-ui,sans-serif}body{margin:0;background:#102027;color:#eef;padding:24px}h1{margin-top:0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card,section{background:#182b32;border:1px solid #31545e;border-radius:10px;padding:16px}.value{font-size:32px;font-weight:700;color:#80cbc4}section{margin-top:16px;overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;border-bottom:1px solid #31545e;padding:8px;white-space:nowrap}.ok{color:#80cbc4}.bad{color:#ff8a80}button{background:#00695c;color:white;border:1px solid #80cbc4;border-radius:8px;padding:10px 18px}button:focus{background:white;color:black}</style></head><body>
<h1>APK Server V2 — Telemetry</h1><button id="refresh">Làm mới</button><span id="updated"></span><div class="cards" id="cards"></div>
<section><h2>Tổng thiết bị theo Model / SDK</h2><table><thead><tr><th>Model</th><th>SDK</th><th>Tổng thiết bị</th><th>Online 10 phút</th></tr></thead><tbody id="device-groups"></tbody></table></section>
<section><h2>Thiết bị gần đây</h2><table><thead><tr><th>Device ID</th><th>Online</th><th>Trạng thái</th><th>Giai đoạn</th><th>Package</th><th>Model / SDK</th><th>Release</th><th>Thời gian</th></tr></thead><tbody id="devices"></tbody></table></section>
<section><h2>Lượt tải theo APK</h2><table><thead><tr><th>Package</th><th>Version</th><th>Lượt tải</th></tr></thead><tbody id="downloads"></tbody></table></section>
<section><h2>R2 storage</h2><div id="storage">Đang kiểm tra…</div></section>
<section><h2>Lỗi gần nhất</h2><table><thead><tr><th>Thời gian</th><th>Device ID</th><th>Sự kiện</th><th>Package</th><th>Thông báo</th></tr></thead><tbody id="failures"></tbody></table></section>
<script>
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const time=v=>new Date(Number(v)*1000).toLocaleString('vi-VN');
async function loadDeviceGroups(){const r=await fetch('/api/v2/stats',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json(),groups=Array.isArray(d.deviceGroups)?d.deviceGroups:[];document.querySelector('#device-groups').innerHTML=groups.length?groups.map(x=>'<tr><td>'+esc(x.model)+'</td><td>'+esc(x.sdk)+'</td><td>'+esc(x.deviceCount)+'</td><td>'+esc(x.onlineDevices)+'</td></tr>').join(''):'<tr><td colspan=4>Chưa có dữ liệu thiết bị</td></tr>'}
async function load(){const [r,sr]=await Promise.all([fetch('/api/v2/stats',{cache:'no-store'}),fetch('/api/v2/storage-health',{cache:'no-store'})]);if(!r.ok||!sr.ok)throw new Error('HTTP '+r.status+'/'+sr.status);const d=await r.json(),s=await sr.json();const cards=[['Tổng thiết bị',d.totalDevices],['Online 10 phút',d.onlineDevices],['Đang cài đặt',d.activeInstalls],['Lượt tải 24h',d.downloads24h],['Cài thành công 24h',d.installs24h],['Lỗi 24h',d.failures24h],['R2 storage',s.ok?'OK':'Lỗi']];document.querySelector('#cards').innerHTML=cards.map(x=>'<div class="card"><div>'+esc(x[0])+'</div><div class="value '+(x[0]==='R2 storage'&&!s.ok?'bad':'')+'">'+esc(x[1])+'</div></div>').join('');document.querySelector('#updated').textContent=' Cập nhật: '+time(d.generatedAt);document.querySelector('#storage').innerHTML='<b class="'+(s.ok?'ok':'bad')+'">'+(s.ok?'Đồng bộ':'Chưa hoàn chỉnh')+'</b> · Release '+esc(s.releaseId||'—')+' · '+esc(s.presentObjects)+'/'+esc(s.declaredObjects)+' object · '+esc(s.declaredBytes)+' byte · kiểm tra '+esc(s.checkedAt)+(s.error?'<br><span class="bad">'+esc(s.error)+'</span>':'')+(s.missingObjects?.length?'<br>Thiếu: '+esc(s.missingObjects.join(', ')):'')+(s.sizeMismatches?.length?'<br>Sai kích thước: '+esc(s.sizeMismatches.join(', ')):'');document.querySelector('#devices').innerHTML=d.recentDevices.map(x=>'<tr><td>'+esc(x.deviceId.slice(0,8))+'…</td><td class="'+(x.lastSeen>=d.generatedAt-d.onlineWindowSeconds?'ok':'')+'">'+(x.lastSeen>=d.generatedAt-d.onlineWindowSeconds?'Có':'Không')+'</td><td>'+esc(x.state)+'</td><td>'+esc(x.phase)+'</td><td>'+esc(x.packageName)+'</td><td>'+esc(x.model)+' / '+esc(x.sdk)+'</td><td>'+esc(x.releaseId)+'</td><td>'+time(x.lastSeen)+'</td></tr>').join('');document.querySelector('#downloads').innerHTML=d.downloads.map(x=>'<tr><td>'+esc(x.packageName)+'</td><td>'+esc(x.versionCode)+'</td><td>'+esc(x.downloads)+'</td></tr>').join('');document.querySelector('#failures').innerHTML=d.recentFailures.map(x=>'<tr><td>'+time(x.receivedAt)+'</td><td>'+esc(x.deviceId.slice(0,8))+'…</td><td class="bad">'+esc(x.event)+'</td><td>'+esc(x.packageName)+'</td><td>'+esc(x.message)+'</td></tr>').join('')}
const refresh=()=>Promise.all([load(),loadDeviceGroups()]).catch(e=>alert(e));document.querySelector('#refresh').onclick=refresh;refresh();setInterval(()=>Promise.all([load(),loadDeviceGroups()]).catch(()=>{}),30000);
</script></body></html>`;

async function handle(request, env, context) {
  const url = new URL(request.url);
  if (url.pathname === "/api/v2/health" && request.method === "GET") return json({ ok: true, service: "apk-server-v2-telemetry" });
  if (url.pathname === "/api/v2/telemetry" && request.method === "POST") return ingest(request, env, context);
  if (url.pathname === "/api/v2/stats" && request.method === "GET") {
    if (!isAdmin(request, env)) return unauthorized();
    return json(await stats(env));
  }
  if (url.pathname === "/api/v2/storage-health" && request.method === "GET") {
    if (!isAdmin(request, env)) return unauthorized();
    return json(await storageHealth(env));
  }
  if ((url.pathname === "/telemetry" || url.pathname === "/telemetry/") && request.method === "GET") {
    if (!isAdmin(request, env)) return unauthorized();
    return new Response(DASHBOARD, { headers: { ...SECURITY_HEADERS, "Content-Type": "text/html; charset=utf-8" } });
  }
  return json({ ok: false, error: "not found" }, 404);
}

export default {
  fetch(request, env, context) {
    return handle(request, env, context).catch((error) => {
      console.error("telemetry request failed", error);
      return json({ ok: false, error: "internal error" }, 500);
    });
  },
  async scheduled(_event, env) {
    const cutoff = Math.floor(Date.now() / 1000) - EVENT_RETENTION_DAYS * 86400;
    const now = Math.floor(Date.now() / 1000);
    await Promise.all([
      env.DB.prepare("DELETE FROM events WHERE received_at < ?").bind(cutoff).run(),
      env.DB.prepare("DELETE FROM telemetry_nonces WHERE expires_at < ?").bind(now).run(),
    ]);
  },
};
