"""Przetwarzanie sygnałów fizjologicznych (Moduł 2).

Polar  (Piotr Michałkiewicz): RR -> HR, RMSSD, SDNN, LF/HF (DFT)
Empatica (Janusz Fątner):     EDA -> poziom tonic, liczba SCR; BVP -> HR (DFT), SNR
Wszystkie funkcje działają na oknie czasowym (tablice numpy), więc ten sam kod służy
do analizy wsadowej i strumieniowej.
"""
import numpy as np
from scipy import signal

# ---------- Dyskretna Transformata Fouriera ----------
def dft_naive(x):
    """Wprost z definicji, O(N^2) - do weryfikacji FFT oraz celów dydaktycznych."""
    x = np.asarray(x, dtype=float); n = len(x)
    k = np.arange(n)[:, None]; m = np.arange(n)[None, :]
    return (x[None, :] * np.exp(-2j * np.pi * k * m / n)).sum(axis=1)

def spectrum(x, fs, nfft=None, window=True):
    """Widmo mocy jednostronne (FFT = szybka DFT)."""
    x = np.asarray(x, float) - np.mean(x)
    if window: x = x * np.hanning(len(x))
    nfft = nfft or len(x)
    X = np.fft.rfft(x, nfft)
    return np.fft.rfftfreq(nfft, 1 / fs), (np.abs(X) ** 2) / len(x)

def band_power(f, p, lo, hi):
    m = (f >= lo) & (f < hi)
    return float(np.trapezoid(p[m], f[m])) if m.sum() > 1 else 0.0

# ---------- Polar: RR ----------
def clean_rr(t, rr):
    """Odrzuca artefakty: poza 300-2000 ms lub >20% od mediany lokalnej."""
    t, rr = np.asarray(t, float), np.asarray(rr, float)
    if len(rr) < 5: return t, rr
    ok = (rr > 300) & (rr < 2000)
    med = signal.medfilt(rr, 5)
    ok &= np.abs(rr - med) < 0.2 * med
    return t[ok], rr[ok]

def rr_features(t, rr, fs_i=4.0):
    out = dict(hr_polar=np.nan, rmssd=np.nan, sdnn=np.nan, lf_hf=np.nan)
    t, rr = clean_rr(t, rr)
    if len(rr) < 10: return out
    out["hr_polar"] = float(60000 / rr.mean())
    out["sdnn"] = float(rr.std(ddof=1))
    out["rmssd"] = float(np.sqrt(np.mean(np.diff(rr) ** 2)))
    ti = np.arange(t[0], t[-1], 1 / fs_i)
    if len(ti) < 32: return out
    ri = signal.detrend(np.interp(ti, t, rr))
    f, p = spectrum(ri, fs_i, nfft=1024)
    lf, hf = band_power(f, p, 0.04, 0.15), band_power(f, p, 0.15, 0.40)
    out["lf_hf"] = float(lf / hf) if hf > 0 else np.nan
    return out

# ---------- Empatica: EDA ----------
def eda_features(t, eda, fs=4.0, min_prom=0.1):
    out = dict(eda_tonic=np.nan, scr_rate=np.nan)
    eda = np.asarray(eda, float)
    if len(eda) < 20: return out
    b, a = signal.butter(2, 1.0, btype="low", fs=fs)               # filtr dolnoprzepustowy 1 Hz
    y = signal.filtfilt(b, a, eda)
    out["eda_tonic"] = float(np.median(y))
    ph = signal.detrend(y)                                          # usunięcie trendu tonic
    peaks, _ = signal.find_peaks(ph, prominence=min_prom, distance=int(2 * fs))
    out["scr_rate"] = float(len(peaks) / ((len(y) / fs) / 60))
    return out

# ---------- Empatica: BVP ----------
def bvp_features(t, bvp, fs=64.0):
    out = dict(bvp_hr=np.nan, bvp_snr=np.nan)
    bvp = np.asarray(bvp, float)
    if len(bvp) < fs * 10: return out
    b, a = signal.butter(3, [0.7, 3.5], btype="band", fs=fs)       # pasmo tętna 42-210 bpm
    y = signal.filtfilt(b, a, bvp)
    f, p = spectrum(y, fs, nfft=16384)
    m = (f >= 0.7) & (f <= 3.0)
    if not m.any(): return out
    k = np.argmax(p[m]); f0 = f[m][k]
    out["bvp_hr"] = float(f0 * 60)
    near = (f > f0 - 0.15) & (f < f0 + 0.15)
    out["bvp_snr"] = float(10 * np.log10(p[near].sum() / max(p[m].sum() - p[m & near].sum(), 1e-12)))
    return out
