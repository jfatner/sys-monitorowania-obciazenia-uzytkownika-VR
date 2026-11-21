#!/usr/bin/env python3
"""Generator syntetycznych sesji VR (zastępuje historyczne pliki Polar/Empatica/wideo).

Dla każdego uczestnika tworzy katalog data/Pxx/ z plikami:
  polar_rr.csv        t,rr_ms        (odstępy RR, zdarzeniowo - jak Polar H10)
  empatica_eda.csv    t,eda_uS       (4 Hz)
  empatica_bvp.csv    t,bvp          (64 Hz)
  video.avi           320x240, 10 fps (przechwycony obraz z gogli VR - syntetyczny)
  truth.csv           t,stress,n_objects,speed   (prawda terenowa do walidacji algorytmów)
  meta.json           parametry uczestnika
Wszystko sterowane jednym ukrytym profilem "obciążenia" s(t) w [0,1].
"""
import argparse, json, os
import numpy as np
import cv2

def stress_profile(rng, dur, gain):
    t = np.arange(0, dur, 0.1)
    ramp = np.clip(t / dur, 0, 1)
    s = 0.15 + 0.45 * ramp
    for _ in range(rng.integers(2, 4)):          # krótkie zadania trudne
        c, w = rng.uniform(0.2, 0.9) * dur, rng.uniform(6, 14)
        s += 0.35 * np.exp(-0.5 * ((t - c) / w) ** 2)
    return t, np.clip(gain * s, 0, 1)

def gen_rr(rng, dur, tfun):
    beats, rr_list, t = [], [], 0.0
    ph = rng.uniform(0, 2 * np.pi)
    while t < dur:
        s = tfun(t)
        hr = 65 + 35 * s
        rsa = (1 - 0.8 * s) * 45 * np.sin(2 * np.pi * 0.25 * t + ph)       # oddech 0.25 Hz
        lf = (10 + 20 * s) * np.sin(2 * np.pi * 0.1 * t)                    # fala Mayera
        rr = 60000 / hr + rsa + lf + rng.normal(0, 8 * (1 - 0.5 * s))
        t += rr / 1000
        beats.append(t); rr_list.append(rr)
    return np.array(beats), np.array(rr_list)

def gen_eda(rng, dur, tfun, fs=4):
    t = np.arange(0, dur, 1 / fs)
    s = np.array([tfun(x) for x in t])
    eda = 2 + 4 * s
    kernel_t = np.arange(0, 15, 1 / fs)
    kernel = (np.exp(-kernel_t / 3.0) - np.exp(-kernel_t / 0.75)); kernel /= kernel.max()
    imp = np.zeros_like(t)
    rate = (0.4 + 12 * s) / 60 / fs                                          # SCR / próbkę
    imp[rng.random(len(t)) < rate] = 1
    amp = rng.uniform(0.3, 1.2, len(t))
    scr = np.convolve(imp * amp, kernel)[:len(t)]
    return t, eda + scr + rng.normal(0, 0.02, len(t))

def gen_bvp(rng, dur, beats, tfun, fs=64):
    t = np.arange(0, dur, 1 / fs)
    idx = np.interp(t, beats, np.arange(len(beats)), left=0)
    ph = 2 * np.pi * idx
    s = np.array([tfun(x) for x in t[::8]]); s = np.interp(t, t[::8], s)
    sig = np.sin(ph) + 0.35 * np.sin(2 * ph + 1.0)
    sig += 0.5 * np.sin(2 * np.pi * 0.08 * t)                                # dryf
    sig += rng.normal(0, 0.08 + 0.1 * s, len(t))
    # artefakty ruchowe: skoki rosnące ze stresem
    for _ in range(int(dur / 20 * (0.5 + 2 * s.mean()))):
        c = rng.integers(0, len(t) - 40)
        sig[c:c + 40] += rng.normal(0, 1.2, 40)
    return t, sig

