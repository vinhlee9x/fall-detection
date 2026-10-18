# Phát hiện té ngã trên Raspberry Pi 4

MoveNet SinglePose Lightning int8 trích 17 keypoint. Cửa sổ 2s được gộp thành 23 đặc trưng, đưa vào Random Forest (ONNX). Hệ thống báo động khi 2/3 cửa sổ gần nhất vượt ngưỡng và người ở tư thế nằm/thấp liên tục `confirm_s` giây.

## Các file

| File | Vai trò |
|---|---|
| `movenet_lightning_int8.tflite` | model trích keypoint |
| `rf_fall.onnx` | Random Forest đã train (Colab) |
| `fall_config.json` | FPS, cửa sổ, ngưỡng, k/n, confirm_s |
| `fall_core.py` | MoveNet + smart crop, đặc trưng, FallDetector (dùng chung với Colab) |
| `pi_demo.py` | chạy realtime với Pi Camera / USB webcam (CLI, không web) |
| `fall_dashboard.py` | dashboard web: video + khung xương, số đo Pi, ảnh báo động, Telegram |
| `pipeline.py`, `frame_sources.py`, `overlay.py` | vòng lặp phát hiện, nguồn frame, vẽ khung xương |
| `web_app.py`, `event_bus.py`, `web/` | server Flask (MJPEG + SSE) và giao diện tĩnh |
| `system_metrics.py`, `alarm_store.py` | số đo Pi, kho ảnh báo động (`alarms/`) |
| `dashboard_config.py`, `telegram_notifier.py` | cấu hình (`dashboard_config.json`) và gửi Telegram |
| `test_video.py` | chạy trên file video, xuất video có vẽ khung xương + p_fall |
| `install_pi.sh` | cài đặt + kiểm tra (+ dịch vụ tự chạy) |

## Cài đặt

Cần Raspberry Pi OS **64-bit** (Lite cũng được).

```bash
ssh pi@raspberrypi.local
hostname -I
mkdir -p ~/fall && cd ~/fall
unzip -o ~/fall_pi_deploy.zip
bash install_pi.sh
```

## Chạy

```bash
cd ~/fall && source venv/bin/activate
python test_video.py test.mp4               # kiểm tra trên video -> test_result.mp4, test_result.csv
python pi_demo.py --log run.csv             # camera realtime, Ctrl+C để dừng
python pi_demo.py --save-alarm              # lưu ảnh lúc báo động
python pi_demo.py --cam 0 --size 640x480    # USB webcam
```

Tự chạy khi bật Pi: `bash install_pi.sh --service` (chạy `fall_dashboard.py`), xem log bằng `journalctl -u fall-detector -f`.

## Dashboard web

```bash
python fall_dashboard.py                     # camera
python fall_dashboard.py test.mp4 --loop     # video lặp lại để thử
```

Mở `http://<ip-pi>:8080` (lấy IP bằng `hostname -I`; `http://<tên-pi>.local:8080` không chạy trên một số máy Android). Có 3 tab: Giám sát (video, biểu đồ p_fall, số đo thiết bị), Ảnh báo động, Telegram.

- Telegram: nhập token (từ `@BotFather`) và `chat_id` ở tab Telegram, bấm Lưu rồi "Gửi thử". Mặc định tắt. Ảnh báo động có hình người sẽ được gửi tới máy chủ Telegram.
- Mật khẩu: sửa `auth.password` trong `dashboard_config.json` (file quyền 600) rồi chạy lại dịch vụ; để trống = không cần mật khẩu. Basic Auth qua HTTP là cleartext, chỉ phù hợp mạng LAN tin cậy.
- Pi không có đồng hồ thời gian thực: bật NTP (`timedatectl set-ntp true`) để giờ trên ảnh/caption đúng.
- Ảnh báo động lưu ở `alarms/`, giữ tối đa `max_alarms` (mặc định 100) bản mới nhất.
- Dev trên máy khác Pi: số đo Pi hiện "N/A"; `python tests/e2e_fake_telegram.py` chạy kịch bản với Telegram giả. Cần Python 3.11 cho `rf_fall.onnx` (opset 22).

## Số đo cho báo cáo

- Dashboard hiển thị sẵn FPS, ms/frame MoveNet, nhiệt độ, cờ throttling, CPU từng nhân, tần số, RAM, đĩa.
- `pi_demo.py` in FPS và ms/frame của MoveNet mỗi 5s, khi dừng in tổng kết.
- Nhiệt độ và throttling (chạy ở cửa sổ SSH khác): `watch -n 2 'vcgencmd measure_temp; vcgencmd get_throttled'`
- RAM và CPU: `htop`
- FPS thực tế phải gần `target_fps` trong `fall_config.json`. Nếu thấp hơn nhiều, train lại trên Colab với `TARGET_FPS` bằng FPS đo được.
