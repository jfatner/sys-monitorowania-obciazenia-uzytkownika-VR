#!/usr/bin/env python3
"""Analiza wsadowa jednej sesji: python3 analyze_session.py data/P01 out.csv"""
import sys, os, numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(__file__))
from session import *
from video import video_frame_features, video_window_features

def run(d, out=None, video_cache=True):
    ld = lambda f: np.loadtxt(os.path.join(d, f), delimiter=",", skiprows=1)
    rr, eda, bvp = ld("polar_rr.csv"), ld("empatica_eda.csv"), ld("empatica_bvp.csv")
    vr, fps = video_frame_features(os.path.join(d, "video.avi"))
    dur = min(rr[-1, 0], eda[-1, 0], bvp[-1, 0], vr[-1, 0])
    rows = []
    for t1 in np.arange(WIN, dur + 1e-9, STEP):
        r = physio_window(rr[:, 0], rr[:, 1], eda[:, 0], eda[:, 1], bvp[:, 0], bvp[:, 1], t1 - WIN, t1)
        r.update(video_window_features(vr, fps, t1 - WIN, t1))
        r["load_index"], gs = load_index(r)
        r.update({f"idx_{k}": v for k, v in gs.items()})
        rows.append(r)
    df = pd.DataFrame(rows)
    if out: df.to_csv(out, index=False)
    return df

if __name__ == "__main__":
    df = run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(df.round(2).to_string())
