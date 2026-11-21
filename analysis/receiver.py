#!/usr/bin/env python3
"""Odbiornik strumieniowy (Moduł 2): TCP <- symulator C.

Zbiera próbki NAZWA,t,wartość; gdy czas strumienia przekroczy koniec kolejnego okna
(co 10 s), liczy cechy fizjologiczne z ostatnich 30 s i wypisuje je na bieżąco.
Po otrzymaniu END dołącza cechy z wideo (plik z gogli VR) i zapisuje CSV.

Strumienie: POLAR_RR, EMP_EDA, EMP_BVP.
Użycie: receiver.py --port 5555 --video data/P01/video.avi --out wyniki.csv
"""
import argparse, os, socket, sys, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from session import *
from video import video_frame_features, video_window_features

def serve(port):
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port)); srv.listen(1)
    print(f"[receiver] nasłuch na :{port}", flush=True)
    conn, _ = srv.accept(); srv.close()
    buf = b""
    with conn:
        while True:
            chunk = conn.recv(65536)
            if not chunk: return
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for ln in lines:
                yield ln.decode()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5555); ap.add_argument("--video", required=True)
    ap.add_argument("--out", default="stream_result.csv")
    a = ap.parse_args()
    B = {k: ([], []) for k in ("POLAR_RR", "EMP_EDA", "EMP_BVP")}
    latest = {k: 0.0 for k in B}; next_end = WIN; rows = []; n = 0

    def emit(t1):
        arr = {k: (np.array(v[0]), np.array(v[1])) for k, v in B.items()}
        r = physio_window(*arr["POLAR_RR"], *arr["EMP_EDA"], *arr["EMP_BVP"], t1 - WIN, t1)
        rows.append(r)
        print(f"[receiver] okno do {t1:5.0f}s  HR={r['hr_polar']:.1f}  RMSSD={r['rmssd']:.1f}  "
              f"EDA={r['eda_tonic']:.2f}  SCR/min={r['scr_rate']:.1f}  BVP-HR={r['bvp_hr']:.1f}", flush=True)

    for ln in serve(a.port):
        if ln == "END": break
        try: name, t, v = ln.split(","); t, v = float(t), float(v)
        except ValueError: continue
        if name not in B: continue
        B[name][0].append(t); B[name][1].append(v); latest[name] = t; n += 1
        while min(latest.values()) >= next_end:           # wszystkie strumienie doszły do końca okna
            emit(next_end); next_end += STEP
    print(f"[receiver] odebrano {n} próbek; analiza wideo...", flush=True)
    vr, fps = video_frame_features(a.video)
    for r in rows:
        r.update(video_window_features(vr, fps, r["t_end"] - WIN, r["t_end"]))
        r["load_index"], gs = load_index(r)
        r.update({f"idx_{k}": v for k, v in gs.items()})
    pd.DataFrame(rows).to_csv(a.out, index=False)
    print(f"[receiver] zapisano {a.out}", flush=True)

if __name__ == "__main__":
    main()
