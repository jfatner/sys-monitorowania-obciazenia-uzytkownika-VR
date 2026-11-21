#!/usr/bin/env python3
"""Odbiornik strumieniowy (Moduł 2): TCP <- symulator w C (Moduł 1).

Symulator odtwarza pliki z sesje/<ID>/wyniki/strumienie/ (tworzy je process_session.py).
Odbiornik co 10 s liczy cechy z ostatnich 30 s i wypisuje je na bieżąco, a po END dołącza
analizę obrazu z tej samej sesji i zapisuje wyniki/cechy_stream.csv.

Użycie: python analysis/receiver.py --session sesje/P01 [--port 5555]
"""
import argparse, os, socket, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
from session import load_session, analyze, physio_window
from video import analyze_app, analyze_webcam

NAMES = {"POLAR_RR": "rr", "EMP_EDA": "eda", "EMP_BVP": "bvp", "EMP_ACC": "acc", "POLAR_HR": "hr", "EMP_IBI": "ibi"}


def serve(port):
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port)); srv.listen(1)
    print(f"[receiver] nasłuch na porcie {port} - uruchom teraz symulator", flush=True)
    conn, addr = srv.accept(); srv.close()
    print(f"[receiver] połączono z {addr[0]}", flush=True)
    buf = b""
    with conn:
        while True:
            chunk = conn.recv(65536)
            if not chunk: return
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for ln in lines: yield ln.decode()


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--session", required=True); ap.add_argument("--port", type=int, default=5555)
    a = ap.parse_args()
    S = load_session(a.session, log=lambda *x: None)
    B = {}; latest = {}; next_end = C.WIN; n = 0
    for ln in serve(a.port):
        if ln == "END": break
        try:
            name, t, v = ln.split(","); t, v = float(t), float(v)
        except ValueError:
            continue
        k = NAMES.get(name)
        if not k: continue
        B.setdefault(k, ([], [])); B[k][0].append(t); B[k][1].append(v); latest[k] = t; n += 1
        while latest and min(latest.values()) >= next_end:
            st = {kk: (np.array(x[0]), np.array(x[1])) for kk, x in B.items()}
            st.update({kk: S["streams"][kk] for kk in ("eda_fs", "bvp_fs", "acc_fs") if kk in S["streams"]})
            r = physio_window(st, next_end - C.WIN, next_end)
            print(f"[receiver] okno do {next_end:5.0f}s  HR={r.get('hr', np.nan):5.1f}  RMSSD={r.get('rmssd', np.nan):5.1f}  "
                  f"EDA={r.get('eda_tonic', np.nan):5.2f}  SCR/min={r.get('scr_rate', np.nan):4.1f}", flush=True)
            next_end += C.STEP
    print(f"[receiver] odebrano {n} próbek; analiza obrazu i zapis...", flush=True)
    S["streams"].update({k: (np.array(x[0]), np.array(x[1])) for k, x in B.items()})   # dane z sieci zamiast z plików
    app = analyze_app(S["app"], S["frame_times"]) if S.get("app") else None
    cam = analyze_webcam(S["webcam"], S["frame_times"]) if S.get("webcam") else None
    df, _ = analyze(S, app, cam)
    out = os.path.join(S["folder"], "wyniki", "cechy_stream.csv"); df.to_csv(out, index=False)
    print(f"[receiver] zapisano {out}", flush=True)


if __name__ == "__main__":
    main()
