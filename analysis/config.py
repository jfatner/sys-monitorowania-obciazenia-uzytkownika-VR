"""Wszystkie ustawienia analizy w jednym miejscu. Wartości oznaczone (HEURYSTYKA) są
założeniami, które warto zweryfikować po pierwszych prawdziwych sesjach."""

# ---- okna czasowe ----
WIN = 30.0                 # długość okna [s]
STEP = 10.0                # przesunięcie okna [s]

# ---- spoczynek (baseline) ----
# Jeśli w events.csv jest TASK_START, baseline = od początku nagrania do TASK_START.
# W przeciwnym razie baseline = pierwsze BASELINE_DEFAULT_S sekund.
BASELINE_DEFAULT_S = 60.0
MIN_BASELINE_S = 30.0
BASELINE_SKIP_S = 30.0     # pierwsze sekundy spoczynku pomijane (reakcja na nowość VR), o ile zostaje >= MIN_BASELINE_S

# ---- eksport klatek z fragmentu ----
FRAME_EXPORT_EVERY_S = 5.0

# ---- synchronizacja ----
SYNC_MAX_DIFF_S = 120.0    # tag Empatiki szukany w odległości do 2 min od znacznika SYNC

# ---- analiza obrazu ----
APP_FPS = 10.0             # z jaką częstotliwością analizować klatki z gogli
CAM_FPS = 1 / 0.15         # kamera laptopa: co 0.15 s (jak w podglądzie kolegi)
ANALYSIS_WIDTH = 320       # szerokość klatki do segmentacji
FLOW_WIDTH = 160           # szerokość klatki do przepływu optycznego
MIN_OBJ_AREA = 0.0008      # min. pole obiektu jako ułamek klatki
MAX_OBJ_AREA = 0.30
RESIDUAL_FLOW_THR = 15.0   # [px/s przy FLOW_WIDTH] ruch elementu sceny niezależny od ruchu głowy
CAM_PIXEL_THRESHOLD = 20   # jak u kolegi
CAM_MOTION_PERCENT = 1.5   # jak u kolegi

# ---- wskaźnik obciążenia ----
# Każda cecha jest porównywana z wartością w spoczynku (baseline) danej osoby:
#   ("diff",  skala, _)   wynik = (x - b) / skala
#   ("drop",  skala, _)   wynik = (1 - x / b) / skala          (spadek, np. RMSSD)
#   ("log2",  skala, eps) wynik = log2((x + eps) / (b + eps)) / skala   (krotność wzrostu)
# i obcinana do [0, 1]. (HEURYSTYKA - skale dobrane z literatury/zdrowego rozsądku)
NORM = {
    "hr":             ("diff", 25.0, 0),      # +25 bpm wzgl. spoczynku = 1
    "rmssd":          ("drop", 0.6, 0),       # spadek o 60% = 1
    "lf_hf":          ("log2", 2.0, 0.1),     # 4x wzrost = 1
    "eda_tonic":      ("log2", 1.0, 0.05),    # 2x wzrost = 1
    "scr_rate":       ("diff", 8.0, 0),       # +8 reakcji/min = 1
    "user_motion":    ("log2", 2.0, 0.5),     # kamera laptopa, % zmienionych pikseli
    "acc_motion":     ("log2", 2.0, 0.01),    # akcelerometr Empatiki [g]
    "head_motion":    ("log2", 2.0, 5.0),     # ruch całej sceny w goglach [px/s]
    "n_objects":      ("log2", 1.0, 1.0),     # zagęszczenie obiektów w scenie
    "scene_dynamics": ("log2", 2.0, 2.0),     # ruch elementów sceny [px/s]
}
GROUPS = {
    "fizjologia": ["hr", "rmssd", "lf_hf", "eda_tonic", "scr_rate"],
    "ruch":       ["user_motion", "acc_motion", "head_motion"],
    "scena":      ["n_objects", "scene_dynamics"],
}
WEIGHTS = {"fizjologia": 0.6, "ruch": 0.2, "scena": 0.2}   # (HEURYSTYKA)
