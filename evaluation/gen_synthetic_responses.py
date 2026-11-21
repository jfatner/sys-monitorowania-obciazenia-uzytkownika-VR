#!/usr/bin/env python3
"""UWAGA: generuje SYNTETYCZNE odpowiedzi RTLX (do testu potoku). Zastąp plik prawdziwym
responses.csv z formularza rtlx_form.html - evaluate.py przyjmuje ten sam format."""
import sys, numpy as np, pandas as pd, os
root = os.path.join(os.path.dirname(__file__), "..")
rng = np.random.default_rng(11)
rows = []
for p in sorted(d for d in os.listdir(f"{root}/data") if d.startswith("P")):
    tr = np.loadtxt(f"{root}/data/{p}/truth.csv", delimiter=",", skiprows=1)
    s = tr[:, 1].mean() * 0.8 + tr[:, 1].max() * 0.2             # subiektywne odczucie ~ obciążenie ukryte
    sub = lambda w, off: float(np.clip(100 * (w * s + off) + rng.normal(0, 9), 0, 100))
    rows.append(dict(participant=p, mental=sub(1.0, -0.05), physical=sub(0.6, -0.1), temporal=sub(0.9, -0.05),
                     performance=sub(0.7, -0.05), effort=sub(1.0, 0.0), frustration=sub(1.1, -0.1)))
pd.DataFrame(rows).round(0).to_csv(f"{os.path.dirname(__file__)}/responses_SYNTHETIC.csv", index=False)
print("zapisano responses_SYNTHETIC.csv")
