#!/usr/bin/env python3
"""Aplikacja do prowadzenia badania (okienka tkinter): uczestnicy, nagrywanie, pliki z opasek,
fragment, ankieta, analiza.

Uruchomienie (z głównego folderu projektu, w środowisku vr):
    python app.py
"""
import glob, json, os, pathlib, re, shutil, subprocess, sys, threading, time, queue, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from tkinter.scrolledtext import ScrolledText

ROOT = os.path.dirname(os.path.abspath(__file__))
SESJE = os.path.join(ROOT, "sesje")
SETTINGS = os.path.join(ROOT, "app_settings.json")
PY = os.environ.get("VR_PYTHON", sys.executable)          # ten sam Python (środowisko vr) dla skryptów
DEFAULTS = {"laptop_cam": "0", "quest_cam": "1", "dshow": True}


def open_path(p):
    if not os.path.exists(p):
        messagebox.showinfo("Brak", f"Nie ma jeszcze:\n{p}"); return
    if sys.platform.startswith("win"):
        os.startfile(p)                                  # noqa  (tylko Windows)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", p])


def conda_paths():
    """Foldery, które 'conda activate' dodaje do PATH - bez nich na Windows biblioteki (numpy/scipy)
    mogą nie znaleźć swoich DLL, gdy aplikacja jest uruchomiona bez aktywacji środowiska."""
    pre = os.path.dirname(os.path.abspath(PY))
    if os.path.basename(pre).lower() in ("bin", "scripts"):
        pre = os.path.dirname(pre)
    cands = [pre, os.path.join(pre, "Library", "mingw-w64", "bin"), os.path.join(pre, "Library", "usr", "bin"),
             os.path.join(pre, "Library", "bin"), os.path.join(pre, "Scripts"), os.path.join(pre, "bin")]
    return [c for c in cands if os.path.isdir(c)]


def mmss_to_s(txt):
    txt = txt.strip()
    m = re.fullmatch(r"(\d{1,3}):(\d{1,2}(?:\.\d+)?)", txt)
    if m: return int(m.group(1)) * 60 + float(m.group(2))
    if re.fullmatch(r"\d+(\.\d+)?", txt): return float(txt)
    raise ValueError(txt)


def s_to_mmss(s):
    return f"{int(s // 60):02d}:{int(round(s % 60)):02d}"


class Participant:
    def __init__(self, pid):
        self.id = pid; self.dir = os.path.join(SESJE, pid)

    def info(self):
        p = os.path.join(self.dir, "info.json")
        try: return json.load(open(p, encoding="utf-8"))
        except Exception: return {}

    def save_info(self, d):
        json.dump(d, open(os.path.join(self.dir, "info.json"), "w", encoding="utf-8"), indent=2, ensure_ascii=False)

    def has_files(self, sub):
        d = os.path.join(self.dir, sub)
        return os.path.isdir(d) and any(os.path.isfile(f) for f in glob.glob(os.path.join(d, "**", "*"), recursive=True))

    def status(self):
        info = self.info()
        return {
            "nagranie": os.path.exists(os.path.join(self.dir, "frames.csv")),
            "polar": self.has_files("polar"),
            "empatica": self.has_files("empatica"),
            "fragment": bool(info.get("fragment_s")),
            "ankieta": bool(glob.glob(os.path.join(self.dir, "ankieta*.json"))),
            "analiza": os.path.exists(os.path.join(self.dir, "wyniki", "podsumowanie.json")),
        }

    def duration(self):
        info = self.info()
        if info.get("recording_end_unix") and info.get("recording_start_unix"):
            return info["recording_end_unix"] - info["recording_start_unix"]
        f = os.path.join(self.dir, "frames.csv")                # zapas: z czasów klatek
        if os.path.exists(f):
            try:
                with open(f) as fh:
                    lines = [l for l in fh.read().splitlines()[1:] if l.strip()]
                return float(lines[-1].split(",")[1]) - float(lines[0].split(",")[1])
            except Exception:
                return None
        return None


