"""Analiza obrazu (Moduł 2) - prawdziwe nagrania z nagrywarki sesji.

app.mp4 (obraz z gogli):
  Piotr Michałkiewicz - zagęszczenie obiektów: przetwarzanie wstępne (skala szarości, wyrównanie
      histogramu CLAHE), filtracja przestrzenna (rozmycie Gaussa), detekcja krawędzi Canny'ego z progami
      dobieranymi automatycznie, morfologia i segmentacja na obszary ograniczone krawędziami -> liczba obiektów
      i gęstość krawędzi.
  Janusz Fątner - dynamika: przepływ optyczny (Farnebäck). Mediana przepływu = ruch całej sceny,
      czyli obrót głowy użytkownika; przepływ po odjęciu mediany = elementy sceny poruszające się
      same -> liczba poruszających się obszarów i ich prędkość; częstotliwość ruchu z DFT.
webcam.mp4 (kamera laptopa skierowana na użytkownika):
  Janusz Fątner - ruch użytkownika: % pikseli zmienionych między klatkami co 0.15 s (metoda
      z podglądu kolegi), odsetek czasu w ruchu, liczba epizodów ruchu na minutę, częstotliwość (DFT).

Czas klatek bierzemy z frames.csv (rzeczywisty), nie z nominalnego FPS pliku.
"""
import cv2, numpy as np
from physio import spectrum
import config as C


def _resize_w(img, w):
    h0, w0 = img.shape[:2]
    return cv2.resize(img, (w, max(1, round(h0 * w / w0))), interpolation=cv2.INTER_AREA)


