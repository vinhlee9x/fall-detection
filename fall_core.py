"""fall_core.py — lõi dùng chung cho Colab (train) và Raspberry Pi (inference).

Chép nguyên file này sang Pi để đặc trưng lúc train và lúc chạy thật giống hệt nhau.
Phụ thuộc: numpy, opencv; MoveNet cần ai-edge-litert (hoặc tflite-runtime / tensorflow);
FallDetector cần onnxruntime.
"""
from collections import deque
import math
import os
import numpy as np
import cv2

# ---- chỉ số keypoint MoveNet (COCO 17) ----
NOSE, L_SH, R_SH, L_HIP, R_HIP, L_ANK, R_ANK = 0, 5, 6, 11, 12, 15, 16
MIN_CROP_SCORE = 0.2   # ngưỡng dùng cho smart crop (theo tutorial MoveNet)
VIS_SCORE = 0.3        # ngưỡng coi keypoint là "nhìn thấy" khi tính đặc trưng


# =====================================================================
# 1. MoveNet + smart crop
# =====================================================================
def load_interpreter(model_path, num_threads=4):
    """Chọn bộ chạy TFLite qua biến môi trường FALL_TFLITE_BACKEND = auto | litert | tflite_runtime | tf.
    auto (mặc định): ai-edge-litert -> tflite-runtime -> tensorflow."""
    backend = os.environ.get("FALL_TFLITE_BACKEND", "auto").lower()
    Interpreter = None
    if backend in ("auto", "litert"):
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            if backend == "litert":
                raise
    if Interpreter is None and backend in ("auto", "tflite_runtime"):
        try:
            from tflite_runtime.interpreter import Interpreter
        except ImportError:
            if backend == "tflite_runtime":
                raise
    if Interpreter is None:
        import tensorflow as tf
        Interpreter = tf.lite.Interpreter
    print(f"[fall_core] TFLite backend: {Interpreter.__module__}", flush=True)
    it = Interpreter(model_path=model_path, num_threads=num_threads)
    it.allocate_tensors()
    return it


def init_crop_region(h, w):
    """Crop mặc định: cả ảnh, đệm thành hình vuông (toạ độ chuẩn hoá)."""
    if w > h:
        bh, bw = w / h, 1.0
        y_min, x_min = (h / 2 - w / 2) / h, 0.0
    else:
        bh, bw = 1.0, h / w
        y_min, x_min = 0.0, (w / 2 - h / 2) / w
    return dict(y_min=y_min, x_min=x_min, y_max=y_min + bh, x_max=x_min + bw,
                height=bh, width=bw)


def _torso_visible(kps):
    return ((kps[L_HIP, 2] > MIN_CROP_SCORE or kps[R_HIP, 2] > MIN_CROP_SCORE) and
            (kps[L_SH, 2] > MIN_CROP_SCORE or kps[R_SH, 2] > MIN_CROP_SCORE))


def determine_crop_region(kps_px, h, w):
    """kps_px: (17,3) [y_px, x_px, score] trên ảnh gốc."""
    if not _torso_visible(kps_px):
        return init_crop_region(h, w)
    cy = (kps_px[L_HIP, 0] + kps_px[R_HIP, 0]) / 2
    cx = (kps_px[L_HIP, 1] + kps_px[R_HIP, 1]) / 2
    torso = [L_SH, R_SH, L_HIP, R_HIP]
    ty = np.max(np.abs(cy - kps_px[torso, 0]))
    tx = np.max(np.abs(cx - kps_px[torso, 1]))
    good = kps_px[:, 2] >= MIN_CROP_SCORE
    by = np.max(np.abs(cy - kps_px[good, 0])) if good.any() else 0.0
    bx = np.max(np.abs(cx - kps_px[good, 1])) if good.any() else 0.0
    half = max(tx * 1.9, ty * 1.9, by * 1.2, bx * 1.2)
    half = min(half, max(cx, w - cx, cy, h - cy))
    if half > max(w, h) / 2:
        return init_crop_region(h, w)
    side = 2 * half
    y_min, x_min = (cy - half) / h, (cx - half) / w
    return dict(y_min=y_min, x_min=x_min, y_max=y_min + side / h, x_max=x_min + side / w,
                height=side / h, width=side / w)


