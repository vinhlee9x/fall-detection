import { $, api } from "./dom.js";

let saved = null;

function setResult(message, ok) {
  const out = $("tg-result");
  out.textContent = message || "";
  out.className = "result" + (ok === true ? " ok" : ok === false ? " err" : "");
}

function currentValues() {
  return {
    enabled: $("tg-enabled").checked,
    chat_id: $("tg-chat").value.trim(),
    message_template: $("tg-template").value,
    token: $("tg-token").value,
  };
}

function isDirty() {
  if (!saved) return true;
  const now = currentValues();
  return now.token !== "" || now.enabled !== saved.enabled || now.chat_id !== saved.chat_id
    || now.message_template !== saved.message_template;
}

function syncButtons() {
  $("tg-test").disabled = isDirty();
}

function applyView(view) {
  saved = { enabled: view.enabled, chat_id: view.chat_id, message_template: view.message_template };
  $("tg-enabled").checked = view.enabled;
  $("tg-chat").value = view.chat_id;
  $("tg-template").value = view.message_template;
  $("tg-token").value = "";
  $("tg-token").placeholder = view.has_token ? "Đã lưu " + view.token_hint : "Dán token từ BotFather";
  syncButtons();
}

export async function loadTelegram() {
  const res = await api("/api/notify");
  if (res.ok && res.body) applyView(res.body);
}

async function save(event) {
  event.preventDefault();
  const values = currentValues();
  const patch = { enabled: values.enabled, chat_id: values.chat_id, message_template: values.message_template };
  if (values.token) patch.bot_token = values.token.trim();
  $("tg-save").disabled = true;
  setResult("Đang lưu…");
  const res = await api("/api/notify", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  $("tg-save").disabled = false;
  if (res.ok && res.body) {
    applyView(res.body);
    setResult("Đã lưu", true);
  } else {
    setResult((res.body && res.body.error) || "Lưu thất bại (HTTP " + res.status + ")", false);
  }
}

async function sendTest() {
  $("tg-test").disabled = true;
  setResult("Đang gửi thử…");
  const res = await api("/api/notify/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  const message = res.body && res.body.message ? res.body.message : "Gửi thử thất bại (HTTP " + res.status + ")";
  setResult(message, res.ok && res.body && res.body.ok === true);
  syncButtons();
}

export function initTelegram() {
  $("tg-form").addEventListener("submit", save);
  $("tg-test").addEventListener("click", sendTest);
  for (const id of ["tg-enabled", "tg-token", "tg-chat", "tg-template"]) {
    $(id).addEventListener("input", syncButtons);
    $(id).addEventListener("change", syncButtons);
  }
  syncButtons();
}
