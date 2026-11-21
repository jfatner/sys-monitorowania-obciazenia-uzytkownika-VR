"""Okna czasowe + wskaźnik obciążenia (wspólne dla trybu wsadowego i strumieniowego)."""
import numpy as np
from physio import rr_features, eda_features, bvp_features

WIN, STEP = 30.0, 10.0          # okno 30 s, krok 10 s
FS_EDA, FS_BVP = 4.0, 64.0

def physio_window(rr_t, rr, eda_t, eda, bvp_t, bvp, t0, t1):
    """Cechy fizjologiczne z danych w oknie (t0, t1]."""
    mr = (rr_t > t0) & (rr_t <= t1); me = (eda_t > t0) & (eda_t <= t1); mb = (bvp_t > t0) & (bvp_t <= t1)
    d = {"t_end": t1}
    d.update(rr_features(rr_t[mr], rr[mr]))
    d.update(eda_features(eda_t[me], eda[me], FS_EDA))
    d.update(bvp_features(bvp_t[mb], bvp[mb], FS_BVP))
    return d

# Zakresy referencyjne (min -> 0, max -> 1) dobrane ręcznie dla populacji młodych dorosłych.
# DO KALIBRACJI na prawdziwych danych (np. z sesji bazowych).
REF = {
    "hr_polar":      (60, 105, +1), "bvp_hr":      (60, 105, +1),
    "rmssd":         (10,  70, -1), "lf_hf":       (0.3, 3.0, +1),
    "eda_tonic":     (2.0, 6.5, +1), "scr_rate":    (0, 14, +1),
    "n_objects":     (3, 11, +1),   "motion_energy": (6.0, 8.5, +1),
    "moving_blobs":  (1, 10, +1),   "head_shift":  (1.5, 7.0, +1),
}
GROUPS = {   # średnia w grupie, potem średnia grup -> wskaźnik 0-100
    "cardiac": ["hr_polar", "bvp_hr", "rmssd", "lf_hf"],
    "eda":     ["eda_tonic", "scr_rate"],
    "visual":  ["n_objects", "moving_blobs", "motion_energy", "head_shift"],
}

def norm(name, x):
    lo, hi, sgn = REF[name]
    z = np.clip((x - lo) / (hi - lo), 0, 1)
    return z if sgn > 0 else 1 - z

def load_index(row):
    """Obiektywny wskaźnik obciążenia 0-100 + składowe grupowe."""
    gs = {}
    for g, names in GROUPS.items():
        v = [norm(n, row[n]) for n in names if n in row and np.isfinite(row[n])]
        gs[g] = float(np.mean(v)) if v else np.nan
    ok = [v for v in gs.values() if np.isfinite(v)]
    return (100 * float(np.mean(ok)) if ok else np.nan), gs
