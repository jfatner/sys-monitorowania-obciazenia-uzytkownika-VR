#!/usr/bin/env python3
"""Monitor obciążenia VR - aplikacja w przeglądarce.

Działa w całości lokalnie, na Twoim komputerze (bez internetu i bez dodatkowych bibliotek):
mały serwer w Pythonie + strona otwierana w przeglądarce.

Uruchomienie (z głównego folderu projektu, w środowisku vr):
    python app.py
Zamknięcie: Ctrl+C w terminalu.

Klasyczna wersja w okienkach: python app_tk.py
"""
import glob, json, mimetypes, os, re, shutil, socket, subprocess, sys, threading, time, urllib.parse, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
SESJE = os.path.join(ROOT, "sesje")
WEB = os.path.join(ROOT, "web")
SETTINGS = os.path.join(ROOT, "app_settings.json")
PY = os.environ.get("VR_PYTHON", sys.executable)
DEFAULTS = {"laptop_cam": "0", "quest_cam": "1", "dshow": True}
ID_RE = re.compile(r"^[\w\-]{1,40}$")
STEPS = ["nagranie", "polar", "empatica", "fragment", "ankieta", "analiza"]


# ======================= pomocnicze =======================

def conda_paths():
    """Foldery, które 'conda activate' dodaje do PATH (na Windows bez nich numpy/scipy nie znajdą DLL)."""
    pre = os.path.dirname(os.path.abspath(PY))
    if os.path.basename(pre).lower() in ("bin", "scripts"):
        pre = os.path.dirname(pre)
    c = [pre, os.path.join(pre, "Library", "mingw-w64", "bin"), os.path.join(pre, "Library", "usr", "bin"),
         os.path.join(pre, "Library", "bin"), os.path.join(pre, "Scripts"), os.path.join(pre, "bin")]
    return [x for x in c if os.path.isdir(x)]


def open_local(path):
    """Otwiera plik/folder w systemie (Eksplorator, odtwarzacz, przeglądarka obrazów)."""
    if not os.path.exists(path):
        return False
    if sys.platform.startswith("win"):
        os.startfile(path)                                    # noqa: tylko Windows
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def settings():
    return {**DEFAULTS, **(read_json(SETTINGS, {}) or {})}


def safe_join(base, *parts):
    """Ścieżka wewnątrz base (bez wychodzenia '..')."""
    p = os.path.realpath(os.path.join(base, *parts))
    if p != os.path.realpath(base) and not p.startswith(os.path.realpath(base) + os.sep):
        raise PermissionError(p)
    return p


def clean_name(n):
    n = os.path.basename(n.replace("\\", "/"))
    n = re.sub(r"[^\w\-. ()]", "_", n).strip(" .")
    return n or "plik"


# ======================= uczestnik =======================

