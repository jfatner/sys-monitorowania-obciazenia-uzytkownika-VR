#!/usr/bin/env python3
"""Analiza jednej sesji (albo wszystkich).

    python analysis/process_session.py sesje/P01
    python analysis/process_session.py sesje            # każda podfolder-sesja po kolei

Wyniki w sesje/<ID>/wyniki/:
    cechy.csv            cechy w oknach 30 s co 10 s + wskaźnik obciążenia
    podsumowanie.json    spoczynek, średnie z zadania, szczyt, jakość danych, ostrzeżenia
    przebieg.png         wykres całej sesji
    obraz_app.csv, obraz_webcam.csv   cechy obrazu klatka po klatce
    strumienie/*.csv     dane z opasek w czasie sesji (t,wartość) - wejście dla symulatora w C
"""
import json, os, sys, time
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C
from session import load_session, analyze
from importers import DataError
from video import analyze_app, analyze_webcam


def export_streams(S, out):
    os.makedirs(out, exist_ok=True)
    names = {"rr": ("polar_rr.csv", "rr_ms"), "hr": ("polar_hr.csv", "hr_bpm"), "eda": ("empatica_eda.csv", "eda_uS"),
             "bvp": ("empatica_bvp.csv", "bvp"), "acc": ("empatica_acc.csv", "acc_g"), "ibi": ("empatica_ibi.csv", "ibi_ms")}
    for k, (fn, col) in names.items():
        if k in S["streams"]:
            t, v = S["streams"][k]; m = (t >= 0) & (t <= S["dur"])
            pd.DataFrame({"t": np.round(t[m], 4), col: v[m]}).to_csv(os.path.join(out, fn), index=False)


def _mmss(s):
    try:
        m, sec = str(s).strip().split(":"); return int(m) * 60 + float(sec)
    except Exception:
        return None


def plot(S, df, out):
    panels = [("Tętno [bpm]", ["hr", "bvp_hr"]), ("RMSSD [ms]", ["rmssd"]), ("EDA [µS] / SCR na min", ["eda_tonic", "scr_rate"]),
              ("Ruch użytkownika", ["user_motion", "acc_motion"]), ("Scena w goglach", ["n_objects", "head_motion", "scene_dynamics"]),
              ("Obciążenie 0-100", ["load_index", "idx_fizjologia", "idx_ruch", "idx_scena"])]
    panels = [(t, [c for c in cols if c in df and df[c].notna().any()]) for t, cols in panels]
    panels = [p for p in panels if p[1]]
    fig, axes = plt.subplots(len(panels), 1, figsize=(11, 2.0 * len(panels)), sharex=True)
    axes = np.atleast_1d(axes); x = df.t_end - C.WIN / 2
    for ax, (title, cols) in zip(axes, panels):
        for c in cols:
            lw = 2.2 if c == "load_index" else 1.3
            ax.plot(x, df[c], lw=lw, label=c, marker="o", ms=2.5)
        ax.set_ylabel(title, fontsize=8); ax.legend(fontsize=7, loc="upper left", ncol=4); ax.grid(alpha=.3)
        ax.axvspan(*S["baseline_range"], color="0.85", zorder=0)
        if S.get("fragment"): ax.axvspan(*S["fragment"], color="gold", alpha=.18, zorder=0)
        for t, e in S["events"]:
            ax.axvline(t, color={"SYNC": "tab:purple", "TASK_START": "tab:green"}.get(e, "tab:gray"), ls="--", lw=.8)
        if S.get("survey"):
            pk = _mmss(S["survey"].get("najwieksze_napiecie_czas", ""))
            if pk is not None: ax.axvline(pk, color="red", lw=1.5, alpha=.6)
    axes[0].set_title(f"Sesja {S['id']}  (szare = spoczynek, żółte = analizowany fragment, zielona = start zadania, czerwona = szczyt wg uczestnika)", fontsize=9)
    axes[-1].set_xlabel("czas sesji [s] (środek okna)")
    fig.tight_layout(); fig.savefig(out, dpi=120); plt.close(fig)


