#!/usr/bin/env python3
"""Nagrywanie sesji VR: obraz z gogli (Meta Quest przez OBS Virtual Camera) + kamera laptopa.

Na bazie podglądu kolegi. Różnica: do plików trafiają CZYSTE obrazy (bez napisów i maski),
a każda klatka dostaje znacznik czasu, żeby później dopasować obraz do danych z opasek.

Użycie (z głównego folderu projektu):
    python nagrywanie/record_session.py --id P01

Klawisze w oknie podglądu:
    R  - start / stop nagrywania
    M  - znacznik SYNCHRONIZACJI (naciśnij RAZEM z krótkim wciśnięciem przycisku na Empatice)
    T  - start ZADANIA (koniec spoczynku / baseline)
    E  - dowolny inny znacznik (np. "coś się stało")
    S  - zapis kadru podglądu do PNG
    Q  - koniec

Wynik w sesje/<ID>/:
    app.mp4       obraz z gogli (oryginalna rozdzielczość)
    webcam.mp4    obraz z kamery laptopa
    frames.csv    frame,unix_time   (czas każdej klatki - obie kamery czytane w tej samej pętli)
    events.csv    unix_time,event   (SYNC, TASK_START, EVENT)
    info.json     metadane sesji
"""
import argparse, csv, json, os, sys, time
from datetime import datetime

import cv2
import numpy as np

# Indeksy kamer mogą się różnić na innych komputerach (sprawdź --list-cameras).
LAPTOP_CAM_INDEX = 0
QUEST_CAM_INDEX = 1
PREVIEW_WIDTH = 640

# Detektor ruchu na podglądzie (taki sam jak u kolegi; w analizie liczony jest ponownie z pliku).
MOTION_WIDTH = 320
SAMPLE_INTERVAL = 0.15
PIXEL_THRESHOLD = 20
MOTION_PERCENT = 1.5
MOTION_HOLD = 0.45


def resize_to_width(frame, width):
    h, w = frame.shape[:2]
    nh = max(1, round(h * width / w))
    return cv2.resize(frame, (width, nh), interpolation=cv2.INTER_AREA if width < w else cv2.INTER_LINEAR)


def prepare_frame(frame):
    return cv2.GaussianBlur(cv2.cvtColor(resize_to_width(frame, MOTION_WIDTH), cv2.COLOR_BGR2GRAY), (5, 5), 0)


def measure_motion(prev, cur):
    _, mask = cv2.threshold(cv2.absdiff(prev, cur), PIXEL_THRESHOLD, 255, cv2.THRESH_BINARY)
    return mask, 100 * cv2.countNonZero(mask) / mask.size


