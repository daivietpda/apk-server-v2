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
  };
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

async function ingest(request, env, context) {
  if (!env.INGEST_TOKEN || env.INGEST_TOKEN.length < 32
      || !safeEqual(request.headers.get("X-Telemetry-Key") || "", env.INGEST_TOKEN)) {
    return json({ ok: false, error: "unauthorized" }, 401);
  }
  const declared = Number(request.headers.get("Content-Length") || 0);
  if (declared > MAX_BODY_BYTES) return json({ ok: false, error: "payload too large" }, 413);
  const raw = await request.text();
  if (new TextEncoder().encode(raw).length > MAX_BODY_BYTES) return json({ ok: false, error: "payload too large" }, 413);
  let item;
  try {
    item = validatePayload(JSON.parse(raw));
  } catch (error) {
    return json({ ok: false, error: error.message }, 400);
  }
  const now = Math.floor(Date.now() / 1000);
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
      version_code, release_id, endpoint, message
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(item.deviceId, now, eventTime, item.event, item.runId, item.state, item.phase,
    item.packageName, item.versionCode, item.releaseId, item.endpoint, item.message);
  await env.DB.batch([upsert, insert]);
  if (context && Math.random() < 0.01) {
    const cutoff = now - EVENT_RETENTION_DAYS * 86400;
    context.waitUntil(env.DB.prepare("DELETE FROM events WHERE received_at < ?").bind(cutoff).run());
  }
  return json({ ok: true }, 202);
}

async function stats(env) {
  const now = Math.floor(Date.now() / 1000);
  const onlineAfter = now - ONLINE_WINDOW_SECONDS;
  const dayAfter = now - 86400;
  const [summary, outcomes, recent, downloads, failures] = await Promise.all([
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
    recentDevices: recent.results || [],
    downloads: downloads.results || [],
    recentFailures: failures.results || [],
  };
}

const DASHBOARD = `<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>APK Server V2 Telemetry</title><style>
:root{color-scheme:dark;font-family:system-ui,sans-serif}body{margin:0;background:#102027;color:#eef;padding:24px}h1{margin-top:0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}.card,section{background:#182b32;border:1px solid #31545e;border-radius:10px;padding:16px}.value{font-size:32px;font-weight:700;color:#80cbc4}section{margin-top:16px;overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;border-bottom:1px solid #31545e;padding:8px;white-space:nowrap}.ok{color:#80cbc4}.bad{color:#ff8a80}button{background:#00695c;color:white;border:1px solid #80cbc4;border-radius:8px;padding:10px 18px}button:focus{background:white;color:black}</style></head><body>
<h1>APK Server V2 — Telemetry</h1><button id="refresh">Làm mới</button><span id="updated"></span><div class="cards" id="cards"></div>
<section><h2>Thiết bị gần đây</h2><table><thead><tr><th>Device ID</th><th>Online</th><th>Trạng thái</th><th>Giai đoạn</th><th>Package</th><th>Model / SDK</th><th>Release</th><th>Thời gian</th></tr></thead><tbody id="devices"></tbody></table></section>
<section><h2>Lượt tải theo APK</h2><table><thead><tr><th>Package</th><th>Version</th><th>Lượt tải</th></tr></thead><tbody id="downloads"></tbody></table></section>
<section><h2>Lỗi gần nhất</h2><table><thead><tr><th>Thời gian</th><th>Device ID</th><th>Sự kiện</th><th>Package</th><th>Thông báo</th></tr></thead><tbody id="failures"></tbody></table></section>
<script>
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const time=v=>new Date(Number(v)*1000).toLocaleString('vi-VN');
async function load(){const r=await fetch('/api/v2/stats',{cache:'no-store'});if(!r.ok)throw new Error('HTTP '+r.status);const d=await r.json();const cards=[['Tổng thiết bị',d.totalDevices],['Online 10 phút',d.onlineDevices],['Đang cài đặt',d.activeInstalls],['Lượt tải 24h',d.downloads24h],['Cài thành công 24h',d.installs24h],['Lỗi 24h',d.failures24h]];document.querySelector('#cards').innerHTML=cards.map(x=>'<div class="card"><div>'+esc(x[0])+'</div><div class="value">'+esc(x[1])+'</div></div>').join('');document.querySelector('#updated').textContent=' Cập nhật: '+time(d.generatedAt);document.querySelector('#devices').innerHTML=d.recentDevices.map(x=>'<tr><td>'+esc(x.deviceId.slice(0,8))+'…</td><td class="'+(x.lastSeen>=d.generatedAt-d.onlineWindowSeconds?'ok':'')+'">'+(x.lastSeen>=d.generatedAt-d.onlineWindowSeconds?'Có':'Không')+'</td><td>'+esc(x.state)+'</td><td>'+esc(x.phase)+'</td><td>'+esc(x.packageName)+'</td><td>'+esc(x.model)+' / '+esc(x.sdk)+'</td><td>'+esc(x.releaseId)+'</td><td>'+time(x.lastSeen)+'</td></tr>').join('');document.querySelector('#downloads').innerHTML=d.downloads.map(x=>'<tr><td>'+esc(x.packageName)+'</td><td>'+esc(x.versionCode)+'</td><td>'+esc(x.downloads)+'</td></tr>').join('');document.querySelector('#failures').innerHTML=d.recentFailures.map(x=>'<tr><td>'+time(x.receivedAt)+'</td><td>'+esc(x.deviceId.slice(0,8))+'…</td><td class="bad">'+esc(x.event)+'</td><td>'+esc(x.packageName)+'</td><td>'+esc(x.message)+'</td></tr>').join('')}
document.querySelector('#refresh').onclick=()=>load().catch(e=>alert(e));load().catch(e=>alert(e));setInterval(()=>load().catch(()=>{}),30000);
</script></body></html>`;

async function handle(request, env, context) {
  const url = new URL(request.url);
  if (url.pathname === "/api/v2/health" && request.method === "GET") return json({ ok: true, service: "apk-server-v2-telemetry" });
  if (url.pathname === "/api/v2/telemetry" && request.method === "POST") return ingest(request, env, context);
  if (url.pathname === "/api/v2/stats" && request.method === "GET") {
    if (!isAdmin(request, env)) return unauthorized();
    return json(await stats(env));
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
    await env.DB.prepare("DELETE FROM events WHERE received_at < ?").bind(cutoff).run();
  },
};