class Participant:
    def __init__(self, pid):
        if not ID_RE.match(pid):
            raise ValueError("zły kod uczestnika")
        self.id = pid
        self.dir = os.path.join(SESJE, pid)

    def exists(self):
        return os.path.isdir(self.dir)

    def info(self):
        return read_json(os.path.join(self.dir, "info.json"), {}) or {}

    def save_info(self, d):
        with open(os.path.join(self.dir, "info.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)

    def files(self, sub):
        d = os.path.join(self.dir, sub)
        out = []
        for p in sorted(glob.glob(os.path.join(d, "**", "*"), recursive=True)):
            if os.path.isfile(p) and "digital_biomarkers" not in p.replace("\\", "/"):
                out.append({"name": os.path.relpath(p, d).replace("\\", "/"), "size": os.path.getsize(p)})
        return out

    def duration(self):
        info = self.info()
        if info.get("recording_end_unix") and info.get("recording_start_unix"):
            return info["recording_end_unix"] - info["recording_start_unix"]
        f = os.path.join(self.dir, "frames.csv")
        if os.path.exists(f):
            try:
                with open(f) as fh:
                    lines = [l for l in fh.read().splitlines()[1:] if l.strip()]
                return float(lines[-1].split(",")[1]) - float(lines[0].split(",")[1])
            except Exception:
                return None
        return None

    def events(self):
        """Znaczniki z nagrywarki (SYNC, TASK_START, EVENT) w sekundach od startu nagrania."""
        ev, fr = os.path.join(self.dir, "events.csv"), os.path.join(self.dir, "frames.csv")
        if not (os.path.exists(ev) and os.path.exists(fr)):
            return []
        try:
            with open(fr) as f:
                f.readline(); t0 = float(f.readline().split(",")[1])
            out = []
            with open(ev, encoding="utf-8") as f:
                for line in f.read().splitlines()[1:]:
                    if line.strip():
                        t, name = line.split(",", 1)
                        out.append({"t": round(float(t) - t0, 1), "name": name.strip()})
            return out
        except Exception:
            return []

    def survey(self):
        a = sorted(glob.glob(os.path.join(self.dir, "ankieta*.json")))
        return read_json(a[-1]) if a else None

    def summary(self):
        return read_json(os.path.join(self.dir, "wyniki", "podsumowanie.json"))

    def status(self):
        return {
            "nagranie": os.path.exists(os.path.join(self.dir, "frames.csv")),
            "polar": bool(self.files("polar")),
            "empatica": bool(self.files("empatica")),
            "fragment": bool(self.info().get("fragment_s")),
            "ankieta": self.survey() is not None,
            "analiza": self.summary() is not None,
        }

    def brief(self):
        s, sv, sm = self.status(), self.survey(), self.summary()
        return {"id": self.id, "status": s, "done": sum(s.values()),
                "rtlx": (sv or {}).get("rtlx"),
                "peak": (sm or {}).get("peak_load_index"),
                "warnings": len((sm or {}).get("warnings", []))}

    def detail(self):
        d = self.brief()
        info, sm, sv = self.info(), self.summary(), self.survey()
        wyn = os.path.join(self.dir, "wyniki")
        plot = os.path.join(wyn, "przebieg.png")
        d.update(
            duration=self.duration(), fragment=info.get("fragment_s"),
            has_app_video=os.path.exists(os.path.join(self.dir, "app.mp4")),
            has_webcam_video=os.path.exists(os.path.join(self.dir, "webcam.mp4")),
            polar_files=self.files("polar"), empatica_files=self.files("empatica"),
            survey=None if not sv else {k: sv.get(k) for k in
                                        ("rtlx", "stres_1_5", "najwieksze_napiecie_czas", "mental", "physical",
                                         "temporal", "performance", "effort", "frustration")},
            plot_version=int(os.path.getmtime(plot)) if os.path.exists(plot) else None,
            frames=sorted(os.path.basename(p) for p in glob.glob(os.path.join(wyn, "klatki", "*.png"))),
            events=self.events(),
            results=None)
        if sm:
            tm, base = sm.get("task_mean", {}) or {}, sm.get("baseline", {}) or {}
            d["results"] = {
                "part": sm.get("analysed_part"), "fragment": sm.get("fragment_s"),
                "dur": sm.get("dur_s"), "baseline": sm.get("baseline_s"),
                "load_mean": tm.get("load_index"), "peak": sm.get("peak_load_index"), "peak_time": sm.get("peak_time_s"),
                "idx": {g: tm.get(f"idx_{g}") for g in ("fizjologia", "ruch", "scena")},
                "hr": tm.get("hr"), "hr_base": base.get("hr"), "hr_delta": sm.get("hr_delta"),
                "rmssd": tm.get("rmssd"), "rmssd_base": base.get("rmssd"), "rmssd_ratio": sm.get("rmssd_ratio"),
                "eda": tm.get("eda_tonic"), "eda_ratio": sm.get("eda_tonic_ratio"),
                "user_motion": tm.get("user_motion"), "n_objects": tm.get("n_objects"),
                "polar_source": sm.get("polar_source"), "warnings": sm.get("warnings", []),
            }
        return d


def list_participants():
    os.makedirs(SESJE, exist_ok=True)
    ids = sorted(d for d in os.listdir(SESJE)
                 if os.path.isdir(os.path.join(SESJE, d)) and not d.startswith(("_", ".")) and ID_RE.match(d))
    return [Participant(i).brief() for i in ids]


# ======================= zadania w tle (nagrywanie, analiza, zestawienie) =======================

class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"running": False, "name": None, "pid": None, "pct": None, "label": "", "code": None,
                      "started": None, "ended": None, "seq": 0}
        self.lines = []

    def snapshot(self, since=0):
        with self.lock:
            s = dict(self.state)
            s["lines"] = self.lines[since:]
            s["next"] = len(self.lines)
            s["elapsed"] = (s["ended"] or time.time()) - s["started"] if s["started"] else None
            return s

    def start(self, name, args, pid=None):
        with self.lock:
            if self.state["running"]:
                return False
            self.lines = []
            self.state.update(running=True, name=name, pid=pid, pct=None, label="", code=None,
                              started=time.time(), ended=None, seq=self.state["seq"] + 1)
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", "VR_PROGRESS": "1"}
        env["PATH"] = os.pathsep.join(conda_paths() + [env.get("PATH", "")])
        threading.Thread(target=self._run, args=(args, env), daemon=True).start()
        return True

    def _run(self, args, env):
        code = -1
        try:
            pr = subprocess.Popen([PY, "-u", "-X", "faulthandler"] + args, cwd=ROOT, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, env=env, text=True, encoding="utf-8", errors="replace",
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            for line in pr.stdout:
                line = line.rstrip("\n")
                with self.lock:
                    if line.startswith("@@PROGRESS"):
                        parts = line.split(" ", 2)
                        try:
                            self.state["pct"] = float(parts[1]); self.state["label"] = parts[2] if len(parts) > 2 else ""
                        except (IndexError, ValueError):
                            pass
                    else:
                        self.lines.append(line)
            code = pr.wait()
        except Exception as e:
            with self.lock:
                self.lines.append(f"BŁĄD uruchomienia: {e}")
        with self.lock:
            if code not in (0, 1, 2, -1):
                self.lines.append("To błąd systemu Windows (np. brak pliku DLL), a nie błąd danych. "
                                  "Uruchom aplikację z terminala z aktywnym środowiskiem conda.")
            self.state.update(running=False, code=code, ended=time.time())
            if code == 0:
                self.state["pct"] = 100.0


JOB = Job()

REQUIRED = ["numpy", "scipy", "pandas", "matplotlib", "cv2"]
ENV = {"ok": None, "missing": [], "python": PY}


def check_env():
    """Sprawdza, czy Python, którym liczona jest analiza, ma potrzebne biblioteki."""
    code = ("import importlib.util as u, json; "
            f"print(json.dumps([m for m in {REQUIRED!r} if u.find_spec(m) is None]))")
    env = {**os.environ, "PATH": os.pathsep.join(conda_paths() + [os.environ.get("PATH", "")])}
    try:
        out = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=60, env=env,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip()
        ENV["missing"] = json.loads(out.splitlines()[-1]) if out else REQUIRED
    except Exception:
        ENV["missing"] = REQUIRED
    ENV["ok"] = not ENV["missing"]
    return ENV


# ======================= HTTP =======================

class Handler(BaseHTTPRequestHandler):
    server_version = "VRMonitor/1.0"

    def log_message(self, fmt, *args):                       # cisza w terminalu
        pass

    # --- odpowiedzi ---
    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False, default=float).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(b)

    def send_err(self, msg, code=400):
        self.send_json({"error": msg}, code)

    def send_file(self, path, cache=False):
        if not os.path.isfile(path):
            return self.send_err("nie ma takiego pliku", 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    def body(self, limit=500 * 1024 * 1024):
        n = int(self.headers.get("Content-Length") or 0)
        if n > limit:
            raise ValueError("plik za duży")
        return self.rfile.read(n) if n else b""

    def jbody(self):
        b = self.body(5 * 1024 * 1024)
        return json.loads(b.decode("utf-8")) if b else {}

    # --- routing ---
    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_DELETE(self):
        self.route("DELETE")

    def route(self, method):
        u = urllib.parse.urlparse(self.path)
        path, q = urllib.parse.unquote(u.path), urllib.parse.parse_qs(u.query)
        try:
            for m, pat, fn in ROUTES:
                if m == method:
                    mt = re.fullmatch(pat, path)
                    if mt:
                        return fn(self, q, *mt.groups())
            self.send_err("nieznany adres", 404)
        except PermissionError:
            self.send_err("niedozwolona ścieżka", 403)
        except (ValueError, KeyError) as e:
            self.send_err(str(e) or "złe dane", 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:                                # nie wywracaj serwera
            try:
                self.send_err(f"błąd serwera: {e}", 500)
            except Exception:
                pass

    # --- strony ---
    def h_index(self, q):
        self.send_file(os.path.join(WEB, "index.html"))

    def h_static(self, q, rel):
        self.send_file(safe_join(WEB, rel))

    def h_survey_form(self, q):
        self.send_file(os.path.join(ROOT, "evaluation", "ankieta.html"))

    def h_session_file(self, q, pid, rel):
        p = Participant(pid)
        self.send_file(safe_join(p.dir, rel))

    def h_eval_file(self, q, rel):
        self.send_file(safe_join(os.path.join(SESJE, "_ewaluacja"), rel))

    # --- API: uczestnicy ---
    def h_list(self, q):
        self.send_json({"participants": list_participants(), "job": JOB.snapshot(10**9), "env": ENV})

    def h_create(self, q):
        pid = (self.jbody().get("id") or "").strip()
        if not ID_RE.match(pid):
            return self.send_err("Kod może zawierać litery, cyfry, '-' i '_' (bez spacji, do 40 znaków).")
        p = Participant(pid)
        if p.exists():
            return self.send_err(f"{pid} już istnieje.", 409)
        os.makedirs(os.path.join(p.dir, "polar")); os.makedirs(os.path.join(p.dir, "empatica"))
        p.save_info({"participant": pid})
        self.send_json(p.detail())

    def h_detail(self, q, pid):
        p = Participant(pid)
        if not p.exists():
            return self.send_err("nie ma takiego uczestnika", 404)
        self.send_json(p.detail())

    def h_fragment(self, q, pid):
        p = Participant(pid); b = self.jbody()
        info = p.info()
        if b.get("clear"):
            info.pop("fragment_s", None)
        else:
            a, e = float(b["from"]), float(b["to"])
            d = p.duration()
            if e <= a or a < 0 or (d and a >= d):
                return self.send_err("Koniec musi być po początku i w obrębie nagrania.")
            info["fragment_s"] = [a, min(e, d) if d else e]
        p.save_info(info)
        self.send_json(p.detail())

    def h_upload(self, q, pid):
        p = Participant(pid)
        kind = (q.get("kind") or [""])[0]
        if kind not in ("polar", "empatica"):
            return self.send_err("zły rodzaj pliku")
        rel = urllib.parse.unquote(self.headers.get("X-Relpath") or self.headers.get("X-Filename") or "plik")
        parts = [clean_name(x) for x in rel.replace("\\", "/").split("/") if x not in ("", ".", "..")]
        dest = safe_join(os.path.join(p.dir, kind), *parts)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(self.body())
        self.send_json({"ok": True, "saved": "/".join(parts)})

    def h_delete_file(self, q, pid):
        p = Participant(pid); b = self.jbody()
        kind = b.get("kind")
        if kind not in ("polar", "empatica"):
            return self.send_err("zły rodzaj pliku")
        if b.get("all"):
            d = os.path.join(p.dir, kind)
            shutil.rmtree(d, ignore_errors=True); os.makedirs(d, exist_ok=True)
        else:
            f = safe_join(os.path.join(p.dir, kind), b["name"])
            if os.path.isfile(f): os.remove(f)
        self.send_json(p.detail())

    def h_survey(self, q, pid):
        p = Participant(pid); d = self.jbody()
        tlx = ["mental", "physical", "temporal", "performance", "effort", "frustration"]
        if not all(isinstance(d.get(k), (int, float)) for k in tlx):
            return self.send_err("niepełna ankieta")
        d["id"] = pid
        with open(os.path.join(p.dir, f"ankieta_{pid}.json"), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
        self.send_json({"ok": True, "rtlx": d.get("rtlx")})

    def h_open(self, q, pid):
        p = Participant(pid); what = self.jbody().get("what")
        target = {"folder": p.dir, "app": os.path.join(p.dir, "app.mp4"), "webcam": os.path.join(p.dir, "webcam.mp4"),
                  "plot": os.path.join(p.dir, "wyniki", "przebieg.png"),
                  "frames": os.path.join(p.dir, "wyniki", "klatki")}.get(what)
        if not target:
            return self.send_err("nieznany element")
        self.send_json({"ok": open_local(target)})

    # --- API: zadania ---
    def h_record(self, q, pid):
        if not self.env_guard(): return
        p = Participant(pid); b = self.jbody(); s = settings()
        if p.status()["nagranie"]:
            if not b.get("overwrite"):
                return self.send_err("exists", 409)
            old = os.path.join(p.dir, f"stare_nagranie_{time.strftime('%Y%m%d_%H%M%S')}")
            os.makedirs(old)
            for fn in ("app.mp4", "webcam.mp4", "frames.csv", "events.csv"):
                if os.path.exists(os.path.join(p.dir, fn)):
                    shutil.move(os.path.join(p.dir, fn), os.path.join(old, fn))
        args = [os.path.join(ROOT, "nagrywanie", "record_session.py"), "--id", pid, "--root", SESJE,
                "--laptop-cam", str(s["laptop_cam"]), "--quest-cam", str(s["quest_cam"])]
        if s.get("dshow") and sys.platform.startswith("win"):
            args.append("--dshow")
        self.job_response(JOB.start("Nagrywanie", args, pid))

    def env_guard(self):
        if ENV["ok"] is False:
            self.send_err("Brak bibliotek: " + ", ".join(ENV["missing"]) + ". Uruchom aplikację w środowisku vr "
                          "(conda activate D:\\srodowiska\\vr, potem python app.py).", 412)
            return False
        return True

    def h_analyze(self, q, pid):
        if not self.env_guard(): return
        p = Participant(pid); s = p.status()
        if not (s["nagranie"] or s["polar"] or s["empatica"]):
            return self.send_err("Brak danych: najpierw nagranie i/lub pliki z opasek.")
        self.job_response(JOB.start("Analiza", [os.path.join(ROOT, "analysis", "process_session.py"), p.dir], pid))

    def h_evaluate(self, q):
        if not self.env_guard(): return
        self.job_response(JOB.start("Zestawienie", [os.path.join(ROOT, "evaluation", "evaluate.py"), SESJE]))

    def h_cameras(self, q):
        args = [os.path.join(ROOT, "nagrywanie", "record_session.py"), "--list-cameras"]
        if settings().get("dshow") and sys.platform.startswith("win"):
            args.append("--dshow")
        self.job_response(JOB.start("Test kamer", args))

    def job_response(self, ok):
        if ok:
            self.send_json(JOB.snapshot())
        else:
            self.send_err("Poczekaj, aż skończy się poprzednie zadanie.", 409)

    def h_job(self, q):
        since = int((q.get("since") or ["0"])[0])
        self.send_json(JOB.snapshot(since))

    # --- API: ustawienia, zestawienie ---
    def h_settings_get(self, q):
        self.send_json(settings())

    def h_settings_set(self, q):
        b = self.jbody(); s = settings()
        for k in ("laptop_cam", "quest_cam"):
            if k in b: s[k] = str(b[k]).strip()
        if "dshow" in b: s["dshow"] = bool(b["dshow"])
        with open(SETTINGS, "w") as f:
            json.dump(s, f, indent=2)
        self.send_json(s)

    def h_eval(self, q):
        d = os.path.join(SESJE, "_ewaluacja")
        out = {"ready": os.path.exists(os.path.join(d, "zestawienie.csv")), "rows": [], "corr": [], "peaks": [],
               "plot_version": None}
        import csv as _csv
        def rows(fn):
            p = os.path.join(d, fn)
            if not os.path.exists(p): return []
            with open(p, encoding="utf-8") as f:
                return list(_csv.DictReader(f))
        out["rows"] = rows("zestawienie.csv")
        out["corr"] = [r for r in rows("korelacje.csv") if r.get("ankieta") == "rtlx"]
        out["peaks"] = rows("szczyty.csv")
        pl = os.path.join(d, "wykresy.png")
        out["plot_version"] = int(os.path.getmtime(pl)) if os.path.exists(pl) else None
        self.send_json(out)

    def h_open_eval(self, q):
        self.send_json({"ok": open_local(os.path.join(SESJE, "_ewaluacja"))})


P = r"/api/p/([\w\-]{1,40})"
ROUTES = [
    ("GET", r"/", Handler.h_index),
    ("GET", r"/static/(.+)", Handler.h_static),
    ("GET", r"/ankieta", Handler.h_survey_form),
    ("GET", r"/files/([\w\-]{1,40})/(.+)", Handler.h_session_file),
    ("GET", r"/eval-files/(.+)", Handler.h_eval_file),
    ("GET", r"/api/participants", Handler.h_list),
    ("POST", r"/api/participants", Handler.h_create),
    ("GET", P, Handler.h_detail),
    ("POST", P + r"/fragment", Handler.h_fragment),
    ("POST", P + r"/upload", Handler.h_upload),
    ("POST", P + r"/delete-file", Handler.h_delete_file),
    ("POST", P + r"/survey", Handler.h_survey),
    ("POST", P + r"/open", Handler.h_open),
    ("POST", P + r"/record", Handler.h_record),
    ("POST", P + r"/analyze", Handler.h_analyze),
    ("POST", r"/api/evaluate", Handler.h_evaluate),
    ("POST", r"/api/cameras", Handler.h_cameras),
    ("GET", r"/api/job", Handler.h_job),
    ("GET", r"/api/settings", Handler.h_settings_get),
    ("POST", r"/api/settings", Handler.h_settings_set),
    ("GET", r"/api/eval", Handler.h_eval),
    ("POST", r"/api/open-eval", Handler.h_open_eval),
]


def free_port(start=8765):
    for port in range(start, start + 50):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port)); return port
            except OSError:
                continue
    raise RuntimeError("brak wolnego portu")


def main():
    os.makedirs(SESJE, exist_ok=True)
    mimetypes.add_type("application/javascript", ".js"); mimetypes.add_type("text/css", ".css")
    port = int(os.environ.get("VR_PORT") or free_port())
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    e = check_env()
    print(f"Python do analizy: {PY}")
    if not e["ok"]:
        print("!" * 70)
        print(f"! UWAGA: temu Pythonowi brakuje bibliotek: {', '.join(e['missing'])}")
        print("! Analiza i nagrywanie nie zadziałają. Zamknij (Ctrl+C) i uruchom w środowisku vr:")
        print("!     conda activate D:\\srodowiska\\vr")
        print("!     python app.py")
        print("!" * 70)
    print(f"Monitor obciążenia VR działa: {url}")
    print("Zostaw to okno otwarte. Zamknięcie aplikacji: Ctrl+C.")
    if not os.environ.get("VR_NO_BROWSER"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nZamknięto.")


if __name__ == "__main__":
    main()
