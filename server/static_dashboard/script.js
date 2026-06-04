// 중앙 서버 대시보드 - 라이브 백엔드 연동
//
// 실시간 CCTV 상태(장치 목록 + 통계 카드)와 이벤트 기록은
// COMMUNICATION_PROTOCOL.md v0.1 의 GET 엔드포인트에서 가져옵니다.
//
// 오염도 / 온습도 는 현재 프로토콜에 정의되어 있지 않아 백엔드에서
// 제공되지 않습니다. 가짜 데이터를 표시하지 않고 "미연동" 상태로 둡니다.

const API_BASE = (window.API_BASE || "http://localhost:9000").replace(/\/+$/, "");

// --- fetch helper ------------------------------------------------------------
// Surfaces the §5 error envelope as an Error and lets the network layer throw
// so each section can fall back independently.

async function apiGet(path) {
    const res = await fetch(`${API_BASE}${path}`, {
        headers: { "Accept": "application/json" },
    });
    let body = null;
    try {
        body = await res.json();
    } catch (_) {
        // non-JSON body (shouldn't happen for these endpoints)
    }
    if (!res.ok || (body && body.ok === false)) {
        const code = body && body.error ? body.error.code : `http_${res.status}`;
        const msg = body && body.error ? body.error.message : res.statusText;
        throw new Error(`[${code}] ${msg}`);
    }
    return body;
}

// --- small render utilities --------------------------------------------------

function setBody(tableId, html) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    if (tbody) tbody.innerHTML = html;
}

function colCount(tableId) {
    return document.querySelectorAll(`#${tableId} thead th`).length || 1;
}

function fullWidthRow(tableId, text, cls) {
    return `<tr><td class="${cls}" colspan="${colCount(tableId)}">${text}</td></tr>`;
}

// Render a value that may be null/undefined as an em dash.
function show(v) {
    return (v === null || v === undefined || v === "") ? "—" : v;
}

// ISO 8601 UTC -> "YYYY-MM-DD HH:MM" local-ish display. Falls back to raw.
function fmtTime(iso) {
    if (!iso) return "—";
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ` +
           `${p(d.getHours())}:${p(d.getMinutes())}`;
}

function statusBadge(status) {
    if (status === "ok") return `<span class="badge ok">정상</span>`;
    if (!status) return `<span class="badge warn">대기</span>`;
    return `<span class="badge bad">${status}</span>`;
}

// --- API status banner -------------------------------------------------------

function setApiStatus(state, text) {
    const wrap = document.getElementById("api-status");
    const label = document.getElementById("api-status-text");
    if (wrap) wrap.className = `api-status ${state}`;
    if (label) label.textContent = text;
}

// --- realtime: device list + stat cards --------------------------------------

function isOnline(dev) {
    return dev.status === "ok";
}

function renderCctvTable(devices) {
    if (!devices.length) {
        setBody("cctv-table", fullWidthRow("cctv-table", "등록된 장치가 없습니다.", "muted"));
        return;
    }
    setBody("cctv-table", devices.map((d) => `
        <tr>
            <td>${show(d.device_id)}</td>
            <td>${show(d.location)}</td>
            <td>${statusBadge(d.status)}</td>
            <td>${show(d.fps)}</td>
            <td>${show(d.model_version)}</td>
            <td>${fmtTime(d.last_seen)}</td>
        </tr>
    `).join(""));
}

function renderStatCards(devices) {
    const total = devices.length;
    const online = devices.filter(isOnline).length;
    const offline = total - online;

    const set = (id, value, cls) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = value;
        if (cls) el.className = `value ${cls}`;
    };
    set("stat-online", `${online} / ${total}`);
    set("stat-streaming", online, "ok");
    set("stat-offline", offline, offline ? "warn" : "ok");
    set("stat-server", "정상", "ok");

    // settings card: show the newest reported model version, if any.
    const versions = devices.map((d) => d.model_version).filter(Boolean);
    const mv = document.getElementById("setting-model-version");
    if (mv) mv.textContent = versions.length ? versions[versions.length - 1] : "미보고";
}

function renderRealtimeUnavailable(message) {
    setBody("cctv-table", fullWidthRow("cctv-table", message, "error"));
    ["stat-online", "stat-streaming", "stat-offline"].forEach((id) => {
        const el = document.getElementById(id);
        if (el) { el.textContent = "—"; el.className = "value"; }
    });
    const sv = document.getElementById("stat-server");
    if (sv) { sv.textContent = "오프라인"; sv.className = "value bad"; }
}

async function loadRealtime() {
    const data = await apiGet("/api/devices");
    const devices = (data && data.devices) || [];
    renderCctvTable(devices);
    renderStatCards(devices);
    return devices;
}

// --- events: aggregate per-device, sort newest first -------------------------

const SEVERITY_LABEL = { info: "정보", warning: "주의", critical: "위험" };

async function loadEvents(devices) {
    if (!devices.length) {
        setBody("events-table", fullWidthRow("events-table", "이벤트가 없습니다.", "muted"));
        return;
    }
    // Fetch each device's events; tolerate a single device failing.
    const results = await Promise.allSettled(
        devices.map((d) =>
            apiGet(`/api/devices/${encodeURIComponent(d.device_id)}/events?limit=100`)
                .then((r) => ((r && r.events) || []).map((e) => ({ ...e, device_id: d.device_id })))
        )
    );

    const events = [];
    let anyFailed = false;
    for (const r of results) {
        if (r.status === "fulfilled") events.push(...r.value);
        else anyFailed = true;
    }
    events.sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp)));

    if (!events.length) {
        const msg = anyFailed
            ? "일부 장치의 이벤트를 불러오지 못했습니다."
            : "이벤트가 없습니다.";
        setBody("events-table", fullWidthRow("events-table", msg, anyFailed ? "error" : "muted"));
        return;
    }
    setBody("events-table", events.map((e) => {
        const sev = SEVERITY_LABEL[e.severity] || e.severity || "";
        const type = e.event_type ? `${e.event_type}${sev ? ` (${sev})` : ""}` : show(sev);
        return `
        <tr>
            <td>${fmtTime(e.timestamp)}</td>
            <td>${show(e.device_id)}</td>
            <td>${type}</td>
            <td>${show(e.message)}</td>
        </tr>`;
    }).join(""));
}

// --- unbacked sections: honest empty state -----------------------------------

const UNBACKED_MSG = "백엔드에서 제공되지 않는 데이터입니다 (프로토콜 v0.1 미정의).";

function renderUnbackedSections() {
    setBody("pollution-table", fullWidthRow("pollution-table", UNBACKED_MSG, "muted"));
    setBody("th-table", fullWidthRow("th-table", UNBACKED_MSG, "muted"));
}

// --- bootstrap ---------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
    const apiBaseEl = document.getElementById("setting-api-base");
    if (apiBaseEl) apiBaseEl.textContent = API_BASE;

    // Always honest about what isn't wired, regardless of API state.
    renderUnbackedSections();

    try {
        const devices = await loadRealtime();
        setApiStatus("online", `API 연결됨 · 장치 ${devices.length}대`);
        await loadEvents(devices);
    } catch (err) {
        setApiStatus("offline", "API 서버에 연결할 수 없습니다");
        renderRealtimeUnavailable(`서버에 연결할 수 없습니다: ${err.message}`);
        setBody(
            "events-table",
            fullWidthRow("events-table", "서버에 연결할 수 없어 이벤트를 불러오지 못했습니다.", "error")
        );
    }
});