def _iter_frames(path, times, fps, progress=None):
    """Zwraca (t, klatka) co ~1/fps sekundy według czasów z frames.csv.
    progress(ułamek 0-1) - opcjonalnie, do paska postępu."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"Nie można otworzyć {path}")
    next_t, i, n = -1e9, 0, max(len(times), 1)
    try:
        while i < len(times):
            if progress and i % 50 == 0: progress(i / n)
            if times[i] < next_t:
                if not cap.grab(): break
                i += 1; continue
            ok, fr = cap.read()
            if not ok: break
            yield times[i], fr
            next_t, i = times[i] + 1.0 / fps, i + 1
    finally:
        cap.release()


_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))


def count_objects(gray):
    """Segmentacja sceny -> (liczba obiektów, gęstość krawędzi)."""
    g = _clahe.apply(gray)
    blur = cv2.GaussianBlur(g, (5, 5), 1.2)
    med = float(np.median(blur))
    edges = cv2.Canny(blur, int(max(0, 0.66 * med)), int(min(255, 1.33 * med + 20)))
    closed = cv2.morphologyEx(cv2.dilate(edges, np.ones((3, 3), np.uint8)), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    # segmentacja: obszary ograniczone krawędziami (składowe spójne tła krawędzi); bardzo duże = tło sceny
    _, _, st, _ = cv2.connectedComponentsWithStats((closed == 0).astype(np.uint8), connectivity=4)
    areas = st[1:, cv2.CC_STAT_AREA]; A = gray.size
    n = int(((areas >= C.MIN_OBJ_AREA * A) & (areas <= C.MAX_OBJ_AREA * A)).sum())
    return n, float((edges > 0).mean())


def analyze_app(path, times, progress=None):
    """Kolumny: t, n_objects, edge_density, head_motion[px/s], scene_dynamics[px/s], moving_regions."""
    rows, prev, prev_t = [], None, None
    for t, fr in _iter_frames(path, times, C.APP_FPS, progress):
        gray = cv2.cvtColor(_resize_w(fr, C.ANALYSIS_WIDTH), cv2.COLOR_BGR2GRAY)
        n, ed = count_objects(gray)
        small = _resize_w(gray, C.FLOW_WIDTH)
        hm = sd = mr = np.nan
        if prev is not None and t > prev_t:
            dt = t - prev_t
            flow = cv2.calcOpticalFlowFarneback(prev, small, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            med = np.median(flow.reshape(-1, 2), axis=0)
            hm = float(np.hypot(*med) / dt)
            res = np.linalg.norm(flow - med, axis=2) / dt
            sd = float(res.mean())
            m = (res > C.RESIDUAL_FLOW_THR).astype(np.uint8)
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
            k, _, st, _ = cv2.connectedComponentsWithStats(m)
            mr = int(sum(1 for j in range(1, k) if st[j, cv2.CC_STAT_AREA] >= 6))
        rows.append((t, n, ed, hm, sd, mr))
        prev, prev_t = small, t
    return np.array(rows, dtype=float).reshape(-1, 6)


def analyze_webcam(path, times, progress=None):
    """Kolumny: t, changed_percent."""
    rows, prev = [], None
    for t, fr in _iter_frames(path, times, C.CAM_FPS, progress):
        g = cv2.GaussianBlur(cv2.cvtColor(_resize_w(fr, 320), cv2.COLOR_BGR2GRAY), (5, 5), 0)
        if prev is not None and prev.shape == g.shape:
            _, mask = cv2.threshold(cv2.absdiff(prev, g), C.CAM_PIXEL_THRESHOLD, 255, cv2.THRESH_BINARY)
            rows.append((t, 100.0 * cv2.countNonZero(mask) / mask.size))
        prev = g
    return np.array(rows, dtype=float).reshape(-1, 2)


def _dom_freq(x, fs):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 16 or np.std(x) == 0: return np.nan
    f, p = spectrum(x, fs, nfft=1024)
    m = (f >= 0.05) & (f <= fs / 2)
    return float(f[m][np.argmax(p[m])])


def app_window(rows, t0, t1):
    keys = ("n_objects", "edge_density", "head_motion", "scene_dynamics", "moving_regions", "scene_motion_freq")
    out = dict.fromkeys(keys, np.nan)
    if rows is None or len(rows) == 0: return out
    w = rows[(rows[:, 0] > t0) & (rows[:, 0] <= t1)]
    if len(w) < 5: return out
    for j, k in enumerate(keys[:5], start=1):
        out[k] = float(np.nanmean(w[:, j]))
    out["scene_motion_freq"] = _dom_freq(w[:, 4], C.APP_FPS)
    return out


def webcam_window(rows, t0, t1):
    keys = ("user_motion", "user_moving_frac", "user_motion_bursts", "user_motion_freq")
    out = dict.fromkeys(keys, np.nan)
    if rows is None or len(rows) == 0: return out
    w = rows[(rows[:, 0] > t0) & (rows[:, 0] <= t1)]
    if len(w) < 5: return out
    moving = w[:, 1] >= C.CAM_MOTION_PERCENT
    out["user_motion"] = float(w[:, 1].mean())
    out["user_moving_frac"] = float(moving.mean())
    out["user_motion_bursts"] = float(np.sum(np.diff(moving.astype(int)) == 1) / ((t1 - t0) / 60))
    out["user_motion_freq"] = _dom_freq(w[:, 1], C.CAM_FPS)
    return out


def export_frames(app_path, cam_path, times, t_from, t_to, out_dir, every_s=None, progress=None):
    """Zapisuje co every_s sekund klatkę z fragmentu: oryginał, segmentacja (kontury obiektów),
    przepływ optyczny względem poprzedniej klatki oraz maska ruchu z kamerki. Do sprawozdania."""
    import os
    every_s = every_s or C.FRAME_EXPORT_EVERY_S
    os.makedirs(out_dir, exist_ok=True)
    targets = list(np.arange(t_from, t_to + 1e-9, every_s))
    caps = {k: cv2.VideoCapture(p) for k, p in (("app", app_path), ("cam", cam_path)) if p}
    prev = {"app": None, "cam": None}; n = 0; ti = 0
    stop_i = max(int(np.searchsorted(times, t_to)), 1)
    for i, t in enumerate(times):
        if progress and i % 50 == 0: progress(min(i / stop_i, 1.0))
        frames = {}
        for k, cap in caps.items():
            ok, fr = cap.read()
            if ok: frames[k] = fr
        if "app" not in frames: break
        g = cv2.cvtColor(_resize_w(frames["app"], C.ANALYSIS_WIDTH), cv2.COLOR_BGR2GRAY)
        gc = cv2.GaussianBlur(cv2.cvtColor(_resize_w(frames["cam"], 320), cv2.COLOR_BGR2GRAY), (5, 5), 0) if "cam" in frames else None
        if ti < len(targets) and t >= targets[ti]:
            ti += 1; n += 1
            app_s = _resize_w(frames["app"], C.ANALYSIS_WIDTH)
            # segmentacja
            blur = cv2.GaussianBlur(_clahe.apply(g), (5, 5), 1.2); med = float(np.median(blur))
            edges = cv2.Canny(blur, int(max(0, 0.66 * med)), int(min(255, 1.33 * med + 20)))
            closed = cv2.morphologyEx(cv2.dilate(edges, np.ones((3, 3), np.uint8)), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
            k_, lab, st, _ = cv2.connectedComponentsWithStats((closed == 0).astype(np.uint8), connectivity=4)
            seg = app_s.copy(); A = g.size; cnt = 0
            for j in range(1, k_):
                if C.MIN_OBJ_AREA * A <= st[j, cv2.CC_STAT_AREA] <= C.MAX_OBJ_AREA * A:
                    cnt += 1
                    m = (lab == j).astype(np.uint8)
                    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(seg, cs, -1, (0, 255, 255), 1)
            cv2.putText(seg, f"obiekty: {cnt}", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            # przepływ optyczny
            flow_img = np.zeros_like(app_s)
            if prev["app"] is not None:
                small, ps = _resize_w(g, C.FLOW_WIDTH), _resize_w(prev["app"], C.FLOW_WIDTH)
                fl = cv2.calcOpticalFlowFarneback(ps, small, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                res = fl - np.median(fl.reshape(-1, 2), axis=0)
                mag, ang = cv2.cartToPolar(res[..., 0], res[..., 1])
                hsv = np.zeros((*mag.shape, 3), np.uint8); hsv[..., 0] = ang * 90 / np.pi; hsv[..., 1] = 255
                hsv[..., 2] = np.clip(255 * mag / max(np.percentile(mag, 99), 0.3), 0, 255).astype(np.uint8)
                flow_img = cv2.resize(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), app_s.shape[1::-1])
            cv2.putText(flow_img, "ruch elementow sceny", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            row1 = cv2.hconcat([app_s, seg, flow_img])
            if gc is not None and prev["cam"] is not None:
                _, mk = cv2.threshold(cv2.absdiff(prev["cam"], gc), C.CAM_PIXEL_THRESHOLD, 255, cv2.THRESH_BINARY)
                cam_s = _resize_w(frames["cam"], C.ANALYSIS_WIDTH); mk = cv2.resize(cv2.cvtColor(mk, cv2.COLOR_GRAY2BGR), cam_s.shape[1::-1])
                cv2.putText(mk, f"ruch uzytkownika {100 * (mk[..., 0] > 0).mean():.1f}%", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
                pad = np.zeros((cam_s.shape[0], row1.shape[1] - 2 * cam_s.shape[1], 3), np.uint8)
                row2 = cv2.hconcat([cam_s, mk, pad])
                row1 = cv2.vconcat([row1, row2]) if row2.shape[1] == row1.shape[1] else row1
            cv2.imwrite(os.path.join(out_dir, f"klatka_{int(t // 60):02d}m{t % 60:04.1f}s.png"), row1)
        prev["app"] = g; prev["cam"] = gc
        if t > t_to: break
    for c in caps.values(): c.release()
    return n
