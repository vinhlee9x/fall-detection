import { $ } from "./dom.js";

const WINDOW_POINTS = 240;
const points = [];
let threshold = null;
let canvas = null;
let ctx = null;
let queued = false;

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function resize() {
  const ratio = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
}

function draw() {
  queued = false;
  if (document.hidden || canvas.offsetParent === null) return;
  const rect = canvas.getBoundingClientRect();
  if (canvas.width !== Math.round(rect.width * (window.devicePixelRatio || 1))) resize();
  const w = rect.width;
  const h = rect.height;
  ctx.clearRect(0, 0, w, h);
  const pad = 4;
  const y = (p) => pad + (1 - Math.min(1, Math.max(0, p))) * (h - 2 * pad);
  const stepX = w / (WINDOW_POINTS - 1);
  const offset = WINDOW_POINTS - points.length;

  ctx.strokeStyle = cssVar("--line");
  ctx.lineWidth = 1;
  for (const level of [0, 0.5, 1]) {
    ctx.beginPath();
    ctx.moveTo(0, y(level));
    ctx.lineTo(w, y(level));
    ctx.stroke();
  }

  let runStart = null;
  points.forEach((pt, i) => {
    const suspect = pt[2] === "suspect";
    if (suspect && runStart === null) runStart = i;
    if ((!suspect || i === points.length - 1) && runStart !== null) {
      ctx.fillStyle = "rgba(251, 191, 36, 0.22)";
      ctx.fillRect((offset + runStart) * stepX, 0, (i - runStart + 1) * stepX, h);
      runStart = null;
    }
  });

  if (threshold !== null) {
    ctx.save();
    ctx.setLineDash([6, 4]);
    ctx.strokeStyle = cssVar("--danger");
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(0, y(threshold));
    ctx.lineTo(w, y(threshold));
    ctx.stroke();
    ctx.restore();
  }

  if (points.length > 1) {
    ctx.beginPath();
    points.forEach((pt, i) => {
      const x = (offset + i) * stepX;
      if (i === 0) ctx.moveTo(x, y(pt[1]));
      else ctx.lineTo(x, y(pt[1]));
    });
    ctx.strokeStyle = cssVar("--accent");
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.stroke();
  }
}

export function requestDraw() {
  if (queued) return;
  queued = true;
  requestAnimationFrame(draw);
}

export function initChart() {
  canvas = $("chart");
  ctx = canvas.getContext("2d");
  window.addEventListener("resize", requestDraw);
  document.addEventListener("visibilitychange", requestDraw);
}

export function setThreshold(value) {
  if (typeof value === "number") threshold = value;
}

export function setHistory(history) {
  points.length = 0;
  if (Array.isArray(history)) {
    for (const pt of history.slice(-WINDOW_POINTS)) points.push(pt);
  }
  requestDraw();
}

export function pushPoint(t, p, state) {
  points.push([t, p, state]);
  if (points.length > WINDOW_POINTS) points.shift();
  requestDraw();
}
