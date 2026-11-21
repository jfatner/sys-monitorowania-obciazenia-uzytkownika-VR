#!/usr/bin/env python3
"""Ewaluacja (Moduł 3): zestawienie wskaźników obiektywnych z Raw NASA-TLX.

Użycie: evaluate.py [responses.csv]   (domyślnie responses.csv, a gdy go brak - SYNTHETIC)
Kolumny responses.csv: participant,mental,physical,temporal,performance,effort,frustration (0-100)
Wyniki: results/evaluation_summary.csv, results/correlations.csv, results/correlations.png,
        results/validation_vs_truth.csv (tylko dane syntetyczne - prawda terenowa).
"""
import sys, os, numpy as np, pandas as pd
from scipy import stats
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.join(HERE, "..")
sys.path.insert(0, f"{ROOT}/analysis")
from analyze_session import run

SUBS = ["mental", "physical", "temporal", "performance", "effort", "frustration"]
OBJ = ["load_index", "hr_polar", "rmssd", "lf_hf", "eda_tonic", "scr_rate", "n_objects", "motion_energy", "head_shift"]

def features(p):
    f = f"{ROOT}/results/features_{p}.csv"
    if os.path.exists(f): return pd.read_csv(f)
    return run(f"{ROOT}/data/{p}", f)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else f"{HERE}/responses.csv"
    synthetic = False
    if not os.path.exists(path): path, synthetic = f"{HERE}/responses_SYNTHETIC.csv", True
    R = pd.read_csv(path); R["rtlx"] = R[SUBS].mean(axis=1)               # Raw TLX = średnia bez ważenia
    agg, val = [], []
    for p in R.participant:
        df = features(p)
        row = {"participant": p, **{f"{c}_mean": df[c].mean() for c in OBJ}, "load_index_peak": df.load_index.max()}
        agg.append(row)
        if synthetic and os.path.exists(f"{ROOT}/data/{p}/truth.csv"):    # walidacja algorytmu wobec ukrytego s(t)
            tr = np.loadtxt(f"{ROOT}/data/{p}/truth.csv", delimiter=",", skiprows=1)
            s = [tr[(tr[:, 0] > t - 30) & (tr[:, 0] <= t), 1].mean() for t in df.t_end]
            tc = [tr[(tr[:, 0] > t - 30) & (tr[:, 0] <= t), 2].mean() for t in df.t_end]
            val.append(dict(participant=p, r_index_vs_truth=np.corrcoef(df.load_index, s)[0, 1],
                            r_nobj_vs_truth=np.corrcoef(df.n_objects, tc)[0, 1]))
    A = R.merge(pd.DataFrame(agg), on="participant"); A.to_csv(f"{ROOT}/results/evaluation_summary.csv", index=False)
    rows = []
    for tgt in ["rtlx"] + SUBS:
        for m in [f"{c}_mean" for c in OBJ] + ["load_index_peak"]:
            ok = A[[tgt, m]].dropna()
            if len(ok) < 4: continue
            pr, pp = stats.pearsonr(ok[m], ok[tgt]); sr, sp = stats.spearmanr(ok[m], ok[tgt])
            rows.append(dict(target=tgt, metric=m, n=len(ok), pearson_r=pr, pearson_p=pp, spearman_rho=sr, spearman_p=sp))
    C = pd.DataFrame(rows); C.to_csv(f"{ROOT}/results/correlations.csv", index=False)
    if val:
        V = pd.DataFrame(val); V.to_csv(f"{ROOT}/results/validation_vs_truth.csv", index=False)
        print("\nWalidacja wobec prawdy terenowej (średnia r w sesjach):\n", V.drop(columns="participant").mean().round(3).to_string())
    top = C[C.target == "rtlx"].sort_values("pearson_r", ascending=False)
    print(f"\nŹródło odpowiedzi: {os.path.basename(path)}{'  [DANE SYNTETYCZNE]' if synthetic else ''}")
    print("\nKorelacje z RTLX (N=%d):\n" % len(A), top.round(3).to_string(index=False))
    fig, ax = plt.subplots(1, 3, figsize=(13, 4))
    for a, m, lab in zip(ax, ["load_index_mean", "hr_polar_mean", "eda_tonic_mean"], ["Wskaźnik obciążenia (0-100)", "HR Polar [bpm]", "EDA tonic [µS]"]):
        a.scatter(A[m], A.rtlx, s=40); k = np.polyfit(A[m], A.rtlx, 1); xs = np.linspace(A[m].min(), A[m].max(), 10)
        a.plot(xs, np.polyval(k, xs), "r--"); r = np.corrcoef(A[m], A.rtlx)[0, 1]
        a.set_xlabel(lab); a.set_ylabel("Raw TLX"); a.set_title(f"r = {r:.2f}")
        for _, rw in A.iterrows(): a.annotate(rw.participant[1:], (rw[m], rw.rtlx), fontsize=7, xytext=(3, 3), textcoords="offset points")
    if synthetic: fig.suptitle("DANE SYNTETYCZNE - ilustracja potoku, nie wynik badania", color="red")
    fig.tight_layout(); fig.savefig(f"{ROOT}/results/correlations.png", dpi=130)

if __name__ == "__main__":
    main()
