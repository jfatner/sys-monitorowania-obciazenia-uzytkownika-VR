#!/usr/bin/env python3
"""Ewaluacja (Moduł 3): zestawienie wyników obiektywnych z ankietą (RTLX + wywiad).

    python evaluation/evaluate.py sesje

Bierze każdą sesję, która ma wyniki/podsumowanie.json (po process_session.py) i ankieta_<ID>.json.
Wyniki w sesje/_ewaluacja/:
    zestawienie.csv     jeden wiersz na uczestnika: ankieta + miary obiektywne
    korelacje.csv       Pearson i Spearman (r, p) dla każdej pary miara-ankieta
    szczyty.csv         moment największego napięcia wg uczestnika vs szczyt wskaźnika
    wykresy.png         wykresy rozrzutu
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from scipy import stats
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

TLX = ["mental", "physical", "temporal", "performance", "effort", "frustration"]
TARGETS = ["rtlx", "stres_1_5"] + TLX
OBJ = ["load_index", "idx_fizjologia", "idx_ruch", "idx_scena", "peak_load_index",
       "hr_delta", "rmssd_ratio", "eda_tonic_ratio", "scr_rate", "user_motion", "acc_motion",
       "head_motion", "n_objects", "scene_dynamics"]
MIN_N = 5
PEAK_TOL_S = 60


def mmss(s):
    try: m, x = str(s).split(":"); return int(m) * 60 + float(x)
    except Exception: return np.nan


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "sesje"
    out = os.path.join(root, "_ewaluacja"); os.makedirs(out, exist_ok=True)
    rows, peaks, skipped = [], [], []
    for d in sorted(glob.glob(os.path.join(root, "*", ""))):
        sid = os.path.basename(os.path.normpath(d))
        if sid.startswith(("_", ".")): continue
        sp, ank = os.path.join(d, "wyniki", "podsumowanie.json"), sorted(glob.glob(os.path.join(d, "ankieta*.json")))
        if not os.path.exists(sp) or not ank:
            skipped.append(f"{sid}: " + ("brak wyników (uruchom process_session.py)" if not os.path.exists(sp) else "brak ankiety"))
            continue
        P = json.load(open(sp, encoding="utf-8")); A = json.load(open(ank[-1], encoding="utf-8"))
        r = {"id": sid, **{k: A.get(k) for k in TARGETS}}
        tm = P.get("task_mean", {})
        for k in OBJ:
            r[k] = P.get(k, tm.get(k))
        rows.append(r)
        declared = mmss(A.get("najwieksze_napiecie_czas", ""))
        if np.isfinite(declared) and P.get("peak_time_s") is not None:
            peaks.append(dict(id=sid, deklarowany_s=declared, szczyt_wskaznika_s=P["peak_time_s"],
                              roznica_s=abs(declared - P["peak_time_s"])))
    for s in skipped: print("pominięto", s)
    if not rows:
        print("Brak sesji z wynikami i ankietą."); return 1
    Z = pd.DataFrame(rows); Z.to_csv(os.path.join(out, "zestawienie.csv"), index=False)
    print(f"\nUczestników: {len(Z)}")
    print(Z[["id", "rtlx", "stres_1_5", "load_index", "hr_delta", "eda_tonic_ratio"]].round(2).to_string(index=False))

    res = []
    for tgt in TARGETS:
        for m in OBJ:
            ok = Z[[tgt, m]].apply(pd.to_numeric, errors="coerce").dropna()
            if len(ok) < MIN_N or ok[m].std() == 0 or ok[tgt].std() == 0: continue
            pr, pp = stats.pearsonr(ok[m], ok[tgt]); sr, sp = stats.spearmanr(ok[m], ok[tgt])
            res.append(dict(ankieta=tgt, miara=m, n=len(ok), pearson_r=pr, pearson_p=pp, spearman_rho=sr, spearman_p=sp))
    if res:
        K = pd.DataFrame(res); K.to_csv(os.path.join(out, "korelacje.csv"), index=False)
        print("\nKorelacje z RTLX (Spearman, sortowane):")
        print(K[K.ankieta == "rtlx"].sort_values("spearman_rho", key=abs, ascending=False)
              [["miara", "n", "spearman_rho", "spearman_p", "pearson_r"]].round(3).to_string(index=False))
        print("\nUwaga: przy małej liczbie osób p < 0.05 dla wielu par może wyjść przypadkiem - patrz README.")
    else:
        print(f"\nZa mało uczestników do korelacji (potrzeba co najmniej {MIN_N}).")

    if peaks:
        Pk = pd.DataFrame(peaks); Pk.to_csv(os.path.join(out, "szczyty.csv"), index=False)
        print(f"\nSzczyt napięcia wg uczestnika vs szczyt wskaźnika: mediana różnicy {Pk.roznica_s.median():.0f} s, "
              f"w granicach ±{PEAK_TOL_S} s: {(Pk.roznica_s <= PEAK_TOL_S).sum()}/{len(Pk)}")

    cols = [c for c in ("load_index", "idx_fizjologia", "hr_delta", "eda_tonic_ratio") if Z[c].notna().sum() >= 2]
    if cols and Z.rtlx.notna().sum() >= 2:
        fig, ax = plt.subplots(1, len(cols), figsize=(4.2 * len(cols), 3.8)); ax = np.atleast_1d(ax)
        for a, c in zip(ax, cols):
            ok = Z[["id", c, "rtlx"]].dropna()
            a.scatter(ok[c], ok.rtlx, s=40)
            for _, w in ok.iterrows(): a.annotate(w.id, (w[c], w.rtlx), fontsize=7, xytext=(3, 3), textcoords="offset points")
            if len(ok) >= 3:
                k = np.polyfit(ok[c].astype(float), ok.rtlx.astype(float), 1); xs = np.linspace(ok[c].min(), ok[c].max(), 10)
                a.plot(xs, np.polyval(k, xs), "r--", lw=1)
                a.set_title(f"rho = {stats.spearmanr(ok[c], ok.rtlx)[0]:.2f} (n={len(ok)})", fontsize=9)
            a.set_xlabel(c); a.set_ylabel("Raw TLX")
        fig.tight_layout(); fig.savefig(os.path.join(out, "wykresy.png"), dpi=130)
    print(f"\nWyniki: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
