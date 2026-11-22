"""Sports reframing prototype (EXPERIMENT - not used by production).

Problem: the production cropper (clipper/crop.py) follows faces; for sports it falls back to a fixed centre
crop, so in 9:16 the ball / play leaves the frame. This prototype follows the ACTION instead:

  1. Dense optical flow (Farneback) on a downscaled frame.
  2. Subtract the camera's own pan (median flow) so only things moving *relative to the camera* count
     (the ball carrier, the ball, a swing) - broadcast cameras already pan with the play.
  3. Motion energy per column -> horizontal centre of mass (weighted toward the strongest cluster).
  4. Scene-cut detection (histogram jump) resets the tracker so replays / angle changes snap, not drift.
  5. Camera-operator smoothing: dead zone + max pan speed + critically damped follow.

Outputs <name>_tracked.mp4 (9:16) and <name>_compare.mp4 (fixed centre | tracked, side by side).

Usage:  python motion_reframe.py <video> [--start 30] [--dur 20] [--out DIR]
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import cv2
import numpy as np

AW = 320  # analysis width


def analyse(path: str, start: float, dur: float):
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    n = int(dur * fps)
    ah = int(H * AW / W)
    prev, prev_hist = None, None
    xs, conf, cuts = [], [], []
    for i in range(n):
        ok, fr = cap.read()
        if not ok:
            break
        small = cv2.resize(fr, (AW, ah))
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([small], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
        hist = cv2.normalize(hist, hist).flatten()
        cut = prev_hist is not None and cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA) > 0.45
        prev_hist = hist
        if prev is None or cut:
            xs.append(np.nan); conf.append(0.0); cuts.append(cut); prev = g
            continue
        flow = cv2.calcOpticalFlowFarneback(prev, g, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        prev = g
        flow -= np.median(flow.reshape(-1, 2), axis=0)          # remove camera pan
        mag = np.linalg.norm(flow, axis=2)
        mag[: int(ah * 0.08)] = 0                                 # ignore score bug / ticker bands
        mag[int(ah * 0.90):] = 0
        thr = max(np.percentile(mag, 97), 0.6)
        mask = np.where(mag > thr, mag, 0)
        col = mask.sum(axis=0)
        if col.sum() < 1e-3:
            xs.append(np.nan); conf.append(0.0); cuts.append(False); continue
        col = cv2.GaussianBlur(col.reshape(1, -1).astype(np.float32), (0, 0), AW * 0.04).ravel()
        peak = int(np.argmax(col))                                # strongest cluster ...
        lo, hi = max(0, peak - AW // 6), min(AW, peak + AW // 6)
        win = col[lo:hi]
        x = (np.arange(lo, hi) * win).sum() / win.sum()           # ... and its centre of mass
        xs.append(x * W / AW); conf.append(float(win.sum() / col.sum())); cuts.append(False)
    cap.release()
    return np.array(xs), np.array(conf), np.array(cuts), fps, W, H


def smooth(xs, conf, cuts, W, crop_w, fps):
    lo, hi = crop_w / 2, W - crop_w / 2
    out, pos, vel = [], W / 2, 0.0
    # CALM_V1: wide dead zone, slow pans, and the aim only moves when the action STAYS somewhere new
    dead, vmax = crop_w * 0.22, W * 0.35 / fps
    hold = int(0.7 * fps)
    target, cand, since = W / 2, W / 2, 0
    med = []
    for x, c, cut in zip(xs, conf, cuts):
        if not np.isnan(x) and c > 0.25:
            med = (med + [x])[-int(0.5 * fps):]                   # 0.5 s median ignores twitches
            m = float(np.median(med))
            if abs(m - cand) > dead * 0.5:
                cand, since = m, 0
            else:
                since += 1
            if since >= hold and abs(cand - target) > dead:
                target = cand
        if cut:
            med, since = [], 0
            pos, vel = np.clip(target, lo, hi), 0.0               # snap on a cut
        err = target - pos
        if abs(err) > dead * 0.3:
            k, d = 0.03, 0.7                                      # softer spring, more damping
            vel = vel * d + k * (err - np.sign(err) * dead)
            vel = float(np.clip(vel, -vmax, vmax))
        else:
            vel *= 0.6
        pos = float(np.clip(pos + vel, lo, hi))
        out.append(pos)
    return np.array(out)


def render(path, start, dur, centers, fps, W, H, out: Path, wide: float = 1.0):
    ow, oh = 1080, 1920
    crop_w = min(W, int(round(H * 9 / 16 * wide))) // 2 * 2
    box_h = int(round(ow * H / crop_w)) // 2 * 2          # height of the sharp band when wider than 9:16
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    tmp_t, tmp_c = out.with_suffix(".t.mp4"), out.with_suffix(".c.mp4")
    vt = cv2.VideoWriter(str(tmp_t), cv2.VideoWriter_fourcc(*"mp4v"), fps, (ow, oh))
    vc = cv2.VideoWriter(str(tmp_c), cv2.VideoWriter_fourcc(*"mp4v"), fps, (540 * 2, 960))
    for cx in centers:
        ok, fr = cap.read()
        if not ok:
            break
        x0 = int(np.clip(cx - crop_w / 2, 0, W - crop_w))
        if wide <= 1.0:
            tr = cv2.resize(fr[:, x0:x0 + crop_w], (ow, oh))
        else:  # WIDE_V1: sharp wider band in the middle, blurred cover fill above/below
            bw = int(round(H * 9 / 16)) // 2 * 2
            bx = int(np.clip(cx - bw / 2, 0, W - bw))
            tr = cv2.GaussianBlur(cv2.resize(fr[:, bx:bx + bw], (ow // 4, oh // 4)), (0, 0), 6)
            tr = (cv2.resize(tr, (ow, oh)) * 0.55).astype(np.uint8)
            y0 = (oh - box_h) // 2
            tr[y0:y0 + box_h] = cv2.resize(fr[:, x0:x0 + crop_w], (ow, box_h))
        f0 = (W - int(round(H * 9 / 16)) // 2 * 2) // 2
        fx = cv2.resize(fr[:, f0:f0 + int(round(H * 9 / 16)) // 2 * 2], (540, 960))
        vt.write(tr)
        both = np.hstack([fx, cv2.resize(tr, (540, 960))])
        cv2.putText(both, "fixed centre (production)", (12, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        cv2.putText(both, "motion tracked (prototype)" if wide <= 1 else f"tracked, wide x{wide:g}", (552, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        vc.write(both)
    vt.release(); vc.release(); cap.release()
    for tmp, final in ((tmp_t, out.with_name(out.stem + "_tracked.mp4")), (tmp_c, out.with_name(out.stem + "_compare.mp4"))):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp), "-ss", str(start), "-t", str(dur), "-i", path,
                        "-map", "0:v", "-map", "1:a?", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
                        "-c:a", "aac", "-shortest", str(final)], check=True)
        tmp.unlink()
    return crop_w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("--start", type=float, default=0); ap.add_argument("--dur", type=float, default=20)
    ap.add_argument("--out", default=str(Path(__file__).parent / "out"))
    ap.add_argument("--wide", type=float, default=1.0, help="1 = full-height 9:16 crop; 1.8 = ~60%% of the field, blurred fill")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    xs, conf, cuts, fps, W, H = analyse(a.video, a.start, a.dur)
    crop_w = min(W, int(round(H * 9 / 16 * a.wide))) // 2 * 2
    centers = smooth(xs, conf, cuts, W, crop_w, fps)
    name = out / f"{Path(a.video).stem[:40].strip()}_{int(a.start)}s{'_wide' if a.wide > 1 else ''}"
    render(a.video, a.start, a.dur, centers, fps, W, H, name, a.wide)
    tracked = np.isfinite(xs) & (conf > 0.25)
    print(f"frames={len(xs)} cuts={int(cuts.sum())} action-locked={tracked.mean():.0%} "
          f"pan range={centers.min():.0f}-{centers.max():.0f}px of {W}px -> {name}_compare.mp4")


if __name__ == "__main__":
    main()
