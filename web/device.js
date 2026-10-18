import { $, el, fmt, formatDuration } from "./dom.js";

const NOW_LABELS = {
  undervoltage: "Sụt áp",
  freq_capped: "Giới hạn xung",
  throttled: "Đang giảm xung",
  soft_temp_limit: "Chạm ngưỡng nhiệt mềm",
};
const PAST_LABELS = {
  undervoltage: "Từng sụt áp",
  freq_capped: "Từng giới hạn xung",
  throttled: "Từng giảm xung",
  soft_temp_limit: "Từng chạm ngưỡng nhiệt",
};

const rows = {};
let coresBox = null;
let coreItems = [];

function addRow(parent, key, label) {
  const row = el("div", "dev-row");
  const dt = el("dt", null, label);
  const dd = el("dd", null, "N/A");
  row.append(dt, dd);
  parent.append(row);
  rows[key] = dd;
  return dd;
}

export function initDevice() {
  const root = $("device");
  const list = el("dl");
  list.style.margin = "0";
  addRow(list, "temp", "Nhiệt độ CPU");
  addRow(list, "throttle", "Giảm xung");
  addRow(list, "cpu", "CPU tổng");
  coresBox = el("div", "cores");
  list.append(coresBox);
  addRow(list, "freq", "Tần số CPU");
  addRow(list, "ram", "RAM");
  addRow(list, "disk", "Ổ đĩa");
  addRow(list, "proc", "Tiến trình");
  addRow(list, "load", "Tải trung bình");
  addRow(list, "uptime", "Thời gian chạy");
  root.append(list);
}

function renderFlags(throttled) {
  const dd = rows.throttle;
  dd.textContent = "";
  if (!throttled) {
    dd.textContent = "N/A";
    return;
  }
  const box = el("div", "flags");
  const now = throttled.now || [];
  const past = (throttled.since_boot || []).filter((name) => !now.includes(name));
  for (const name of now) box.append(el("span", "flag flag-now", NOW_LABELS[name] || name));
  for (const name of past) box.append(el("span", "flag flag-past", PAST_LABELS[name] || name));
  if (!now.length && !past.length) box.append(el("span", "flag", "Bình thường"));
  dd.append(box);
}

function renderCores(values) {
  const list = Array.isArray(values) ? values : [];
  while (coreItems.length < list.length) {
    const row = el("div", "core");
    const label = el("span", null, "Nhân " + coreItems.length);
    const bar = el("div", "bar");
    const fill = el("i");
    bar.append(fill);
    const num = el("b", null, "N/A");
    row.append(label, bar, num);
    coresBox.append(row);
    coreItems.push({ fill, num, row });
  }
  while (coreItems.length > list.length) coreItems.pop().row.remove();
  list.forEach((value, i) => {
    coreItems[i].fill.style.width = Math.min(100, Math.max(0, value)) + "%";
    coreItems[i].num.textContent = fmt(value, 0, "%");
  });
}

export function renderDevice(sys) {
  const temp = sys.cpu_temp_c;
  rows.temp.textContent = fmt(temp, 1, "°C");
  rows.temp.className = temp >= 80 ? "v-hot" : temp >= 70 ? "v-warn" : "";
  renderFlags(sys.throttled);
  rows.cpu.textContent = fmt(sys.cpu_percent, 0, "%");
  renderCores(sys.cpu_percent_per_core);
  rows.freq.textContent = fmt(sys.cpu_freq_mhz, 0, "MHz");
  rows.ram.textContent = sys.ram_total_mb === null || sys.ram_total_mb === undefined
    ? "N/A"
    : fmt(sys.ram_used_mb, 0) + " / " + fmt(sys.ram_total_mb, 0) + " MB (" + fmt(sys.ram_percent, 0, "%") + ")";
  rows.disk.textContent = sys.disk_total_gb === null || sys.disk_total_gb === undefined
    ? "N/A"
    : fmt(sys.disk_used_gb, 1) + " / " + fmt(sys.disk_total_gb, 1) + " GB (" + fmt(sys.disk_percent, 0, "%") + ")";
  rows.proc.textContent = "CPU " + fmt(sys.proc_cpu_percent, 0, "%") + " · RAM " + fmt(sys.proc_rss_mb, 0, "MB");
  rows.load.textContent = Array.isArray(sys.load_avg) ? sys.load_avg.map((v) => v.toFixed(2)).join(" · ") : "N/A";
  rows.uptime.textContent = formatDuration(sys.uptime_s);
}