class Progress:
    """Wypisuje linie '@@PROGRESS <procent> <opis>' - aplikacja zamienia je na pasek postępu."""
    def __init__(self, stages):
        tot = sum(w for _, w in stages) or 1
        self.span, acc = {}, 0.0
        for name, w in stages:
            self.span[name] = (100 * acc / tot, 100 * (acc + w) / tot); acc += w
        self.last = -1
        self.on = os.environ.get("VR_PROGRESS") == "1"     # ustawia aplikacja (app.py)

    def stage(self, name, label):
        a, b = self.span.get(name, (0, 0))
        def cb(frac):
            pct = int(a + (b - a) * min(max(frac, 0), 1))
            if pct != self.last and self.on:
                self.last = pct; print(f"@@PROGRESS {pct} {label}", flush=True)
        cb(0)
        return cb


def process(folder):
    t_start = time.time()
    print(f"\n=== {folder} ===")
    S = load_session(folder)
    out = os.path.join(S["folder"], "wyniki"); os.makedirs(out, exist_ok=True)
    has_v = S["frame_times"] is not None
    frag_frames = bool(S.get("fragment") and S["app"] and has_v)
    P = Progress([("app", 55 if S["app"] and has_v else 0), ("cam", 20 if S["webcam"] and has_v else 0),
                  ("feat", 8), ("frames", 12 if frag_frames else 0), ("plot", 5)])
    app_rows = cam_rows = None
    if S["app"] and S["frame_times"] is not None:
        print("[obraz] gogle..."); app_rows = analyze_app(S["app"], S["frame_times"], P.stage("app", "analiza obrazu z gogli"))
        pd.DataFrame(app_rows, columns=["t", "n_objects", "edge_density", "head_motion", "scene_dynamics", "moving_regions"]) \
            .to_csv(os.path.join(out, "obraz_app.csv"), index=False)
    if S["webcam"] and S["frame_times"] is not None:
        print("[obraz] kamera laptopa..."); cam_rows = analyze_webcam(S["webcam"], S["frame_times"], P.stage("cam", "analiza obrazu z kamery laptopa"))
        pd.DataFrame(cam_rows, columns=["t", "changed_percent"]).to_csv(os.path.join(out, "obraz_webcam.csv"), index=False)
    P.stage("feat", "sygnały z opasek i wskaźnik obciążenia")
    df, base = analyze(S, app_rows, cam_rows)
    if df.empty:
        raise DataError(f"sesja trwa tylko {S['dur']:.0f} s - do analizy potrzeba co najmniej {C.WIN:.0f} s "
                        f"(najlepiej kilka minut: spoczynek + zadanie)")
    rr_in = "rr" in S["streams"] and int(((S["streams"]["rr"][0] >= 0) & (S["streams"]["rr"][0] <= S["dur"])).sum()) >= 10
    if "rmssd" in df and len(df) and rr_in:
        miss = df.rmssd.isna().mean()
        if miss > 0.3:
            S["warnings"].append(f"HRV (RMSSD) niepoliczalne w {100 * miss:.0f}% okien - za dużo zakłóconych uderzeń "
                                 "(ruch ręki z opaską Polar?); tętno brane z pliku HR")
    df.to_csv(os.path.join(out, "cechy.csv"), index=False)
    export_streams(S, os.path.join(out, "strumienie"))

    if S.get("fragment"):
        task = df[df.phase == "fragment"]
    else:
        task = df[df.phase == "zadanie"]
        if task.empty: task = df[df.phase != "spoczynek"]
    if S.get("fragment") and S["app"] and S["frame_times"] is not None:
        from video import export_frames
        n = export_frames(S["app"], S["webcam"], S["frame_times"], *S["fragment"], os.path.join(out, "klatki"),
                          progress=P.stage("frames", "zapis klatek z fragmentu"))
        print(f"[obraz] wyeksportowano {n} klatek z fragmentu do wyniki/klatki/")
    num = [c for c in df.columns if c not in ("t_start", "t_end", "phase") and pd.api.types.is_numeric_dtype(df[c])]
    pk = task.loc[task.load_index.idxmax()] if task.load_index.notna().any() else None
    summ = dict(
        id=S["id"], dur_s=round(S["dur"], 1), baseline_s=[round(x, 1) for x in S["baseline_range"]],
        fragment_s=list(S["fragment"]) if S.get("fragment") else None,
        analysed_part="fragment" if S.get("fragment") else "zadanie",
        polar_source=S.get("polar_source"), sync=S["sync"],
        events=[(round(t, 2), e) for t, e in S["events"]],
        baseline={k: (round(v, 4) if isinstance(v, float) and np.isfinite(v) else None) for k, v in base.items() if k not in ("t_start", "t_end")},
        task_mean={c: (round(float(task[c].mean()), 4) if task[c].notna().any() else None) for c in num},
        peak_load_index=round(float(pk.load_index), 1) if pk is not None else None,
        peak_time_s=round(float(pk.t_end - C.WIN / 2), 1) if pk is not None else None,
        rr_valid_mean=round(float(df.rr_valid.mean()), 3) if "rr_valid" in df and df.rr_valid.notna().any() else None,
        warnings=S["warnings"],
    )
    d = summ["task_mean"]; b = summ["baseline"]
    for k, kind in (("hr", "delta"), ("eda_tonic", "ratio"), ("rmssd", "ratio")):
        if d.get(k) is not None and b.get(k):
            summ[f"{k}_{kind}"] = round(d[k] - b[k], 3) if kind == "delta" else round(d[k] / b[k], 3)
    json.dump(summ, open(os.path.join(out, "podsumowanie.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=float)
    P.stage("plot", "wykres i podsumowanie")
    plot(S, df, os.path.join(out, "przebieg.png"))
    if P.on: print("@@PROGRESS 100 gotowe", flush=True)

    print(f"czas sesji {S['dur']:.0f} s, spoczynek {S['baseline_range'][0]:.0f}-{S['baseline_range'][1]:.0f} s, okien: {len(df)}"
          + (f", fragment {S['fragment'][0]:.0f}-{S['fragment'][1]:.0f} s" if S.get('fragment') else ""))
    if S.get("polar_source"): print(f"Polar: {S['polar_source']}")
    if S.get("empatica_source"): print(f"Empatica: {S['empatica_source']}")
    show = [c for c in ("hr", "rmssd", "eda_tonic", "scr_rate", "user_motion", "n_objects", "scene_dynamics", "load_index") if c in df]
    print((task if S.get("fragment") else df)[["t_end", "phase"] + show].round(2).to_string(index=False))
    if summ["peak_time_s"] is not None:
        print(f"Szczyt obciążenia: {summ['peak_load_index']} w ~{summ['peak_time_s']:.0f} s")
    for w in S["warnings"]: print(f"  ! {w}")
    print(f"wyniki: {out}  ({time.time() - t_start:.0f} s)")


def main():
    if len(sys.argv) < 2:
        print(__doc__); return 2
    target = sys.argv[1]
    markers = ("info.json", "frames.csv", "empatica", "Empatica", "polar", "Polar")
    if any(os.path.exists(os.path.join(target, m)) for m in markers):
        folders = [target]
    else:
        folders = sorted(os.path.join(target, d) for d in os.listdir(target)
                         if os.path.isdir(os.path.join(target, d)) and not d.startswith((".", "_")))
    bad = 0
    for f in folders:
        try:
            process(f)
        except (DataError, IOError, KeyError, ValueError) as e:
            bad += 1; print(f"BŁĄD w {f}: {e}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
