export const $ = (id) => document.getElementById(id);

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function fmt(value, digits, unit) {
  if (value === null || value === undefined || Number.isNaN(value)) return "N/A";
  const number = typeof value === "number" ? value.toFixed(digits === undefined ? 0 : digits) : String(value);
  return unit ? number + " " + unit : number;
}

export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "N/A";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return (d ? d + " ngày " : "") + h + " giờ " + m + " phút";
}

export async function api(path, options) {
  const response = await fetch(path, options);
  let body = null;
  try {
    body = await response.json();
  } catch (e) {
    body = null;
  }
  return { ok: response.ok, status: response.status, body };
}