STATUS_LABELS = [("nagranie", "Nagranie"), ("polar", "Polar"), ("empatica", "Empatica"),
                 ("fragment", "Fragment"), ("ankieta", "Ankieta"), ("analiza", "Analiza")]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Monitor obciążenia VR")
        self.geometry("1060x700"); self.minsize(900, 600)
        os.makedirs(SESJE, exist_ok=True)
        self.settings = {**DEFAULTS, **(json.load(open(SETTINGS)) if os.path.exists(SETTINGS) else {})}
        self.proc_q = queue.Queue(); self.busy = False
        self._build()
        self.refresh_list()
        self.after(150, self._pump)

    # ---------------- interfejs ----------------
    def _build(self):
        style = ttk.Style(self)
        try: style.theme_use("clam")
        except tk.TclError: pass
        style.configure("H.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Ok.TLabel", foreground="#1b7f3b"); style.configure("No.TLabel", foreground="#9a9a9a")
        style.configure("Big.TButton", padding=(10, 6))

        main = ttk.PanedWindow(self, orient="horizontal"); main.pack(fill="both", expand=True, padx=8, pady=8)

        # --- lewa: uczestnicy ---
        left = ttk.Frame(main, padding=4); main.add(left, weight=1)
        ttk.Label(left, text="Uczestnicy", style="H.TLabel").pack(anchor="w")
        self.lb = tk.Listbox(left, font=("Consolas", 11), activestyle="none", exportselection=False)
        self.lb.pack(fill="both", expand=True, pady=4)
        self.lb.bind("<<ListboxSelect>>", lambda e: self.show_selected())
        ttk.Button(left, text="+ Dodaj uczestnika", command=self.add_participant).pack(fill="x")
        ttk.Button(left, text="Ustawienia kamer", command=self.edit_settings).pack(fill="x", pady=(4, 0))
        ttk.Separator(left).pack(fill="x", pady=8)
        ttk.Button(left, text="Zestawienie wszystkich\n(korelacje z ankietami)", command=self.run_eval,
                   style="Big.TButton").pack(fill="x")

        # --- prawa: wybrany uczestnik ---
        right = ttk.Frame(main, padding=(10, 4)); main.add(right, weight=3)
        self.title_lbl = ttk.Label(right, text="Wybierz albo dodaj uczestnika", style="H.TLabel"); self.title_lbl.pack(anchor="w")
        st = ttk.Frame(right); st.pack(anchor="w", pady=(4, 8))
        self.st_lbls = {}
        for k, name in STATUS_LABELS:
            l = ttk.Label(st, text=f"○ {name}", style="No.TLabel"); l.pack(side="left", padx=(0, 14)); self.st_lbls[k] = l

        steps = ttk.Frame(right); steps.pack(fill="x")
        steps.columnconfigure(1, weight=1)
        r = 0
        def row(num, text):
            nonlocal r
            ttk.Label(steps, text=f"{num}.", width=3).grid(row=r, column=0, sticky="nw", pady=4)
            f = ttk.Frame(steps); f.grid(row=r, column=1, sticky="ew", pady=4)
            ttk.Label(f, text=text, width=24).pack(side="left")
            r += 1
            return f

        f = row(1, "Nagranie sesji")
        self.b_rec = ttk.Button(f, text="Nagraj sesję", command=self.record); self.b_rec.pack(side="left")
        ttk.Button(f, text="Obejrzyj nagranie", command=lambda: self._open_in("app.mp4")).pack(side="left", padx=4)
        ttk.Button(f, text="Kamera", command=lambda: self._open_in("webcam.mp4")).pack(side="left")

        f = row(2, "Pliki z opasek")
        ttk.Button(f, text="Dodaj pliki Polar…", command=lambda: self.add_files("polar", [("Polar", "*.txt *.csv"), ("Wszystkie", "*.*")])).pack(side="left")
        ttk.Button(f, text="Dodaj pliki Empatica…", command=lambda: self.add_files("empatica", [("Empatica", "*.zip *.csv *.avro"), ("Wszystkie", "*.*")])).pack(side="left", padx=4)
        ttk.Button(f, text="Dodaj folder Empatica…", command=self.add_emp_folder).pack(side="left")

        f = row(3, "Fragment do analizy")
        ttk.Label(f, text="od").pack(side="left")
        self.e_from = ttk.Entry(f, width=7); self.e_from.pack(side="left", padx=3)
        ttk.Label(f, text="do").pack(side="left")
        self.e_to = ttk.Entry(f, width=7); self.e_to.pack(side="left", padx=3)
        ttk.Label(f, text="(mm:ss)").pack(side="left")
        ttk.Button(f, text="Zapisz", command=self.save_fragment).pack(side="left", padx=4)
        ttk.Button(f, text="Cała sesja", command=self.clear_fragment).pack(side="left")
        self.dur_lbl = ttk.Label(f, text="", style="No.TLabel"); self.dur_lbl.pack(side="left", padx=8)

        f = row(4, "Ankieta")
        ttk.Button(f, text="Otwórz formularz", command=lambda: webbrowser.open(pathlib.Path(ROOT, "evaluation", "ankieta.html").as_uri())).pack(side="left")
        ttk.Button(f, text="Wczytaj z Pobranych", command=self.import_survey).pack(side="left", padx=4)
        ttk.Button(f, text="Wskaż plik…", command=self.import_survey_manual).pack(side="left")

        f = row(5, "Analiza")
        self.b_an = ttk.Button(f, text="▶ Analizuj", command=self.analyze, style="Big.TButton"); self.b_an.pack(side="left")
        ttk.Button(f, text="Wykres", command=lambda: self._open_in("wyniki", "przebieg.png")).pack(side="left", padx=4)
        ttk.Button(f, text="Klatki", command=lambda: self._open_in("wyniki", "klatki")).pack(side="left")
        ttk.Button(f, text="Folder sesji", command=lambda: self._open_in()).pack(side="left", padx=4)

        pf = ttk.Frame(right); pf.pack(fill="x", pady=(12, 0))
        style = ttk.Style(self); style.configure("Pct.TLabel", font=("Segoe UI", 14, "bold"))
        bar_row = ttk.Frame(pf); bar_row.pack(fill="x")
        self.pct_lbl = ttk.Label(bar_row, text="0%", style="Pct.TLabel", width=5, anchor="e"); self.pct_lbl.pack(side="right", padx=(8, 0))
        self.pbar = ttk.Progressbar(bar_row, mode="determinate", maximum=100); self.pbar.pack(side="left", fill="x", expand=True, ipady=4)
        self.plbl = ttk.Label(pf, text="", style="No.TLabel"); self.plbl.pack(anchor="w")

        ttk.Label(right, text="Komunikaty", style="H.TLabel").pack(anchor="w", pady=(8, 2))
        self.log = ScrolledText(right, height=14, font=("Consolas", 9), wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("warn", foreground="#b35c00"); self.log.tag_configure("err", foreground="#c0392b")
        self.log.tag_configure("ok", foreground="#1b7f3b")

    # ---------------- pomocnicze ----------------
    def write(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text if text.endswith("\n") else text + "\n", tag)
        self.log.see("end"); self.log.configure(state="disabled")

    def current(self):
        sel = self.lb.curselection()
        if not sel:
            messagebox.showinfo("Uczestnik", "Najpierw wybierz uczestnika z listy."); return None
        return Participant(self.ids[sel[0]])

    def _open_in(self, *parts):
        p = self.current()
        if p: open_path(os.path.join(p.dir, *parts))

    def refresh_list(self, select=None):
        prev = select or (self.ids[self.lb.curselection()[0]] if getattr(self, "ids", None) and self.lb.curselection() else None)
        self.ids = sorted(d for d in os.listdir(SESJE) if os.path.isdir(os.path.join(SESJE, d)) and not d.startswith(("_", ".")))
        self.lb.delete(0, "end")
        for pid in self.ids:
            s = Participant(pid).status()
            marks = "".join("●" if s[k] else "·" for k, _ in STATUS_LABELS)
            self.lb.insert("end", f"{pid:<12} {marks}")
        if prev in self.ids:
            i = self.ids.index(prev); self.lb.selection_set(i); self.lb.see(i)
        self.show_selected()

    def show_selected(self):
        sel = self.lb.curselection()
        if not sel:
            return
        p = Participant(self.ids[sel[0]]); s = p.status()
        self.title_lbl.configure(text=f"Uczestnik {p.id}")
        for k, name in STATUS_LABELS:
            self.st_lbls[k].configure(text=f"{'✔' if s[k] else '○'} {name}", style="Ok.TLabel" if s[k] else "No.TLabel")
        fr = p.info().get("fragment_s")
        for e, v in ((self.e_from, fr[0] if fr else None), (self.e_to, fr[1] if fr else None)):
            e.delete(0, "end")
            if v is not None: e.insert(0, s_to_mmss(v))
        d = p.duration()
        self.dur_lbl.configure(text=f"nagranie: {s_to_mmss(d)}" if d else "")

    # ---------------- akcje ----------------
    def add_participant(self):
        n = len(self.ids) + 1
        sugg = next(f"P{i:02d}" for i in range(n, n + 1000) if f"P{i:02d}" not in self.ids)
        pid = simpledialog.askstring("Nowy uczestnik", "Kod uczestnika (bez imienia i nazwiska):", initialvalue=sugg, parent=self)
        if not pid: return
        pid = pid.strip()
        if not re.fullmatch(r"[\w\-]{1,40}", pid):
            messagebox.showerror("Kod", "Kod może zawierać litery, cyfry, '-' i '_' (bez spacji)."); return
        if pid in self.ids:
            messagebox.showerror("Kod", f"{pid} już istnieje."); return
        os.makedirs(os.path.join(SESJE, pid, "polar")); os.makedirs(os.path.join(SESJE, pid, "empatica"))
        Participant(pid).save_info({"participant": pid})
        self.write(f"Dodano uczestnika {pid}", "ok"); self.refresh_list(select=pid)

    def edit_settings(self):
        w = tk.Toplevel(self); w.title("Ustawienia kamer"); w.transient(self); w.grab_set()
        vals = {}
        for i, (k, lab) in enumerate((("laptop_cam", "Numer kamery laptopa"), ("quest_cam", "Numer kamery OBS (gogle) albo 'brak'"))):
            ttk.Label(w, text=lab).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            e = ttk.Entry(w, width=6); e.insert(0, str(self.settings[k])); e.grid(row=i, column=1, padx=8); vals[k] = e
        dv = tk.BooleanVar(value=self.settings["dshow"])
        ttk.Checkbutton(w, text="DirectShow (Windows, szybsze otwieranie kamer)", variable=dv).grid(row=2, column=0, columnspan=2, sticky="w", padx=8)
        def test():
            self.run_script([os.path.join(ROOT, "nagrywanie", "record_session.py"), "--list-cameras"] + (["--dshow"] if dv.get() else []), "Kamery")
        def save():
            self.settings.update({k: e.get().strip() for k, e in vals.items()}, dshow=dv.get())
            json.dump(self.settings, open(SETTINGS, "w"), indent=2); w.destroy()
        ttk.Button(w, text="Sprawdź dostępne kamery", command=test).grid(row=3, column=0, padx=8, pady=8, sticky="w")
        ttk.Button(w, text="Zapisz", command=save).grid(row=3, column=1, padx=8, pady=8)

    def record(self):
        p = self.current()
        if not p: return
        if p.status()["nagranie"]:
            if not messagebox.askyesno("Nagranie istnieje", f"{p.id} ma już nagranie. Przenieść stare pliki do folderu 'stare_nagranie' i nagrać od nowa?"):
                return
            old = os.path.join(p.dir, "stare_nagranie"); os.makedirs(old, exist_ok=True)
            for fn in ("app.mp4", "webcam.mp4", "frames.csv", "events.csv"):
                if os.path.exists(os.path.join(p.dir, fn)): shutil.move(os.path.join(p.dir, fn), os.path.join(old, fn))
        self.write(f"\n=== Nagrywanie {p.id} ===\nW oknie podglądu: R = start/stop nagrywania, T = start zadania "
                   f"(koniec spoczynku), Q = koniec. Instrukcja klawiszy jest też na dole okna.", "ok")
        args = [os.path.join(ROOT, "nagrywanie", "record_session.py"), "--id", p.id, "--root", SESJE,
                "--laptop-cam", str(self.settings["laptop_cam"]), "--quest-cam", str(self.settings["quest_cam"])]
        if self.settings.get("dshow") and sys.platform.startswith("win"): args.append("--dshow")
        self.run_script(args, "Nagrywanie")

    def add_files(self, sub, types):
        p = self.current()
        if not p: return
        files = filedialog.askopenfilenames(title=f"Pliki {sub} dla {p.id}", filetypes=types, parent=self)
        if not files: return
        dst = os.path.join(p.dir, sub); os.makedirs(dst, exist_ok=True)
        for f in files:
            shutil.copy2(f, dst); self.write(f"skopiowano do {sub}/: {os.path.basename(f)}")
        self.refresh_list()

    def add_emp_folder(self):
        p = self.current()
        if not p: return
        src = filedialog.askdirectory(title=f"Folder z eksportem Empatiki dla {p.id}", parent=self)
        if not src: return
        dst = os.path.join(p.dir, "empatica", os.path.basename(src.rstrip("/\\")))
        shutil.copytree(src, dst, dirs_exist_ok=True); self.write(f"skopiowano folder do empatica/: {os.path.basename(dst)}")
        self.refresh_list()

    def save_fragment(self):
        p = self.current()
        if not p: return
        try:
            a, b = mmss_to_s(self.e_from.get()), mmss_to_s(self.e_to.get())
        except ValueError:
            messagebox.showerror("Fragment", "Wpisz czas jako mm:ss, np. 03:20"); return
        d = p.duration()
        if b <= a or (d and a >= d):
            messagebox.showerror("Fragment", "Koniec musi być po początku i w obrębie nagrania."); return
        info = p.info(); info["fragment_s"] = [a, min(b, d) if d else b]; p.save_info(info)
        self.write(f"{p.id}: fragment {s_to_mmss(a)}–{s_to_mmss(info['fragment_s'][1])} zapisany", "ok"); self.refresh_list()

    def clear_fragment(self):
        p = self.current()
        if not p: return
        info = p.info(); info.pop("fragment_s", None); p.save_info(info)
        self.write(f"{p.id}: analiza całej sesji (bez fragmentu)"); self.refresh_list()

    def import_survey(self):
        p = self.current()
        if not p: return
        cands = []
        for d in (os.path.join(os.path.expanduser("~"), "Downloads"), os.path.join(os.path.expanduser("~"), "Pobrane")):
            cands += glob.glob(os.path.join(d, f"ankieta_{p.id}*.json"))
        if not cands:
            messagebox.showinfo("Ankieta", f"Nie znalazłem ankieta_{p.id}.json w Pobranych. Użyj 'Wskaż plik…'."); return
        self._take_survey(p, max(cands, key=os.path.getmtime))

    def import_survey_manual(self):
        p = self.current()
        if not p: return
        f = filedialog.askopenfilename(title="Plik ankiety", filetypes=[("Ankieta", "*.json")], parent=self)
        if f: self._take_survey(p, f)

    def _take_survey(self, p, f):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            messagebox.showerror("Ankieta", f"Nie da się odczytać pliku: {e}"); return
        if d.get("id") and d["id"] != p.id and not messagebox.askyesno("Ankieta", f"Ankieta jest dla {d['id']}, a wybrany jest {p.id}. Mimo to przypisać?"):
            return
        shutil.copy2(f, os.path.join(p.dir, f"ankieta_{p.id}.json"))
        self.write(f"{p.id}: wczytano ankietę (RTLX = {d.get('rtlx')})", "ok"); self.refresh_list()

    def analyze(self):
        p = self.current()
        if not p: return
        s = p.status()
        if not (s["nagranie"] or s["polar"] or s["empatica"]):
            messagebox.showinfo("Analiza", "Brak danych: najpierw nagranie i/lub pliki z opasek."); return
        self.write(f"\n=== Analiza {p.id} ===")
        self.run_script([os.path.join(ROOT, "analysis", "process_session.py"), p.dir], "Analiza",
                        on_done=lambda ok: ok and os.path.exists(os.path.join(p.dir, "wyniki", "przebieg.png"))
                        and open_path(os.path.join(p.dir, "wyniki", "przebieg.png")))

    def run_eval(self):
        self.write("\n=== Zestawienie wszystkich uczestników ===")
        self.run_script([os.path.join(ROOT, "evaluation", "evaluate.py"), SESJE], "Zestawienie",
                        on_done=lambda ok: ok and open_path(os.path.join(SESJE, "_ewaluacja")))

    # ---------------- uruchamianie skryptów w tle ----------------
    def run_script(self, args, name, on_done=None):
        if self.busy:
            messagebox.showinfo("Zajęte", "Poczekaj, aż skończy się poprzednie zadanie."); return
        self.busy = True; self.t_job = time.time(); self.job_name = name; self.got_progress = False
        for b in (self.b_rec, self.b_an): b.state(["disabled"])
        self.pbar.configure(mode="indeterminate", value=0); self.pbar.start(12); self.pct_lbl.configure(text="…")
        self.plbl.configure(text=f"{name}: pracuję…")
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "VR_PROGRESS": "1"}
        env["PATH"] = os.pathsep.join(conda_paths() + [env.get("PATH", "")])   # jak "conda activate" (DLL-e)

        def work():
            try:
                pr = subprocess.Popen([PY, "-u", "-X", "faulthandler"] + args, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      env=env, text=True, encoding="utf-8", errors="replace",
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for line in pr.stdout:
                    self.proc_q.put(("line", line.rstrip("\n")))
                code = pr.wait()
            except Exception as e:
                self.proc_q.put(("line", f"BŁĄD uruchomienia: {e}")); code = -1
            self.proc_q.put(("done", (name, code, on_done)))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _fmt(s):
        s = int(round(s))
        return f"{s // 60} min {s % 60:02d} s" if s >= 60 else f"{s} s"

    def _pump(self):
        try:
            while True:
                kind, val = self.proc_q.get_nowait()
                if kind == "line" and val.startswith("@@PROGRESS"):
                    parts = val.split(" ", 2)
                    try: pct = float(parts[1])
                    except (IndexError, ValueError): continue
                    label = parts[2] if len(parts) > 2 else ""
                    if not self.got_progress:
                        self.got_progress = True; self.pbar.stop(); self.pbar.configure(mode="determinate")
                    self.pbar.configure(value=pct); self.pct_lbl.configure(text=f"{pct:.0f}%")
                    el = time.time() - self.t_job
                    eta = f" · zostało ok. {self._fmt(el * (100 - pct) / pct)}" if 3 <= pct < 100 and el > 3 else ""
                    self.plbl.configure(text=f"{self.job_name}: {label} - {pct:.0f}%{eta}")
                    continue
                if kind == "line":
                    tag = "warn" if val.strip().startswith("!") else ("err" if "BŁĄD" in val or "Traceback" in val or "Error" in val else None)
                    self.write(val, tag)
                else:
                    name, code, cb = val
                    self.busy = False
                    self.pbar.stop(); self.pbar.configure(mode="determinate", value=100 if code == 0 else 0)
                    self.pct_lbl.configure(text="100%" if code == 0 else "✖")
                    self.plbl.configure(text=f"{name}: {'gotowe' if code == 0 else 'błąd - szczegóły w komunikatach'} "
                                             f"({self._fmt(time.time() - self.t_job)})")
                    for b in (self.b_rec, self.b_an): b.state(["!disabled"])
                    self.write(f"{name}: {'zakończono' if code == 0 else f'zakończono z błędem (kod {code})'}", "ok" if code == 0 else "err")
                    if code not in (0, 1, 2, -1):
                        self.write("To błąd systemu Windows (np. brak pliku DLL), a nie błąd danych. Uruchom aplikację z terminala "
                                   "z aktywnym środowiskiem (conda activate D:\\srodowiska\\vr, potem python app.py) "
                                   "i przyślij komunikaty.", "warn")
                    self.refresh_list()
                    if cb: cb(code == 0)
        except queue.Empty:
            pass
        self.after(150, self._pump)


def enable_dpi_awareness():
    """Windows: bez tego przy skalowaniu ekranu 125-150% okno jest rozciągane jak obrazek i wygląda na rozmyte."""
    if not sys.platform.startswith("win"):
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # per-monitor DPI aware
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


if __name__ == "__main__":
    enable_dpi_awareness()
    App().mainloop()