def gen_video(path, rng, dur, tfun, fps=10, w=320, h=240):
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    n_max = 14
    pos = rng.uniform([20, 20], [w - 20, h - 20], (n_max, 2))
    ang = rng.uniform(0, 2 * np.pi, n_max)
    rad = rng.integers(7, 14, n_max)
    col = rng.integers(120, 256, (n_max, 3))
    yy, xx = np.mgrid[0:h, 0:w]
    bg = (25 + 25 * (yy / h) + 10 * np.sin(xx / 40.0)).astype(np.uint8)
    bg = cv2.merge([bg, bg, (bg * 1.2).clip(0, 255).astype(np.uint8)])
    truth, cam = [], np.zeros(2)
    for f in range(int(dur * fps)):
        t = f / fps; s = tfun(t)
        n = 3 + int(round(8 * s)); speed = 1 + 5 * s
        cam = 0.7 * cam + rng.normal(0, 3.0 * s, 2)                          # drżenie głowy
        M = np.float32([[1, 0, cam[0]], [0, 1, cam[1]]])
        frame = cv2.warpAffine(bg, M, (w, h), borderMode=cv2.BORDER_REFLECT)
        frame = frame.astype(np.int16) + rng.normal(0, 2, frame.shape).astype(np.int16)
        frame = frame.clip(0, 255).astype(np.uint8)
        ang += rng.normal(0, 0.15, n_max)
        pos += speed * np.stack([np.cos(ang), np.sin(ang)], 1)
        for k in range(n_max):                                               # odbicia od ścian
            for d, lim in ((0, w), (1, h)):
                if pos[k, d] < rad[k] or pos[k, d] > lim - rad[k]:
                    ang[k] = np.pi - ang[k] if d == 0 else -ang[k]
                    pos[k, d] = np.clip(pos[k, d], rad[k], lim - rad[k])
        for k in range(n):
            c = tuple(int(x) for x in col[k])
            p = (int(pos[k, 0] + cam[0]), int(pos[k, 1] + cam[1]))
            if k % 2: cv2.circle(frame, p, int(rad[k]), c, -1)
            else: cv2.rectangle(frame, (p[0] - rad[k], p[1] - rad[k]), (p[0] + rad[k], p[1] + rad[k]), c, -1)
        vw.write(frame)
        truth.append((t, s, n, speed))
    vw.release()
    return np.array(truth)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data"); ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--dur", type=float, default=120); ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    master = np.random.default_rng(a.seed)
    for k in range(1, a.n + 1):
        rng = np.random.default_rng(master.integers(1 << 31))
        gain = rng.uniform(0.6, 1.3)
        d = os.path.join(a.out, f"P{k:02d}"); os.makedirs(d, exist_ok=True)
        tg, sg = stress_profile(rng, a.dur, gain)
        tfun = lambda x, tg=tg, sg=sg: float(np.interp(x, tg, sg))
        beats, rr = gen_rr(rng, a.dur, tfun)
        np.savetxt(f"{d}/polar_rr.csv", np.c_[beats, rr], delimiter=",", header="t,rr_ms", comments="", fmt="%.4f")
        te, eda = gen_eda(rng, a.dur, tfun)
        np.savetxt(f"{d}/empatica_eda.csv", np.c_[te, eda], delimiter=",", header="t,eda_uS", comments="", fmt="%.5f")
        tb, bvp = gen_bvp(rng, a.dur, beats, tfun)
        np.savetxt(f"{d}/empatica_bvp.csv", np.c_[tb, bvp], delimiter=",", header="t,bvp", comments="", fmt="%.5f")
        truth = gen_video(f"{d}/video.avi", rng, a.dur, tfun)
        np.savetxt(f"{d}/truth.csv", truth, delimiter=",", header="t,stress,n_objects,speed", comments="", fmt="%.4f")
        json.dump({"participant": f"P{k:02d}", "gain": gain, "dur": a.dur, "synthetic": True},
                  open(f"{d}/meta.json", "w"))
        print("OK", d, f"mean stress {sg.mean():.2f}")

if __name__ == "__main__":
    main()
