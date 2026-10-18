import time

import cv2


def frames_from_video(path, period, loop=False, realtime=False):
    while True:
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise SystemExit(f"Không mở được video: {path}")
        vid_fps, idx, next_t = cap.get(cv2.CAP_PROP_FPS) or 30.0, -1, 0.0
        t0 = time.time()
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            idx += 1
            t = idx / vid_fps
            if t + 1e-6 < next_t:
                continue
            next_t += period
            if realtime:
                wait = t - (time.time() - t0)
                if wait > 0:
                    time.sleep(wait)
            yield t, frame
        cap.release()
        if not loop:
            return
        yield None, None


def full_fov_sensor_mode(cam, w, h):
    try:
        full = tuple(cam.camera_properties["PixelArraySize"])
        modes = [m for m in cam.sensor_modes if tuple(m["crop_limits"][2:]) == full]
    except Exception:
        return None
    if not modes:
        return None
    enough = [m for m in modes if m["size"][0] >= w and m["size"][1] >= h]
    pick = min(enough, key=lambda m: m["size"][0] * m["size"][1]) if enough else \
        max(modes, key=lambda m: m["size"][0] * m["size"][1])
    return {"output_size": tuple(pick["size"]), "bit_depth": pick["bit_depth"]}


def frames_from_camera(size, cam_index, period):
    w, h = map(int, size.split("x"))
    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        sensor = full_fov_sensor_mode(cam, w, h)
        if sensor:
            print(f"Sensor mode full-FOV: {sensor['output_size']}")
        cam.configure(cam.create_video_configuration(main={"size": (w, h), "format": "RGB888"},
                                                     sensor=sensor))
        cam.start()
        grab = cam.capture_array
        print(f"Dùng Pi Camera {w}x{h}")
    except Exception as e:
        print(f"Không dùng được Pi Camera ({e}) -> thử USB webcam {cam_index}")
        cap = cv2.VideoCapture(cam_index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

        def grab():
            ok, frame = cap.read()
            if not ok:
                raise SystemExit("Không đọc được webcam")
            return frame
    t0, next_t = time.time(), 0.0
    while True:
        now = time.time() - t0
        if now < next_t:
            time.sleep(next_t - now)
        next_t = max(next_t + period, time.time() - t0)
        frame = grab()
        yield time.time() - t0, frame
