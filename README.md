# Phát hiện té ngã trên Raspberry Pi 4

MoveNet SinglePose Lightning int8 trích 17 keypoint. Cửa sổ 2s được gộp thành 23 đặc trưng, đưa vào Random Forest (ONNX). Hệ thống báo động khi 2/3 cửa sổ gần nhất vượt ngưỡng và người ở tư thế nằm/thấp liên tục `confirm_s` giây.

## Các file

| File | Vai trò |
|---|---|
| `movenet_lightning_int8.tflite` | model trích keypoint |
| `rf_fall.onnx` | Random Forest đã train (Colab) |
| `fall_config.json` | FPS, cửa sổ, ngưỡng, k/n, confirm_s |
| `fall_core.py` | MoveNet + smart crop, đặc trưng, FallDetector (dùng chung với Colab) |
| `pi_demo.py` | chạy realtime với Pi Camera / USB webcam |
| `test_video.py` | chạy trên file video, xuất video có vẽ khung xương + p_fall |
| `install_pi.sh` | cài đặt + kiểm tra (+ dịch vụ tự chạy) |

## Cài đặt

Cần Raspberry Pi OS **64-bit** (Lite cũng được).

```bash
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

Tự chạy khi bật Pi: `bash install_pi.sh --service`, xem log bằng `journalctl -u fall-detector -f`.

## Số đo cho báo cáo

- `pi_demo.py` in FPS và ms/frame của MoveNet mỗi 5s, khi dừng in tổng kết.
- Nhiệt độ và throttling (chạy ở cửa sổ SSH khác): `watch -n 2 'vcgencmd measure_temp; vcgencmd get_throttled'`
- RAM và CPU: `htop`
- FPS thực tế phải gần `target_fps` trong `fall_config.json`. Nếu thấp hơn nhiều, train lại trên Colab với `TARGET_FPS` bằng FPS đo được.
