"""Chạy phát hiện té ngã trên Raspberry Pi.

    python pi_demo.py                    # Pi Camera (picamera2), không có thì dùng USB webcam
    python pi_demo.py video.mp4          # chạy trên file video (đo tốc độ + kiểm tra nhanh)
    python pi_demo.py --log run.csv      # ghi log từng frame để làm báo cáo

Cần các file cùng thư mục: fall_core.py, fall_config.json, movenet_lightning_int8.tflite, rf_fall.onnx
"""
import argparse
import functools
import json
import os
import time

import cv2
print = functools.partial(print, flush=True)  # in ngay, không mất chữ nếu tiến trình bị crash
from fall_core import MoveNet, FallDetector, onnx_predictor
from frame_sources import frames_from_camera, frames_from_video
from pipeline import DetectionPipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?", help="file video; bỏ trống để dùng camera")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--cam", type=int, default=0, help="chỉ số USB webcam khi không có Pi Camera")
    ap.add_argument("--size", default="640x480", help="độ phân giải camera")
    ap.add_argument("--log", help="ghi CSV: t, p_fall, state, pose_ms")
    ap.add_argument("--save-alarm", action="store_true", help="lưu ảnh lúc báo động")
    args = ap.parse_args()

    cfg = json.load(open("fall_config.json"))
    period = 1.0 / cfg["target_fps"]
    pose = MoveNet(cfg["movenet"], num_threads=args.threads)
    det = FallDetector(onnx_predictor(cfg["model"]), threshold=cfg["threshold"], win_s=cfg["win_s"],
                       stride_s=cfg["stride_s"], k=cfg["k"], n=cfg["n"], confirm_s=cfg["confirm_s"])
    src = frames_from_video(args.video, period) if args.video else frames_from_camera(args.size, args.cam, period)

    log = open(args.log, "w") if args.log else None
    if log:
        log.write("t,p_fall,state,pose_ms\n")

    def on_frame(t, prob, state, ms):
        log.write(f"{t:.3f},{prob:.3f},{state},{ms:.1f}\n")

    def on_alarm(event):
        cv2.imwrite(f"fall_{time.strftime('%Y%m%d_%H%M%S')}.jpg", event.raw)

    pipe = DetectionPipeline(pose, det, src, cfg["threshold"],
                             on_frame=on_frame if log else None,
                             on_alarm=on_alarm if args.save_alarm else None)
    try:
        pipe.run()
    finally:
        if log:
            log.close()
        os._exit(0)  # thoát ngay, tránh crash khi giải phóng interpreter TFLite


if __name__ == "__main__":
    main()