def draw_status(frame, text, color):
    cv2.rectangle(frame, (0, 0), (frame.shape[1] - 1, 34), (0, 0, 0), -1)
    cv2.putText(frame, text, (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)


def open_source(src, backend):
    """src: numer kamery albo ścieżka do pliku wideo (do testów)."""
    if str(src).isdigit():
        return cv2.VideoCapture(int(src), backend) if backend is not None else cv2.VideoCapture(int(src))
    return cv2.VideoCapture(str(src))


def list_cameras(backend):
    for i in range(6):
        cap = cv2.VideoCapture(i, backend) if backend is not None else cv2.VideoCapture(i)
        ok, fr = cap.read() if cap.isOpened() else (False, None)
        print(f"  kamera {i}: " + (f"OK {fr.shape[1]}x{fr.shape[0]}" if ok else "brak"))
        cap.release()


class Recorder:
    def __init__(self, folder, fps, size_app, size_cam):
        self.folder = folder
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self.w_app = cv2.VideoWriter(os.path.join(folder, "app.mp4"), fourcc, fps, size_app) if size_app else None
        self.w_cam = cv2.VideoWriter(os.path.join(folder, "webcam.mp4"), fourcc, fps, size_cam)
        if not ((self.w_app is None or self.w_app.isOpened()) and self.w_cam.isOpened()):
            raise RuntimeError("Nie udało się utworzyć plików wideo (kodek mp4v).")
        self.f_frames = open(os.path.join(folder, "frames.csv"), "w", newline="")
        self.frames = csv.writer(self.f_frames); self.frames.writerow(["frame", "unix_time"])
        new = not os.path.exists(os.path.join(folder, "events.csv"))
        self.f_events = open(os.path.join(folder, "events.csv"), "a", newline="")
        self.events = csv.writer(self.f_events)
        if new: self.events.writerow(["unix_time", "event"])
        self.n = 0; self.t_first = None; self.t_last = None

    def write(self, fa, fc, t_unix):
        if self.w_app is not None: self.w_app.write(fa)
        self.w_cam.write(fc)
        self.frames.writerow([self.n, f"{t_unix:.4f}"]); self.n += 1
        self.t_first = self.t_first or t_unix; self.t_last = t_unix

    def event(self, name, t_unix):
        self.events.writerow([f"{t_unix:.4f}", name]); self.f_events.flush()

    def close(self):
        if self.w_app is not None: self.w_app.release()
        self.w_cam.release(); self.f_frames.close(); self.f_events.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", help="kod uczestnika, np. P01 (nazwa folderu sesji)")
    ap.add_argument("--root", default="sesje", help="folder na sesje")
    ap.add_argument("--laptop-cam", default=str(LAPTOP_CAM_INDEX))
    ap.add_argument("--quest-cam", default=str(QUEST_CAM_INDEX), help="numer kamery OBS albo 'brak' (test bez gogli)")
    ap.add_argument("--fps", type=float, default=None, help="FPS zapisu pliku; domyślnie mierzone z podglądu (rzeczywiste czasy i tak są w frames.csv)")
    ap.add_argument("--dshow", action="store_true", help="Windows: użyj DirectShow (szybsze otwieranie kamer)")
    ap.add_argument("--list-cameras", action="store_true", help="pokaż dostępne kamery i zakończ")
    ap.add_argument("--no-preview", action="store_true", help="bez okna; nagrywa od razu (do testów)")
    ap.add_argument("--max-seconds", type=float, default=None, help="automatyczny koniec po tylu sekundach")
    a = ap.parse_args()
    backend = cv2.CAP_DSHOW if a.dshow else None

    if a.list_cameras:
        list_cameras(backend); return 0
    if not a.id:
        ap.error("podaj --id (np. --id P01)")
    folder = os.path.join(a.root, a.id)
    if os.path.exists(os.path.join(folder, "app.mp4")):
        print(f"Błąd: {folder} zawiera już nagranie. Użyj innego --id albo przenieś stare pliki.")
        return 1
    os.makedirs(folder, exist_ok=True)

    no_quest = str(a.quest_cam).strip().lower() in ("brak", "none", "-")
    cap_quest = None if no_quest else open_source(a.quest_cam, backend)
    cap_laptop = open_source(a.laptop_cam, backend)
    placeholder = np.zeros((360, 640, 3), np.uint8)
    cv2.putText(placeholder, "TRYB TESTOWY - BEZ GOGLI", (110, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 255), 2)
    rec = None
    try:
        if not cap_laptop.isOpened():
            print(f"Błąd: nie można otworzyć kamery laptopa ({a.laptop_cam}). Sprawdź --list-cameras."); return 1
        if not no_quest and not cap_quest.isOpened():
            print(f"Błąd: nie można otworzyć OBS Virtual Camera ({a.quest_cam}). Czy w OBS kliknięto 'Start Virtual Camera'? "
                  "Test bez gogli: w Ustawieniach kamer wpisz 'brak' jako kamerę gogli."); return 1
        ok1, fq = cap_quest.read() if cap_quest else (True, placeholder); ok2, fl = cap_laptop.read()
        if not (ok1 and ok2):
            print("Błąd odczytu pierwszej klatki."); return 1
        size_app = None if no_quest else (fq.shape[1], fq.shape[0]); size_cam = (fl.shape[1], fl.shape[0])
        print(("Gogle: brak (tryb testowy)" if no_quest else f"Gogle: {size_app[0]}x{size_app[1]}") + f", kamera: {size_cam[0]}x{size_cam[1]}")

        info_path = os.path.join(folder, "info.json")
        info = json.load(open(info_path, encoding="utf-8")) if os.path.exists(info_path) else {}
        info.update(participant=a.id, created=datetime.now().isoformat(timespec="seconds"),
                    app_video=None if no_quest else "app.mp4", webcam_video="webcam.mp4",
                    app_size=size_app, webcam_size=size_cam)
        info.pop("fragment_s", None)                      # nowe nagranie = stary fragment nieaktualny

        # czas: monotoniczny zegar przeliczony na unix (odporny na zmiany zegara systemowego)
        mono0, unix0 = time.monotonic(), time.time()
        now_unix = lambda: unix0 + (time.monotonic() - mono0)

        loop_fps = [None]

        def start():
            fps = a.fps or (round(loop_fps[0], 1) if loop_fps[0] else 30.0)
            info["fps_nominal"] = fps
            r = Recorder(folder, fps, size_app, size_cam)
            info["recording_start_unix"] = now_unix()
            info["recording_start_local"] = datetime.now().isoformat(timespec="milliseconds")
            print(f"● NAGRYWANIE ({fps} fps) - pamiętaj: M razem z przyciskiem Empatiki, T na start zadania")
            return r

        prev_gray, last_sample, last_motion, mask, pct = None, -1e9, -1e9, None, 0.0
        last_event_txt, last_event_t = "", -1e9
        win = "Meta Quest + Kamera Laptopa"
        if not a.no_preview:
            cv2.namedWindow(win, cv2.WINDOW_NORMAL)
            print("R - nagrywanie, M - synchronizacja, T - start zadania, E - znacznik, S - kadr, Q - koniec")
        else:
            rec = start()

        t_prev = None
        while True:
            ok1, fq = cap_quest.read() if cap_quest else (True, placeholder); ok2, fl = cap_laptop.read()
            t = now_unix()
            if t_prev is not None and t > t_prev:              # pomiar rzeczywistej prędkości kamer
                inst = 1.0 / (t - t_prev)
                loop_fps[0] = inst if loop_fps[0] is None else 0.95 * loop_fps[0] + 0.05 * inst
            t_prev = t
            if not (ok1 and ok2):
                print("Koniec obrazu z jednej z kamer - zatrzymuję."); break
            if size_app and fq.shape[1::-1] != size_app: fq = cv2.resize(fq, size_app)
            if fl.shape[1::-1] != size_cam: fl = cv2.resize(fl, size_cam)
            if rec: rec.write(fq, fl, t)
            if a.max_seconds and rec and t - info["recording_start_unix"] >= a.max_seconds:
                break
            if a.no_preview:
                continue

            mono = time.monotonic()
            if mono - last_sample >= SAMPLE_INTERVAL:
                g = prepare_frame(fl)
                if prev_gray is not None and prev_gray.shape == g.shape:
                    mask, pct = measure_motion(prev_gray, g)
                    if pct >= MOTION_PERCENT: last_motion = mono
                prev_gray, last_sample = g, mono

            q = resize_to_width(fq, PREVIEW_WIDTH); l = resize_to_width(fl, PREVIEW_WIDTH)
            if rec:
                el = t - info["recording_start_unix"]
                draw_status(q, f"REC {int(el // 60):02d}:{int(el % 60):02d}  META QUEST", (0, 0, 255))
            else:
                draw_status(q, "PODGLAD (R = nagrywaj)  META QUEST", (255, 255, 255))
            if mask is not None:
                moving = mono - last_motion <= MOTION_HOLD
                draw_status(l, f"KAMERA | {'RUCH' if moving else 'BRAK RUCHU'} | {pct:.1f}%",
                            (0, 200, 255) if moving else (0, 230, 0))
                cv2.imshow("Maska roznic", mask)
            if t - last_event_t < 2.0:
                cv2.putText(q, last_event_txt, (12, q.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
            combined = cv2.vconcat([q, l]) if q.shape[1] == l.shape[1] else q
            hint = "R: nagrywaj/stop  T: start zadania  M: synchronizacja  E: znacznik  Q: koniec"
            cv2.rectangle(combined, (0, combined.shape[0] - 24), (combined.shape[1] - 1, combined.shape[0] - 1), (0, 0, 0), -1)
            cv2.putText(combined, hint, (8, combined.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)
            cv2.imshow(win, combined)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), ord("Q")): break
            if key in (ord("r"), ord("R")):
                if rec is None: rec = start()
                else:
                    print("■ stop nagrywania"); break
            ev = {ord("m"): "SYNC", ord("M"): "SYNC", ord("t"): "TASK_START", ord("T"): "TASK_START",
                  ord("e"): "EVENT", ord("E"): "EVENT"}.get(key)
            if ev:
                if rec:
                    rec.event(ev, t); last_event_txt, last_event_t = f">> {ev}", t; print(f"znacznik {ev}")
                else:
                    print("Znaczniki działają tylko podczas nagrywania (najpierw R).")
            if key in (ord("s"), ord("S")):
                fn = os.path.join(folder, f"kadr_{datetime.now():%Y%m%d_%H%M%S_%f}.png")
                print(("Zapisano " if cv2.imwrite(fn, combined) else "Nie zapisano ") + fn)
    finally:
        cap_laptop.release()
        if cap_quest: cap_quest.release()
        if rec:
            rec.close()
            info.update(recording_end_unix=rec.t_last, n_frames=rec.n,
                        fps_measured=round((rec.n - 1) / (rec.t_last - rec.t_first), 2) if rec.n > 1 else None)
            json.dump(info, open(os.path.join(folder, "info.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)
            print(f"Zapisano {rec.n} klatek ({info['fps_measured']} fps) do {folder}")
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
