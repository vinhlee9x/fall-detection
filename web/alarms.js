import { $, api, el, fmt } from "./dom.js";

const cards = new Map();
let current = null;
let currentKind = "annotated";

function notifyLabel(notify) {
  const status = notify && notify.status;
  if (status === "sent") return ["Telegram: Đã gửi", "sent"];
  if (status === "pending") return ["Telegram: Đang gửi", "pending"];
  if (status === "failed") return ["Telegram thất bại: " + ((notify && notify.error) || "không rõ lý do"), "failed"];
  return ["Telegram: Tắt", "disabled"];
}

function formatTime(iso) {
  const parts = String(iso || "").split("T");
  if (parts.length !== 2) return String(iso || "N/A");
  const date = parts[0].split("-");
  return parts[1] + " " + date[2] + "/" + date[1] + "/" + date[0];
}

function applyBadge(badge, notify) {
  const [text, kind] = notifyLabel(notify);
  badge.textContent = text;
  badge.className = "badge badge-" + kind;
}

function buildCard(record) {
  const item = el("li");
  const button = el("button", "alarm-card");
  button.type = "button";
  const img = el("img", "alarm-thumb");
  img.loading = "lazy";
  img.alt = "Ảnh báo động lúc " + formatTime(record.time_iso);
  img.src = "/api/alarms/" + encodeURIComponent(record.id) + "/image?kind=annotated";
  const meta = el("div", "alarm-meta");
  meta.append(el("b", null, formatTime(record.time_iso)), el("span", null, "p_fall " + fmt(record.p_fall, 2)));
  const badge = el("span", "badge");
  applyBadge(badge, record.notify);
  meta.append(badge);
  button.append(img, meta);
  button.addEventListener("click", () => openViewer(record));
  item.append(button);
  return { item, badge, record };
}

function refreshEmpty() {
  $("alarms-empty").hidden = cards.size > 0;
}

export function addAlarm(record) {
  if (!record || cards.has(record.id)) return;
  const card = buildCard(record);
  cards.set(record.id, card);
  $("alarms-grid").prepend(card.item);
  refreshEmpty();
}

export function updateNotify(update) {
  const card = cards.get(update.id);
  if (!card) return;
  card.record.notify = { status: update.status, error: update.error };
  applyBadge(card.badge, card.record.notify);
}

export async function loadAlarms() {
  const res = await api("/api/alarms?limit=100");
  if (!res.ok || !Array.isArray(res.body)) return;
  const grid = $("alarms-grid");
  grid.textContent = "";
  cards.clear();
  for (const record of res.body) {
    const card = buildCard(record);
    cards.set(record.id, card);
    grid.append(card.item);
  }
  refreshEmpty();
}

function showKind(kind) {
  currentKind = kind;
  $("viewer-img").src = "/api/alarms/" + encodeURIComponent(current.id) + "/image?kind=" + kind;
  $("viewer-annotated").setAttribute("aria-pressed", String(kind === "annotated"));
  $("viewer-raw").setAttribute("aria-pressed", String(kind === "raw"));
}

function openViewer(record) {
  current = record;
  $("viewer-caption").textContent = formatTime(record.time_iso) + " · p_fall " + fmt(record.p_fall, 2);
  showKind("annotated");
  $("viewer").showModal();
}

export function initAlarms() {
  $("viewer-annotated").addEventListener("click", () => showKind("annotated"));
  $("viewer-raw").addEventListener("click", () => showKind("raw"));
  $("viewer-close").addEventListener("click", () => $("viewer").close());
  $("viewer").addEventListener("click", (event) => {
    if (event.target === $("viewer")) $("viewer").close();
  });
  $("viewer").addEventListener("close", () => {
    $("viewer-img").removeAttribute("src");
    current = null;
    currentKind = "annotated";
  });
  refreshEmpty();
}