def crop_and_resize(rgb, crop, size):
    """Cắt vùng crop (có thể vượt biên → đệm đen) và resize về size×size."""
    h, w = rgb.shape[:2]
    x0, y0 = crop["x_min"] * w, crop["y_min"] * h
    x1, y1 = crop["x_max"] * w, crop["y_max"] * h
    sx, sy = size / max(x1 - x0, 1e-6), size / max(y1 - y0, 1e-6)
    M = np.array([[sx, 0, -x0 * sx], [0, sy, -y0 * sy]], dtype=np.float32)
    return cv2.warpAffine(rgb, M, (size, size), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


class MoveNet:
    """MoveNet SinglePose (TFLite). Gọi model(frame_bgr) -> (17,3) [y_px, x_px, score]."""

    def __init__(self, model_path, num_threads=4, smart_crop=True):
        self.it = load_interpreter(model_path, num_threads)
        inp = self.it.get_input_details()[0]
        self.in_idx, self.in_dtype = inp["index"], inp["dtype"]
        self.size = int(inp["shape"][1])
        self.out_idx = self.it.get_output_details()[0]["index"]
        self.smart_crop = smart_crop
        self.crop = None

    def reset(self):
        self.crop = None

    def __call__(self, frame_bgr):
        h, w = frame_bgr.shape[:2]
        if self.crop is None or not self.smart_crop:
            self.crop = init_crop_region(h, w)
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = crop_and_resize(rgb, self.crop, self.size)[None].astype(self.in_dtype)
        self.it.set_tensor(self.in_idx, img)
        self.it.invoke()
        k = self.it.get_tensor(self.out_idx)[0, 0].astype(np.float32)  # (17,3) theo crop
        c = self.crop
        out = np.empty_like(k)
        out[:, 0] = (c["y_min"] + k[:, 0] * c["height"]) * h
        out[:, 1] = (c["x_min"] + k[:, 1] * c["width"]) * w
        out[:, 2] = k[:, 2]
        self.crop = determine_crop_region(out, h, w)
        return out


# =====================================================================
# 2. Đặc trưng: chuỗi theo frame -> vector cho cửa sổ 2s
# =====================================================================
FEATURE_NAMES = [
    "vy_max", "vy_min", "vy_mean", "vy_std", "ay_absmax", "vx_absmax",
    "theta_first", "theta_last", "theta_max", "theta_delta",
    "ar_first", "ar_last", "ar_delta",
    "headh_first", "headh_last", "headh_delta",
    "hipy_delta", "hipy_drop_from_top", "cy_delta", "bboxh_ratio_last",
    "conf_min", "conf_drop", "miss_frac",
]
N_FEATURES = len(FEATURE_NAMES)


def _mean_visible(kps, idx):
    sel = kps[idx]
    m = sel[:, 2] > VIS_SCORE
    if not m.any():
        return np.nan, np.nan
    return sel[m, 0].mean(), sel[m, 1].mean()


def frame_quantities(kps):
    """Đại lượng thô của 1 frame (pixel). NaN nếu không thấy keypoint cần thiết."""
    hy, hx = _mean_visible(kps, [L_HIP, R_HIP])
    sy, sx = _mean_visible(kps, [L_SH, R_SH])
    vis = kps[:, 2] > VIS_SCORE
    if vis.sum() >= 3:
        ys, xs = kps[vis, 0], kps[vis, 1]
        bw, bh = xs.max() - xs.min(), ys.max() - ys.min()
        cy = ys.mean()
    else:
        bw = bh = cy = np.nan
    if np.isnan(hy) or np.isnan(sy):
        L = theta = np.nan
    else:
        dy, dx = sy - hy, sx - hx                       # vai - hông; đứng thẳng: dy < 0
        L = math.hypot(dx, dy)
        theta = math.degrees(math.atan2(abs(dx), -dy))  # 0° đứng, 90° nằm
    ny = kps[NOSE, 0] if kps[NOSE, 2] > VIS_SCORE else np.nan
    return [hy, hx, cy, L, theta, bw, bh, ny, float(kps[:, 2].mean()), float(vis.sum() < 5)]


def _fill_nan(t, x):
    m = ~np.isnan(x)
    if m.all():
        return x
    if not m.any():
        return np.zeros_like(x)
    return np.interp(t, t[m], x[m])


def _smooth(x, k=3):
    if len(x) < k:
        return x
    pad = np.pad(x, (k // 2, k // 2), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


def window_features(t, kps_seq, img_h):
    """t: (T,) giây; kps_seq: (T,17,3) pixel; img_h: chiều cao ảnh.
    Trả về vector N_FEATURES (float32). Khoảng cách chia cho chiều dài thân -> bất biến khoảng cách."""
    t = np.asarray(t, dtype=np.float64)
    q = np.array([frame_quantities(k) for k in kps_seq], dtype=np.float64)  # (T,10)
    hy, hx, cy, L, theta, bw, bh, ny, conf, miss = q.T
    miss_frac = float(np.mean(np.isnan(hy) | np.isnan(theta) | (miss > 0)))

    Lv = L[~np.isnan(L)]
    scale = np.percentile(Lv, 90) if len(Lv) >= 2 else 0.25 * img_h  # thân dài nhất ≈ lúc đứng
    scale = max(scale, 0.05 * img_h)

    hy, hx, cy, theta, bw, bh = (_fill_nan(t, a) for a in (hy, hx, cy, theta, bw, bh))
    headh = (hy - ny) / scale  # >0: đầu cao hơn hông
    headh = _fill_nan(t, headh)
    ar = bw / np.maximum(bh, 1.0)

    if len(t) >= 3 and t[-1] > t[0]:
        vy = np.gradient(_smooth(hy / scale), t)   # thân/giây, dương = đi xuống
        vx = np.gradient(_smooth(hx / scale), t)
        ay = np.gradient(vy, t)
    else:
        vy = vx = ay = np.zeros_like(t)

    n = len(t)
    q4 = max(1, n // 4)
    first = lambda a: float(np.mean(a[:q4]))
    last = lambda a: float(np.mean(a[-q4:]))

    f = [
        vy.max(), vy.min(), vy.mean(), vy.std(), np.abs(ay).max(), np.abs(vx).max(),
        first(theta), last(theta), theta.max(), last(theta) - first(theta),
        first(ar), last(ar), last(ar) - first(ar),
        first(headh), last(headh), last(headh) - first(headh),
        (last(hy) - first(hy)) / scale, (last(hy) - hy.min()) / scale,
        (last(cy) - first(cy)) / scale, last(bh) / max(bh.max(), 1.0),
        conf.min(), first(conf) - last(conf), miss_frac,
    ]
    return np.nan_to_num(np.asarray(f, dtype=np.float32), nan=0.0, posinf=0.0, neginf=0.0)


def is_lying(kps, scale=None):
    """Luật trạng thái nằm/ở thấp cho 1 frame (dùng để xác nhận sau khi RF báo ngã)."""
    hy, hx, cy, L, theta, bw, bh, ny, conf, miss = frame_quantities(kps)
    if miss > 0:
        return None  # không đủ keypoint để kết luận
    horizontal = (not np.isnan(theta) and theta > 55) or (bw / max(bh, 1.0) > 1.2)
    head_low = (not np.isnan(ny) and scale and (hy - ny) / scale < 0.5)
    return bool(horizontal or head_low)


# =====================================================================
# 3. Bộ phát hiện streaming (dùng trên Pi và để đánh giá mức video)
# =====================================================================
class FallDetector:
    """push(t, kps, img_h) mỗi frame. Trả về 'alarm' khi xác nhận ngã, ngược lại None.

    Luồng: RF chấm điểm cửa sổ 2s mỗi `stride_s` -> nếu k/n cửa sổ gần nhất vượt ngưỡng
    thì vào trạng thái nghi ngờ -> nếu người ở tư thế nằm/thấp >= `confirm_s` thì báo động.
    """

    def __init__(self, predict_proba, threshold=0.5, win_s=2.0, stride_s=0.25,
                 k=2, n=3, confirm_s=1.0, confirm_ratio=0.6, suspect_timeout_s=4.0,
                 cooldown_s=10.0):
        self.predict_proba = predict_proba  # hàm: (1,N_FEATURES) float32 -> xác suất ngã
        self.thr, self.win_s, self.stride_s = threshold, win_s, stride_s
        self.k, self.n = k, n
        self.confirm_s, self.confirm_ratio = confirm_s, confirm_ratio
        self.suspect_timeout_s, self.cooldown_s = suspect_timeout_s, cooldown_s
        self.reset()

    def reset(self):
        self.buf = deque()
        self.hits = deque(maxlen=self.n)
        self.next_eval = None
        self.state, self.t_event, self.t_alarm = "normal", None, -1e9
        self.lying = deque()
        self.last_prob = 0.0
        self.scale = None

    def push(self, t, kps, img_h):
        self.buf.append((t, kps))
        while self.buf and t - self.buf[0][0] > self.win_s:
            self.buf.popleft()
        if self.next_eval is None:
            self.next_eval = t + self.win_s

        if t >= self.next_eval:
            self.next_eval += self.stride_s
            ts = np.array([b[0] for b in self.buf])
            if len(ts) >= 4 and ts[-1] - ts[0] >= 0.8 * self.win_s:
                ks = np.stack([b[1] for b in self.buf])
                x = window_features(ts, ks, img_h)[None]
                self.last_prob = float(self.predict_proba(x))
                self.hits.append(self.last_prob >= self.thr)
                Ls = [frame_quantities(k)[3] for k in ks]
                Ls = [v for v in Ls if not np.isnan(v)]
                if Ls:
                    self.scale = float(np.percentile(Ls, 90))

        if self.state == "normal":
            if (sum(self.hits) >= self.k and t - self.t_alarm > self.cooldown_s):
                self.state, self.t_event = "suspect", t
                self.lying.clear()
        elif self.state == "suspect":
            self.lying.append((t, is_lying(kps, self.scale)))
            while self.lying and t - self.lying[0][0] > self.confirm_s:
                self.lying.popleft()
            span = self.lying[-1][0] - self.lying[0][0] if len(self.lying) > 1 else 0
            known = [v for _, v in self.lying if v is not None]
            ratio = (sum(known) / len(known)) if known else 1.0  # mất dấu sau cú ngã -> coi là nằm
            if span >= 0.9 * self.confirm_s and ratio >= self.confirm_ratio:
                self.state, self.t_alarm = "normal", t
                self.hits.clear()
                return "alarm"
            if t - self.t_event > self.suspect_timeout_s:
                self.state = "normal"
                self.hits.clear()
        return None


def onnx_predictor(onnx_path):
    """Trả về hàm x(1,N) -> xác suất lớp 'fall' từ model ONNX (skl2onnx, zipmap=False)."""
    import onnxruntime as ort
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    prob_name = [o.name for o in sess.get_outputs() if "prob" in o.name.lower()][0]

    def f(x):
        return sess.run([prob_name], {in_name: x.astype(np.float32)})[0][0, 1]
    return f
