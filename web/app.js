import { $, fmt } from "./dom.js";
import { initChart, pushPoint, setHistory, setThreshold } from "./chart.js";
import { initDevice, renderDevice } from "./device.js";
import { addAlarm, initAlarms, loadAlarms, updateNotify } from "./alarms.js";
import { initTelegram, loadTelegram } from "./telegram.js";

const STATE_TEXT = { normal: "Bình thường", suspect: "Nghi ngờ ngã" };
const SILENCE_LIMIT_MS = 10000;
const ALARM_CHIP_MS = 8000;
const TABS = ["monitor", "alarms", "telegram"];

let activeTab = "monitor";
let lastEvent = Date.now();
let source = null;
let retry = 0;
let alarmUntil = 0;
let streaming = false;
let streamTimer = null;
let lastState = "normal";

function setConn(kind, text) {
  $("conn-dot").className = "dot dot-" + kind;
  $("conn-text").textContent = text;
}

function renderState(state) {
  lastState = state;
  const chip = $("state-chip");
  if (Date.now() < alarmUntil) {
    chip.textContent = "BÁO ĐỘNG";
    chip.className = "chip chip-alarm";
    return;
  }
  chip.textContent = STATE_TEXT[state] || state;
  chip.className = "chip " + (state === "suspect" ? "chip-suspect" : "chip-normal");
}

function onStatus(data) {
  lastEvent = Date.now();
  setThreshold(data.threshold);
  pushPoint(data.t, data.p_fall, data.state);
  renderState(data.state);
  $("thr-val").textContent = fmt(data.threshold, 2);
  $("m-pfall").textContent = fmt(data.p_fall, 2);
  $("m-fps").textContent = fmt(data.fps, 1) + (data.target_fps ? " / " + data.target_fps : "");
  $("m-ms").textContent = fmt(data.pose_ms, 0, "ms");
  $("m-source").textContent = data.source || "N/A";
}

function showBanner(record) {
  alarmUntil = Date.now() + ALARM_CHIP_MS;
  const when = record && record.time_iso ? record.time_iso.replace("T", " ") : "";
  $("alarm-banner-text").textContent = when ? "Lúc " + when : "";
  $("alarm-banner").hidden = false;
  renderState("normal");
}

function connect() {
  if (source) source.close();
  setConn("wait", "Đang kết nối");
  source = new EventSource("/events");
  source.onopen = () => {
    retry = 0;
    lastEvent = Date.now();
    setConn("ok", "Trực tuyến");
  };
  source.onerror = () => {
    source.close();
    setConn("lost", "Mất kết nối");
    retry += 1;
    setTimeout(connect, Math.min(1000 * 2 ** retry, 10000));
  };
  const on = (name, handler) => source.addEventListener(name, (event) => {
    lastEvent = Date.now();
    try {
      handler(JSON.parse(event.data));
    } catch (e) {
      return;
    }
  });
  on("status", onStatus);
  on("system", renderDevice);
  on("history", setHistory);
  on("alarm", (record) => {
    showBanner(record);
    addAlarm(record);
  });
  on("notify", updateNotify);
}

function watchdog() {
  if (source && source.readyState === EventSource.OPEN && Date.now() - lastEvent > SILENCE_LIMIT_MS) {
    source.close();
    setConn("lost", "Mất kết nối");
    connect();
  }
}

function syncStream() {
  const want = activeTab === "monitor" && !document.hidden;
  const img = $("stream");
  clearTimeout(streamTimer);
  if (want && !streaming) {
    streaming = true;
    $("stream-msg").hidden = true;
    img.src = "/stream.mjpg?ts=" + Date.now();
  } else if (!want && streaming) {
    streaming = false;
    img.removeAttribute("src");
  }
}

function onStreamError() {
  if (!streaming) return;
  streaming = false;
  $("stream").removeAttribute("src");
  $("stream-msg").textContent = "Không mở được luồng video (có thể đã đủ số người xem). Đang thử lại…";
  $("stream-msg").hidden = false;
  streamTimer = setTimeout(syncStream, 5000);
}

function selectTab(name, focus) {
  activeTab = name;
  for (const tab of TABS) {
    const button = $("tab-" + tab);
    const selected = tab === name;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    $("panel-" + tab).hidden = !selected;
    if (selected && focus) button.focus();
  }
  syncStream();
  if (name === "alarms") loadAlarms();
}

function initTabs() {
  TABS.forEach((name, index) => {
    const button = $("tab-" + name);
    button.addEventListener("click", () => selectTab(name, false));
    button.addEventListener("keydown", (event) => {
      let next = null;
      if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
      if (event.key === "ArrowLeft") next = (index + TABS.length - 1) % TABS.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = TABS.length - 1;
      if (next !== null) {
        event.preventDefault();
        selectTab(TABS[next], true);
      }
    });
  });
}

initChart();
initDevice();
initAlarms();
initTelegram();
initTabs();
$("stream").addEventListener("error", onStreamError);
$("alarm-banner-close").addEventListener("click", () => {
  $("alarm-banner").hidden = true;
});
document.addEventListener("visibilitychange", syncStream);
setInterval(watchdog, 2000);
setInterval(() => renderState(lastState), 1000);
connect();
syncStream();
loadAlarms();
loadTelegram();
