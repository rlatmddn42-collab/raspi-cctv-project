// 로컬 디버그 UI - 정적 placeholder 전용
// 실제 백엔드 연동은 추후 구현됨

const placeholder = {
    uptime: "00:12:34",
    cpuTemp: "48.2 ℃",
    serverConn: "연결됨 (모의)",
    lastSync: "2026-05-07 09:12",
    ping: "23",
    cctvRes: "1280x720",
    cctvFps: "15",
    ocrEnabled: "활성",
    ocrLast: "2026-05-07 09:11",
    ocrTempRoi: "x=120, y=40, w=80, h=24",
    ocrHumidRoi: "x=120, y=70, w=80, h=24",
    tempVal: "23.4 ℃",
    humidVal: "46 %",
    thTime: "2026-05-07 09:11",
    modelLoaded: "예",
    modelRuntime: "ONNX Runtime",
    modelVersion: "v0.1.0-dev",
    modelHash: "abc1234",
    inferState: "동작 중",
    inferFps: "4.1",
    pollutionScore: "0.27",
    pollutionTime: "2026-05-07 09:12"
};

function fill(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function applyPlaceholder() {
    fill("uptime", placeholder.uptime);
    fill("cpu-temp", placeholder.cpuTemp);
    fill("server-conn", placeholder.serverConn);
    fill("last-sync", placeholder.lastSync);
    fill("ping", placeholder.ping);
    fill("cctv-res", placeholder.cctvRes);
    fill("cctv-fps", placeholder.cctvFps);
    fill("ocr-enabled", placeholder.ocrEnabled);
    fill("ocr-last", placeholder.ocrLast);
    fill("ocr-temp-roi", placeholder.ocrTempRoi);
    fill("ocr-humid-roi", placeholder.ocrHumidRoi);
    fill("temp-val", placeholder.tempVal);
    fill("humid-val", placeholder.humidVal);
    fill("th-time", placeholder.thTime);
    fill("model-loaded", placeholder.modelLoaded);
    fill("model-runtime", placeholder.modelRuntime);
    fill("model-version", placeholder.modelVersion);
    fill("model-hash", placeholder.modelHash);
    fill("infer-state", placeholder.inferState);
    fill("infer-fps", placeholder.inferFps);
    fill("pollution-score", placeholder.pollutionScore);
    fill("pollution-time", placeholder.pollutionTime);
}

function appendLog(line) {
    const logEl = document.getElementById("log-area");
    if (!logEl) return;
    const ts = new Date().toLocaleTimeString();
    logEl.textContent += `\n[${ts}] ${line}`;
    logEl.scrollTop = logEl.scrollHeight;
}

document.addEventListener("DOMContentLoaded", () => {
    applyPlaceholder();
    appendLog("디버그 UI 로드 완료 (placeholder 모드)");
    appendLog("백엔드 연동은 아직 구현되지 않았습니다");
});
