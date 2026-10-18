#!/usr/bin/env bash
# Cài môi trường chạy phát hiện té ngã trên Raspberry Pi 4 (Raspberry Pi OS 64-bit: Bookworm hoặc Trixie).
# Chạy lại nhiều lần không lỗi.
#   bash install_pi.sh              # cài thư viện + kiểm tra
#   bash install_pi.sh --service    # cài thêm dịch vụ tự chạy khi bật Pi
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
APP_DIR="$(pwd)"
WANT_SERVICE=0
[[ "${1:-}" == "--service" ]] && WANT_SERVICE=1

echo "== 1/5 Kiểm tra file và hệ điều hành"
for f in fall_core.py pi_demo.py test_video.py fall_config.json rf_fall.onnx movenet_lightning_int8.tflite \
         overlay.py frame_sources.py pipeline.py event_bus.py system_metrics.py alarm_store.py \
         dashboard_config.py telegram_notifier.py web_app.py fall_dashboard.py \
         web/index.html web/style.css web/app.js; do
  [[ -f "$f" ]] || { echo "THIẾU FILE: $f (giải nén đủ fall_pi_deploy.zip vào $APP_DIR)"; exit 1; }
done
if [[ "$(uname -m)" != "aarch64" ]]; then
  echo "LỖI: cần Raspberry Pi OS 64-bit (aarch64), máy này là $(uname -m). ai-edge-litert không có bản 32-bit."
  exit 1
fi
. /etc/os-release && echo "OS: $PRETTY_NAME | Python hệ thống: $(python3 --version)"

echo "== 2/5 Cài gói hệ thống (apt)"
sudo apt-get update
sudo apt-get install -y --no-install-recommends python3-venv python3-pip python3-numpy python3-picamera2 ffmpeg unzip

echo "== 3/5 Tạo venv (thấy được picamera2 cài bằng apt)"
[[ -d venv ]] || python3 -m venv --system-site-packages venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install -q --upgrade pip

echo "== 4/5 Cài thư viện Python"
# Giữ đúng numpy của hệ thống để picamera2 không lỗi 'numpy.dtype size changed'.
# Bookworm có numpy 1.x -> dùng OpenCV 4.10 (OpenCV 5 bắt buộc numpy 2).
SYS_NP="$(/usr/bin/python3 -c 'import numpy; print(numpy.__version__)')"
if [[ "${SYS_NP%%.*}" -lt 2 ]]; then
  OPENCV_SPEC="opencv-python-headless<4.11"
else
  OPENCV_SPEC="opencv-python-headless"
fi
echo "numpy hệ thống: $SYS_NP -> $OPENCV_SPEC"
pip install -q "numpy==$SYS_NP" ai-edge-litert onnxruntime "$OPENCV_SPEC" flask psutil

echo "== 5/5 Kiểm tra"
python - <<'EOF'
import json, time, numpy as np, cv2, onnxruntime, flask, psutil
import fall_core
from fall_core import MoveNet, onnx_predictor, N_FEATURES
cfg = json.load(open("fall_config.json"))
print(f"numpy {np.__version__} | opencv {cv2.__version__} | onnxruntime {onnxruntime.__version__}")
pose = MoveNet(cfg["movenet"], num_threads=4)
img = np.random.randint(0, 255, (480, 640, 3), np.uint8)
pose(img); t = time.perf_counter()
for _ in range(20):
    pose(img)
print(f"MoveNet: {(time.perf_counter() - t) / 20 * 1000:.0f} ms/frame")
p = onnx_predictor(cfg["model"])(np.zeros((1, N_FEATURES), np.float32))
print(f"Random Forest ONNX OK (p={p:.2f}) | target_fps={cfg['target_fps']} threshold={cfg['threshold']}")
try:
    from picamera2 import Picamera2
    cams = Picamera2.global_camera_info()
    print("picamera2 OK | camera:", cams if cams else "chưa thấy Pi Camera (kiểm tra cáp hoặc dùng USB webcam)")
except Exception as e:
    print("picamera2 lỗi:", e, "-> vẫn dùng được USB webcam")
import os; os._exit(0)
EOF
command -v vcgencmd >/dev/null && vcgencmd measure_temp || true

if [[ $WANT_SERVICE -eq 1 ]]; then
  echo "== Cài dịch vụ systemd: fall-detector"
  sudo tee /etc/systemd/system/fall-detector.service >/dev/null <<EOF
[Unit]
Description=Fall detection (MoveNet + Random Forest)
After=network-online.target

[Service]
User=$(id -un)
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python -u fall_dashboard.py
UMask=0077
SupplementaryGroups=video
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable fall-detector
  sudo systemctl restart fall-detector
  echo "Xem log: journalctl -u fall-detector -f | Dừng: sudo systemctl stop fall-detector"
  echo "Dashboard: http://$(hostname).local:8080  hoặc  http://$(hostname -I | awk '{print $1}'):8080"
fi

echo
echo "XONG. Chạy thử:"
echo "  cd $APP_DIR && source venv/bin/activate"
echo "  python test_video.py test.mp4      # video -> test_result.mp4"
echo "  python pi_demo.py --log run.csv    # camera, Ctrl+C để dừng"
echo "  python fall_dashboard.py           # dashboard web http://<ip-pi>:8080"
