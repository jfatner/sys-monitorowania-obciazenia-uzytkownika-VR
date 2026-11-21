"""Wczytanie folderu sesji, synchronizacja źródeł, cechy w oknach i wskaźnik obciążenia."""
import csv, glob, json, os
import numpy as np
import pandas as pd

import config as C
from importers import load_empatica, load_polar, parse_time, DataError
from physio import rr_features, hr_features, eda_features, bvp_features, acc_features


# ======================= wczytanie i synchronizacja =======================

def _find(folder, names):
    for n in names:
        if not n: continue
        for p in glob.glob(os.path.join(folder, n)):
            if os.path.exists(p): return p
    return None


def load_session(folder, log=print):
    """Zwraca dict z: id, t0 (unix), dur, streams (czas sesji [s]), frame_times, app/webcam paths,
    events (lista (t, nazwa) w czasie sesji), baseline_end, sync (opis), warnings."""
    folder = os.path.abspath(folder)
    S = dict(id=os.path.basename(folder.rstrip("/\\")), folder=folder, warnings=[], streams={}, sync={})
    W = S["warnings"]
    info = json.load(open(os.path.join(folder, "info.json"), encoding="utf-8")) if os.path.exists(os.path.join(folder, "info.json")) else {}
    S["info"] = info

    # --- obraz i czas sesji ---
    fpath = os.path.join(folder, "frames.csv")
    if os.path.exists(fpath):
        ft = pd.read_csv(fpath)["unix_time"].to_numpy(float)
        S["t0"] = float(ft[0]); S["frame_times"] = ft - ft[0]; S["dur"] = float(ft[-1] - ft[0])
        S["app"] = _find(folder, [info.get("app_video", "app.mp4"), "app.*"])
        S["webcam"] = _find(folder, [info.get("webcam_video", "webcam.mp4"), "webcam.*"])
        gaps = np.diff(ft)
        if len(gaps) and gaps.max() > 1.0:
            W.append(f"przerwa w nagraniu obrazu: {gaps.max():.1f} s")
    else:
        S["t0"] = None; S["frame_times"] = None; S["app"] = S["webcam"] = None
        W.append("brak frames.csv - analiza bez obrazu, czas liczony od początku danych z opasek")

    # --- znaczniki ---
    events = []
    epath = os.path.join(folder, "events.csv")
    if os.path.exists(epath):
        for r in csv.DictReader(open(epath, encoding="utf-8")):
            events.append((float(r["unix_time"]), r["event"].strip()))

    # --- opaski ---
    raw = {}
    emp_dir = _find(folder, ["empatica", "Empatica", "e4", "E4"])
    if emp_dir:
        try:
            raw["emp"] = load_empatica(emp_dir)
            S["empatica_source"] = raw["emp"].get("source", "E4 (CSV)")
            if raw["emp"].get("missing"):
                W.append("Empatica: brak danych " + ", ".join(raw["emp"]["missing"]) +
                         " - czujnik wyłączony w konfiguracji badania (Care Lab Portal)")
        except DataError as e:
            W.append(f"Empatica: {e}")
    else:
        W.append("brak folderu empatica/")
    pol_dir = _find(folder, ["polar", "Polar"])
    if pol_dir:
        hint = parse_time(info["polar_start"]) if info.get("polar_start") else None
        try:
            raw["polar"] = load_polar(pol_dir, hint); S["polar_source"] = raw["polar"]["source"]
            for q in raw["polar"].get("quality_notes", []):
                W.append(f"Polar: {q} (stała wartość > 30 s = czujnik zgubił puls) - pominięte")
        except DataError as e:
            W.append(f"Polar: {e}")
    else:
        W.append("brak folderu polar/")

    # --- synchronizacja Empatiki znacznikiem SYNC ---
    emp_off = 0.0
    sync_ev = [t for t, e in events if e == "SYNC"]
    if "emp" in raw:
        tags = raw["emp"]["tags"]
        if sync_ev and len(tags):
            d = np.array([[tg - sv for tg in tags] for sv in sync_ev])
            i, j = np.unravel_index(np.argmin(np.abs(d)), d.shape)
            if abs(d[i, j]) <= C.SYNC_MAX_DIFF_S:
                emp_off = float(d[i, j])
                S["sync"]["empatica_offset_s"] = round(emp_off, 3)
                log(f"[sync] Empatica przesunięta o {-emp_off:+.2f} s (tag przycisku vs znacznik M)")
            else:
                W.append(f"tag Empatiki i znacznik SYNC różnią się o {d[i, j]:.0f} s - pominięto korektę")
        elif sync_ev:
            W.append("jest znacznik SYNC, ale brak tagów Empatiki (przycisk nie został wciśnięty?)")
        else:
            W.append("brak znacznika SYNC - zakładam zgodność zegarów Empatiki i laptopa")

    if S["t0"] is None:                                 # bez obrazu: część wspólna głównych strumieni
        spans = []
        for name, src in raw.items():
            off = emp_off if name == "emp" else 0.0
            for k, v in src.items():
                if isinstance(v, tuple) and k in ("rr", "hr", "eda", "bvp", "acc") and len(v[0]) > 10 \
                        and v[0][-1] - v[0][0] >= 60:
                    spans.append((float(v[0][0]) - off, float(v[0][-1]) - off))
        if not spans:
            raise DataError("Brak danych do analizy. " + " | ".join(W))
        a, b = max(x[0] for x in spans), min(x[1] for x in spans)
        if b - a < C.WIN:
            raise DataError("Dane z opasek nie nakładają się w czasie (różne nagrania?). " + " | ".join(W))
        S["t0"] = a; S["dur_hint"] = b - a
    t0 = S["t0"]

    def put(name, tv, off=0.0):
        t, v = tv
        S["streams"][name] = (np.asarray(t, float) - off - t0, np.asarray(v, float))

    if "polar" in raw:
        if "rr" in raw["polar"]: put("rr", raw["polar"]["rr"])
        if "hr" in raw["polar"]: put("hr", raw["polar"]["hr"])
    if "emp" in raw:
        e = raw["emp"]
        for k in ("eda", "bvp", "acc", "temp", "hr_e4", "ibi"):
            if k in e: put(k, e[k], emp_off)
        for k in ("eda_fs", "bvp_fs", "acc_fs"):
            if k in e: S["streams"][k] = e[k]

    if S["frame_times"] is None:
        S["dur"] = float(S["dur_hint"])

    # --- pokrycie danych ---
    from datetime import datetime
    hm = lambda x: datetime.fromtimestamp(x).strftime("%d.%m %H:%M:%S")
    names = {"rr": "Polar", "hr": "Polar", "eda": "Empatica", "bvp": "Empatica", "acc": "Empatica",
             "temp": "Empatica", "hr_e4": "Empatica", "ibi": "Empatica"}
    outside, partial = {}, []
    for k, v in S["streams"].items():
        if not isinstance(v, tuple) or len(v[0]) == 0: continue
        a, b = max(v[0][0], 0), min(v[0][-1], S["dur"])
        cov = max(0.0, b - a) / S["dur"] if S["dur"] > 0 else 0
        if cov == 0:
            src = names.get(k, k)
            lo, hi = outside.get(src, (v[0][0], v[0][-1]))
            outside[src] = (min(lo, v[0][0]), max(hi, v[0][-1]))
        elif cov < 0.9:
            partial.append(f"{names.get(k, k)} ({k}): dane pokrywają tylko {100 * cov:.0f}% sesji "
                           f"({v[0][0]:.0f}-{v[0][-1]:.0f} s nagrania)")
    for src, (lo, hi) in outside.items():
        gap = (lo - S["dur"]) if lo > S["dur"] else (hi if hi < 0 else 0)
        g = abs(gap); gtxt = f"{int(g // 3600)} h {int(g % 3600 // 60)} min" if g >= 3600 else f"{int(g // 60)} min {int(g % 60)} s"
        W.append(f"{src}: dane są z innego czasu niż nagranie - nagranie {hm(t0)}-{hm(t0 + S['dur'])}, "
                 f"opaska {hm(t0 + lo)}-{hm(t0 + hi)} (rozjazd ok. {gtxt}). "
                 "Sprawdź, czy pliki są z tej samej sesji i czy zegary telefonu/laptopa są ustawione automatycznie.")
    for p in sorted(set(partial)):
        W.append(p + " - sprawdź, czy zapis w opasce był włączony przez całą sesję")

    S["events"] = [(t - t0, e) for t, e in events]
    task = [t for t, e in S["events"] if e == "TASK_START"]
    S["baseline_end"] = float(task[0]) if task else min(C.BASELINE_DEFAULT_S, S["dur"] / 3)
    if not task:
        W.append(f"brak znacznika TASK_START - spoczynek = pierwsze {S['baseline_end']:.0f} s")
    if S["baseline_end"] < C.MIN_BASELINE_S:
        W.append(f"spoczynek trwa tylko {S['baseline_end']:.0f} s (zalecane >= {C.MIN_BASELINE_S:.0f} s)")

    # --- fragment do analizy (ustawiany w aplikacji; info.json: "fragment_s": [od, do]) ---
    fr = info.get("fragment_s")
    if fr and len(fr) == 2 and fr[1] > fr[0]:
        a, b = max(0.0, float(fr[0])), min(float(fr[1]), S["dur"])
        S["fragment"] = (a, b) if b > a else None
        if b - a < C.WIN:
            W.append(f"fragment trwa {b - a:.0f} s - krócej niż okno analizy ({C.WIN:.0f} s), będzie jedno okno")
        if a < S["baseline_end"]:
            W.append("fragment zaczyna się w czasie spoczynku - sprawdź znacznik startu zadania / fragment")
    else:
        S["fragment"] = None

    # --- ankieta (opcjonalnie) ---
    ank = sorted(glob.glob(os.path.join(folder, "ankieta*.json")))
    S["survey"] = json.load(open(ank[-1], encoding="utf-8")) if ank else None
    return S


