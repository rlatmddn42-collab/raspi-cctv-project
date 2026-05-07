// 중앙 서버 대시보드 - 정적 placeholder 전용
// 실제 백엔드 API 연동은 추후 구현됨

const cctvList = [
    { id: "raspi-edge-01", location: "서울 강남 1번 도로", status: "정상", fps: 4.1, model: "v0.1.0-dev", lastSeen: "2026-05-07 09:12" },
    { id: "raspi-edge-02", location: "서울 종로 2번 교차로", status: "정상", fps: 3.9, model: "v0.1.0-dev", lastSeen: "2026-05-07 09:12" },
    { id: "raspi-edge-03", location: "인천 부평 3번 입구", status: "정상", fps: 4.2, model: "v0.1.0-dev", lastSeen: "2026-05-07 09:11" },
    { id: "raspi-edge-04", location: "수원 영통 4번", status: "오프라인", fps: 0, model: "v0.1.0-dev", lastSeen: "2026-05-06 22:14" },
    { id: "raspi-edge-05", location: "성남 분당 5번", status: "오프라인", fps: 0, model: "v0.1.0-dev", lastSeen: "2026-05-05 18:02" }
];

const pollutionList = [
    { id: "raspi-edge-01", location: "서울 강남 1번 도로", score: 0.27, grade: "양호", time: "2026-05-07 09:12" },
    { id: "raspi-edge-02", location: "서울 종로 2번 교차로", score: 0.54, grade: "보통", time: "2026-05-07 09:12" },
    { id: "raspi-edge-03", location: "인천 부평 3번 입구", score: 0.71, grade: "주의", time: "2026-05-07 09:11" }
];

const thList = [
    { id: "raspi-edge-01", temp: "23.4 ℃", humid: "46 %", time: "2026-05-07 09:11" },
    { id: "raspi-edge-02", temp: "24.1 ℃", humid: "51 %", time: "2026-05-07 09:11" },
    { id: "raspi-edge-03", temp: "22.7 ℃", humid: "58 %", time: "2026-05-07 09:10" }
];

const eventList = [
    { time: "2026-05-07 09:12", device: "raspi-edge-03", type: "오염도 주의", message: "점수 0.71 (임계치 초과)" },
    { time: "2026-05-07 09:05", device: "raspi-edge-02", type: "OCR", message: "ROI 인식 성공" },
    { time: "2026-05-07 08:50", device: "raspi-edge-04", type: "연결", message: "연결 끊김 감지" },
    { time: "2026-05-07 08:32", device: "raspi-edge-01", type: "모델", message: "모델 버전 v0.1.0-dev 로드" }
];

function statusBadge(status) {
    if (status === "정상") return `<span class="badge ok">정상</span>`;
    if (status === "오프라인") return `<span class="badge bad">오프라인</span>`;
    return `<span class="badge warn">${status}</span>`;
}

function gradeBadge(grade) {
    if (grade === "양호") return `<span class="badge ok">${grade}</span>`;
    if (grade === "주의") return `<span class="badge bad">${grade}</span>`;
    return `<span class="badge warn">${grade}</span>`;
}

function renderCctvTable() {
    const tbody = document.querySelector("#cctv-table tbody");
    tbody.innerHTML = cctvList.map(c => `
        <tr>
            <td>${c.id}</td>
            <td>${c.location}</td>
            <td>${statusBadge(c.status)}</td>
            <td>${c.fps}</td>
            <td>${c.model}</td>
            <td>${c.lastSeen}</td>
        </tr>
    `).join("");
}

function renderPollutionTable() {
    const tbody = document.querySelector("#pollution-table tbody");
    tbody.innerHTML = pollutionList.map(p => `
        <tr>
            <td>${p.id}</td>
            <td>${p.location}</td>
            <td>${p.score.toFixed(2)}</td>
            <td>${gradeBadge(p.grade)}</td>
            <td>${p.time}</td>
        </tr>
    `).join("");
}

function renderThTable() {
    const tbody = document.querySelector("#th-table tbody");
    tbody.innerHTML = thList.map(t => `
        <tr>
            <td>${t.id}</td>
            <td>${t.temp}</td>
            <td>${t.humid}</td>
            <td>${t.time}</td>
        </tr>
    `).join("");
}

function renderEventTable() {
    const tbody = document.querySelector("#events-table tbody");
    tbody.innerHTML = eventList.map(e => `
        <tr>
            <td>${e.time}</td>
            <td>${e.device}</td>
            <td>${e.type}</td>
            <td>${e.message}</td>
        </tr>
    `).join("");
}

document.addEventListener("DOMContentLoaded", () => {
    renderCctvTable();
    renderPollutionTable();
    renderThTable();
    renderEventTable();
});
