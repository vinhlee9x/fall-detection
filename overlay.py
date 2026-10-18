import cv2

from fall_core import VIS_SCORE

EDGES = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
         (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]


def draw_overlay(frame, kps, t, prob, state, thr, alarm_active):
    h, w = frame.shape[:2]
    s = max(1.0, h / 480)
    for i, j in EDGES:
        if kps[i, 2] > VIS_SCORE and kps[j, 2] > VIS_SCORE:
            cv2.line(frame, (int(kps[i, 1]), int(kps[i, 0])), (int(kps[j, 1]), int(kps[j, 0])),
                     (0, 255, 0), int(2 * s))
    for y, x, c in kps:
        if c > VIS_SCORE:
            cv2.circle(frame, (int(x), int(y)), int(3 * s), (0, 200, 255), -1)
    bx, by, bw, bh = int(10 * s), int(10 * s), int(200 * s), int(18 * s)
    cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (60, 60, 60), -1)
    cv2.rectangle(frame, (bx, by), (bx + int(bw * prob), by + bh),
                  (0, 0, 255) if prob >= thr else (0, 180, 0), -1)
    cv2.line(frame, (bx + int(bw * thr), by - 3), (bx + int(bw * thr), by + bh + 3), (255, 255, 255), 2)
    cv2.putText(frame, f"p_fall={prob:.2f}  {state}  t={t:.1f}s", (bx, by + bh + int(22 * s)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6 * s, (255, 255, 255), max(1, int(2 * s)))
    if alarm_active:
        cv2.rectangle(frame, (0, h - int(50 * s)), (w, h), (0, 0, 255), -1)
        cv2.putText(frame, "FALL DETECTED", (int(10 * s), h - int(15 * s)),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1 * s, (255, 255, 255), max(2, int(3 * s)))
    return frame