# ======================= cechy w oknie =======================

def _sel(stream, t0, t1):
    t, v = stream
    m = (t > t0) & (t <= t1)
    return t[m], v[m]


def physio_window(st, t0, t1):
    d = {}
    if "rr" in st:
        d.update(rr_features(*_sel(st["rr"], t0, t1), max_gap_s=2.5))   # RMSSD tylko z kolejnych uderzeń
    elif "ibi" in st:
        d.update(rr_features(*_sel(st["ibi"], t0, t1), max_gap_s=2.0))
    else:
        d.update(dict(hr=np.nan, rmssd=np.nan, sdnn=np.nan, lf_hf=np.nan, rr_valid=np.nan))
    if not np.isfinite(d.get("hr", np.nan)):
        for k in ("hr", "hr_e4"):
            if k in st:
                h = hr_features(*_sel(st[k], t0, t1))["hr"]
                if np.isfinite(h): d["hr"] = h; break
    if "eda" in st: d.update(eda_features(*_sel(st["eda"], t0, t1), st.get("eda_fs", 4.0)))
    if "bvp" in st: d.update(bvp_features(*_sel(st["bvp"], t0, t1), st.get("bvp_fs", 64.0)))
    if "acc" in st: d.update(acc_features(*_sel(st["acc"], t0, t1), st.get("acc_fs", 32.0)))
    if "temp" in st:
        _, v = _sel(st["temp"], t0, t1); d["temp"] = float(v.mean()) if len(v) else np.nan
    return d


