"""Analiza obrazu z gogli VR (Moduł 2).

Piotr Michałkiewicz  - zagęszczenie obiektów: rozmycie Gaussa (filtracja przestrzenna),
                       progowanie Otsu (segmentacja), operacje morfologiczne, składowe
                       spójne -> liczba obiektów; gęstość krawędzi Canny'ego.
Janusz Fątner        - dynamika: kompensacja ruchu kamery (korelacja fazowa = ruch głowy
                       użytkownika), różnica klatek -> liczba poruszających się obiektów,
                       energia ruchu i jej częstotliwość dominująca (DFT).
"""
import cv2, numpy as np
from physio import spectrum

MIN_AREA = 60
CORE_DIST = 4.5      # px; rdzeń obiektu = piksele oddalone od tła o >4.5 px (obiekty mają r=7..13)

def count_objects(gray):
    """Zwraca (liczba obiektów, gęstość krawędzi)."""
    blur = cv2.GaussianBlur(gray, (5, 5), 1.2)                       # preprocessing + filtracja
    _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    # rozdzielanie stykających się obiektów: transformata odległości + progowanie maksimów
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    _, cores = cv2.threshold(dist, CORE_DIST, 255, cv2.THRESH_BINARY)
    n, _, stats, _ = cv2.connectedComponentsWithStats(cores.astype(np.uint8))
    cnt = int(sum(1 for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 4))
    edges = cv2.Canny(blur, 60, 150)
    return cnt, float((edges > 0).mean())

def video_frame_features(path):
    """Cechy per klatka: t, n_objects, edge_density, motion_energy, moving_blobs, shift."""
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 10.0
    rows, prev, i = [], None, 0
    win = None
    while True:
        ok, frame = cap.read()
        if not ok: break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        n, ed = count_objects(gray)
        g32 = cv2.GaussianBlur(gray, (5, 5), 1.2).astype(np.float32)
        if prev is None:
            me, blobs, shift = 0.0, 0, 0.0
            win = cv2.createHanningWindow(gray.shape[::-1], cv2.CV_32F)
        else:
            (dx, dy), _ = cv2.phaseCorrelate(prev, g32, win)         # przesunięcie sceny = ruch głowy
            M = np.float32([[1, 0, dx], [0, 1, dy]])
            comp = cv2.warpAffine(prev, M, gray.shape[::-1], borderMode=cv2.BORDER_REFLECT)
            diff = np.abs(g32 - comp)
            me = float(diff.mean())
            m = (diff > 30).astype(np.uint8) * 255
            m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            nb, _, st, _ = cv2.connectedComponentsWithStats(m)
            blobs = int(sum(1 for k in range(1, nb) if st[k, cv2.CC_STAT_AREA] >= MIN_AREA))
            shift = float(np.hypot(dx, dy))
        rows.append((i / fps, n, ed, me, blobs, shift))
        prev, i = g32, i + 1
    cap.release()
    return np.array(rows), fps

def video_window_features(rows, fps, t0, t1):
    """Agregacja cech klatkowych w oknie (t0, t1]."""
    m = (rows[:, 0] > t0) & (rows[:, 0] <= t1)
    w = rows[m]
    out = dict(n_objects=np.nan, edge_density=np.nan, motion_energy=np.nan,
               moving_blobs=np.nan, head_shift=np.nan, motion_freq=np.nan)
    if len(w) < 10: return out
    out.update(n_objects=float(w[:, 1].mean()), edge_density=float(w[:, 2].mean()),
               motion_energy=float(w[:, 3].mean()), moving_blobs=float(w[:, 4].mean()),
               head_shift=float(np.sqrt(np.mean(w[:, 5] ** 2))))
    f, p = spectrum(w[:, 3], fps, nfft=1024)                          # częstotliwość ruchu (DFT)
    mk = (f >= 0.2) & (f <= fps / 2)
    out["motion_freq"] = float(f[mk][np.argmax(p[mk])])
    return out