def window_features(S, app_rows, cam_rows, t0, t1):
    from video import app_window, webcam_window
    d = {"t_start": t0, "t_end": t1}
    d.update(physio_window(S["streams"], t0, t1))
    d.update(app_window(app_rows, t0, t1))
    d.update(webcam_window(cam_rows, t0, t1))
    return d


# ======================= wskaźnik obciążenia =======================

def score(name, x, b):
    kind, scale, eps = C.NORM[name]
    if not (np.isfinite(x) and np.isfinite(b)): return np.nan
    if kind == "diff":
        z = (x - b) / scale
    elif kind == "drop":
        z = (1 - x / b) / scale if b > 0 else np.nan
    else:
        z = np.log2((x + eps) / (b + eps)) / scale
    return float(np.clip(z, 0, 1))


def load_index(row, base):
    groups = {}
    for g, names in C.GROUPS.items():
        v = [score(n, row.get(n, np.nan), base.get(n, np.nan)) for n in names]
        v = [x for x in v if np.isfinite(x)]
        groups[g] = float(np.mean(v)) if v else np.nan
    ok = {g: v for g, v in groups.items() if np.isfinite(v)}
    total = 100 * sum(C.WEIGHTS[g] * v for g, v in ok.items()) / sum(C.WEIGHTS[g] for g in ok) if ok else np.nan
    return total, groups


def analyze(S, app_rows=None, cam_rows=None, log=print):
    """Cechy w oknach + baseline + wskaźnik. Zwraca (DataFrame okien, dict baseline)."""
    b_end = S["baseline_end"]
    b_start = min(C.BASELINE_SKIP_S, max(0.0, b_end - C.MIN_BASELINE_S))   # zostaw co najmniej MIN_BASELINE_S
    S["baseline_range"] = (b_start, b_end)
    base = window_features(S, app_rows, cam_rows, b_start, b_end)
    fr = S.get("fragment")
    ends = list(np.arange(C.WIN, S["dur"] + 1e-9, C.STEP))
    if fr:                                   # okna dokładnie w obrębie fragmentu (+ całość dla wykresu)
        if fr[1] - fr[0] < C.WIN:
            ends.append(fr[1])
        else:
            ends += list(np.arange(fr[0] + C.WIN, fr[1] + 1e-9, C.STEP))
    rows = []
    for t1 in sorted(set(round(float(e), 3) for e in ends)):
        t0w = max(0.0, t1 - C.WIN)
        if fr and abs(t1 - fr[1]) < 1e-6 and fr[1] - fr[0] < C.WIN: t0w = fr[0]
        r = window_features(S, app_rows, cam_rows, t0w, t1)
        if fr and t0w >= fr[0] - 1e-6 and t1 <= fr[1] + 1e-6:
            r["phase"] = "fragment"
        else:
            r["phase"] = "spoczynek" if t1 <= b_end else ("zadanie" if t0w >= b_end else "przejście")
        r["load_index"], gs = load_index(r, base)
        r.update({f"idx_{g}": 100 * v if np.isfinite(v) else np.nan for g, v in gs.items()})
        rows.append(r)
    return pd.DataFrame(rows), base
