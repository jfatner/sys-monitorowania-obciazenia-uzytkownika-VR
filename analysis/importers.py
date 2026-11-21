"""Wczytywanie surowych eksportów z urządzeń.

Wszystkie funkcje zwracają czasy jako UNIX [s] (zegar bezwzględny), dzięki czemu
można je dopasować do frames.csv z nagrywarki.

Obsługiwane formaty:
  Empatica EmbracePlus: pliki raw_data/v6/*.avro z chmury Empatiki (czytane bez dodatkowych bibliotek)
  Empatica E4 (eksport z E4 Connect, rozpakowany folder albo .zip):
      EDA.csv, BVP.csv, TEMP.csv, HR.csv, ACC.csv  - wiersz 1: czas startu (unix), wiersz 2: fs, dalej wartości
      IBI.csv                                       - wiersz 1: czas startu, dalej: przesunięcie [s], IBI [s]
      tags.csv                                      - czasy wciśnięć przycisku (unix)
  Polar:
      a) plik CSV/TXT z kolumną RR albo PP-interval (Polar Sensor Logger: H10 -> RR, Verity Sense -> PPI)
      b) plik z kolumną HR (tętno co sekundę) - wtedy bez HRV
      c) eksport sesji CSV z Polar Flow (wiersze 'Name,Sport,Date,Start time...' + tabela 'Sample rate,Time,HR')
      d) plik TXT z samymi odstępami RR (jeden na wiersz) - wtedy potrzebny czas startu
         (z eksportu CSV z Polar Flow w tym samym folderze albo 'polar_start' w info.json)
"""
import csv, glob, io, os, re, zipfile
from datetime import datetime
import numpy as np


class DataError(Exception):
    pass


# ======================= Empatica E4 =======================

def _e4_files(folder):
    """Zwraca słownik nazwa_pliku(lower) -> zawartość tekstowa. Obsługuje folder i .zip (także zagnieżdżone)."""
    out = {}
    for p in glob.glob(os.path.join(folder, "**", "*"), recursive=True):
        low = os.path.basename(p).lower()
        if low.endswith(".csv") and os.path.isfile(p) and "digital_biomarkers" not in p.replace("\\", "/"):
            out.setdefault(low, open(p, encoding="utf-8", errors="replace").read())
        elif low.endswith(".zip"):
            with zipfile.ZipFile(p) as z:
                for n in z.namelist():
                    if n.lower().endswith(".csv"):
                        out.setdefault(os.path.basename(n).lower(), z.read(n).decode("utf-8", "replace"))
    return out


def _e4_signal(text, ncols=1):
    rows = [r for r in text.strip().splitlines() if r.strip()]
    if len(rows) < 3:
        return None
    t0 = float(rows[0].split(",")[0]); fs = float(rows[1].split(",")[0])
    v = np.array([[float(x) for x in r.split(",")[:ncols]] for r in rows[2:]])
    t = t0 + np.arange(len(v)) / fs
    return t, (v[:, 0] if ncols == 1 else v), fs


def load_embraceplus(paths):
    """EmbracePlus: pliki raw_data/v6/*.avro (każdy ~30 min). Strumienie sklejane po czasie.
    Zwraca ten sam układ co load_empatica + 'missing' (lista pustych czujników)."""
    from avro_reader import read_avro
    parts = {k: [] for k in ("eda", "bvp", "temp", "acc")}
    tags, peaks, fs = [], [], {}
    for p in sorted(paths):
        for rec in read_avro(p):
            rd = rec["rawData"]
            for key, src in (("eda", "eda"), ("bvp", "bvp"), ("temp", "temperature")):
                d = rd.get(src) or {}
                v = d.get("values") or []
                if v and d.get("samplingFrequency"):
                    f = float(d["samplingFrequency"]); fs[key] = f
                    parts[key].append((d["timestampStart"] / 1e6 + np.arange(len(v)) / f, np.asarray(v, float)))
            a = rd.get("accelerometer") or {}
            if a.get("x") and a.get("samplingFrequency"):
                f = float(a["samplingFrequency"]); fs["acc"] = f
                k = (a.get("imuParams") or {}).get("conversionFactor") or (16.0 / 32768)
                xyz = np.c_[a["x"], a["y"], a["z"]].astype(float) * k            # [g]
                parts["acc"].append((a["timestampStart"] / 1e6 + np.arange(len(xyz)) / f, np.linalg.norm(xyz, axis=1)))
            tags += [t / 1e6 for t in (rd.get("tags") or {}).get("tagsTimeMicros", [])]
            peaks += [t / 1e9 for t in (rd.get("systolicPeaks") or {}).get("peaksTimeNanos", [])]
    res, missing = {"tags": np.array(sorted(tags))}, []
    for k, lst in parts.items():
        if lst:
            t = np.concatenate([x[0] for x in lst]); v = np.concatenate([x[1] for x in lst]); o = np.argsort(t)
            res[k] = (t[o], v[o]); res[k + "_fs"] = fs[k]
        else:
            missing.append({"eda": "EDA", "bvp": "BVP (puls)", "temp": "temperatura", "acc": "akcelerometr"}[k])
    if len(peaks) > 2:                                       # szczyty skurczowe -> odstępy między uderzeniami
        pk = np.array(sorted(peaks)); ibi = np.diff(pk) * 1000
        res["ibi"] = (pk[1:], ibi)
    res["missing"] = missing
    res["source"] = f"EmbracePlus ({len(paths)} plików .avro)"
    if not any(k in res for k in ("eda", "bvp", "acc")):
        raise DataError("Pliki .avro EmbracePlus nie zawierają EDA, BVP ani akcelerometru")
    return res


def load_empatica(folder):
    """Zwraca dict: eda, bvp, temp, hr, acc (moduł wektora w g), ibi (t, ms), tags (tablica unix).
    E4: pliki CSV (folder albo .zip). EmbracePlus: pliki .avro (raw_data)."""
    avros = [p for p in glob.glob(os.path.join(folder, "**", "*.avro"), recursive=True) if os.path.isfile(p)]
    if avros:
        return load_embraceplus(avros)
    files = _e4_files(folder)
    if not files:
        raise DataError(f"Brak plików CSV Empatiki w {folder}")
    res = {}
    for key, fname in (("eda", "eda.csv"), ("bvp", "bvp.csv"), ("temp", "temp.csv"), ("hr_e4", "hr.csv")):
        if fname in files:
            s = _e4_signal(files[fname])
            if s: res[key] = s[:2]; res[key + "_fs"] = s[2]
    if "acc.csv" in files:
        s = _e4_signal(files["acc.csv"], ncols=3)
        if s:
            g = np.linalg.norm(s[1], axis=1) / 64.0            # E4: 1/64 g na jednostkę
            res["acc"] = (s[0], g); res["acc_fs"] = s[2]
    if "ibi.csv" in files:
        rows = [r for r in files["ibi.csv"].strip().splitlines() if r.strip()]
        if len(rows) > 1:
            t0 = float(rows[0].split(",")[0])
            arr = np.array([[float(x) for x in r.split(",")[:2]] for r in rows[1:]])
            res["ibi"] = (t0 + arr[:, 0], arr[:, 1] * 1000.0)
    tags = files.get("tags.csv", "").split()
    res["tags"] = np.array([float(x.split(",")[0]) for x in tags if x.strip()]) if tags else np.array([])
    if not any(k in res for k in ("eda", "bvp")):
        raise DataError("W eksporcie Empatiki brak EDA.csv i BVP.csv")
    return res


# ======================= Polar =======================

def parse_time(s):
    """Czas bezwzględny -> unix [s]. Liczby: s/ms/us/ns (rozpoznawane po wielkości); teksty: ISO, z datą."""
    s = s.strip().strip('"')
    try:
        x = float(s)
        for div in (1e9, 1e6, 1e3, 1.0):                     # ns, us, ms, s
            if x / div > 1e8:
                return x / div
        return None
    except ValueError:
        pass
    s2 = s.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S"):
        try:
            dt = datetime.fromisoformat(s2) if fmt is None else datetime.strptime(s2, fmt)
            return dt.timestamp()                              # bez strefy = czas lokalny komputera
        except ValueError:
            continue
    return None


def _read_table(path):
    text = open(path, encoding="utf-8-sig", errors="replace").read()
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return None, None, text
    delim = max([";", ",", "\t"], key=lambda d: lines[0].count(d))
    rows = list(csv.reader(lines, delimiter=delim)) if lines[0].count(delim) else [[l] for l in lines]
    return rows, delim, text


def _polar_flow_csv(rows):
    """Eksport sesji z Polar Flow: [0]=nagłówek, [1]=wartości (Date, Start time), dalej tabela 'Sample rate'."""
    head = [c.strip().lower() for c in rows[0]]
    vals = rows[1]
    date = vals[head.index("date")].strip(); st = vals[head.index("start time")].strip()
    t0 = None
    for fmt in ("%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
        try: t0 = datetime.strptime(f"{date} {st}", fmt).timestamp(); break
        except ValueError: pass
    if t0 is None:
        raise DataError(f"Nie rozpoznano daty w eksporcie Polar Flow: {date} {st}")
    k = next(i for i, r in enumerate(rows) if r and r[0].strip().lower() == "sample rate")
    th = [c.strip().lower() for c in rows[k]]
    it = th.index("time"); ih = next(i for i, c in enumerate(th) if c.startswith("hr"))
    t, hr = [], []
    for r in rows[k + 1:]:
        if len(r) <= max(it, ih) or not r[ih].strip(): continue
        hh, mm, ss = (r[it].strip().split(":") + ["0", "0"])[:3]
        t.append(t0 + int(hh) * 3600 + int(mm) * 60 + float(ss)); hr.append(float(r[ih]))
    return t0, (np.array(t), np.array(hr))


def _anchor_rr(ts, rr_ms):
    """Polar wysyła RR paczkami z jednym czasem telefonu. Odtwarzamy czasy uderzeń z sumy RR,
    zakotwiczonej tak, by pasowały do czasów telefonu (mediana przesunięcia)."""
    cum = np.cumsum(rr_ms) / 1000.0
    off = np.median(ts - cum)
    return off + cum


FROZEN_HR_S = 30.0   # Verity Sense po utracie sygnału powtarza ostatnią wartość HR - dłuższe stałe odcinki = brak danych


def drop_frozen(t, v, max_s=FROZEN_HR_S):
    """Usuwa odcinki, w których wartość nie zmienia się dłużej niż max_s sekund."""
    if len(v) < 3: return t, v, 0.0
    keep = np.ones(len(v), bool)
    start = 0
    for i in range(1, len(v) + 1):
        if i == len(v) or v[i] != v[start]:
            if t[i - 1] - t[start] > max_s:
                keep[start:i] = False
            start = i
    return t[keep], v[keep], float(1 - keep.mean())


def load_polar(folder, start_hint=None):
    """Zwraca dict z kluczami 'rr' (t, ms) i/lub 'hr' (t, bpm) oraz 'source' (opis)."""
    paths = sorted(p for p in glob.glob(os.path.join(folder, "**", "*"), recursive=True)
                   if os.path.isfile(p) and p.lower().endswith((".csv", ".txt")))
    if not paths:
        raise DataError(f"Brak plików Polara w {folder}")
    res, flow_t0, rr_only = {}, None, None
    for p in paths:
        rows, delim, text = _read_table(p)
        if not rows: continue
        head = [c.strip().lower() for c in rows[0]]
        name = os.path.basename(p)
        # c) Polar Flow
        if "sport" in head and "start time" in head:
            flow_t0, hr = _polar_flow_csv(rows)
            res.setdefault("hr", hr); res.setdefault("source", f"Polar Flow ({name})")
            continue
        # d) same liczby
        if all(re.fullmatch(r"\s*\d+(\.\d+)?\s*", r[0]) for r in rows[:20]) and len(rows[0]) == 1:
            rr_only = (name, np.array([float(r[0]) for r in rows]))
            continue
        # a/b) tabela z nagłówkiem
        irr = next((i for i, c in enumerate(head) if re.search(r"\brr\b|rr[-_ ]?interval|rr \[ms\]|ibi|pp[-_ ]?interval|\bppi\b", c)), None)
        iblk = next((i for i, c in enumerate(head) if "blocker" in c), None)   # PPI z Verity Sense: 1 = zakłócone
        ihr = next((i for i, c in enumerate(head) if re.match(r"hr\b|hr \[|heart ?rate", c)), None)
        itime = next((i for i, c in enumerate(head) if "phone" in c and "time" in c), None)
        if itime is None:
            itime = next((i for i, c in enumerate(head) if "time" in c or "date" in c), None)
        data = rows[1:]
        if irr is not None:
            data = [r for r in data if len(r) > irr and r[irr].strip()]
            rr = np.array([float(r[irr]) for r in data])
            if np.median(rr) < 10: rr = rr * 1000                    # podane w sekundach
            # uderzenia oznaczone jako zakłócone usuwamy dopiero PO wyliczeniu czasów,
            # inaczej suma odstępów (czas kolejnych uderzeń) by się przesunęła
            keep = np.array([iblk is None or len(r) <= iblk or r[iblk].strip() in ("0", "") for r in data])
            if itime is not None:
                ts = np.array([parse_time(r[itime]) for r in data], dtype=float)
                if np.isfinite(ts).all():
                    tb = _anchor_rr(ts, rr)
                    res.setdefault("_rr_parts", []).append((tb[keep], rr[keep]))
                    res.setdefault("_rr_names", []).append(
                        f"{name} (odrzucono zakłócone: {int((~keep).sum())}/{len(keep)})")
                    continue
            rr_only = (name, rr)
        elif ihr is not None and itime is not None:
            ts = np.array([parse_time(r[itime]) for r in data if len(r) > ihr], dtype=float)
            hr = np.array([float(r[ihr]) for r in data if len(r) > ihr])
            ok = np.isfinite(ts) & (hr > 0)
            if ok.sum() > 0:
                tt, hh, frac = drop_frozen(ts[ok], hr[ok])
                if frac > 0.2:
                    res.setdefault("_frozen", []).append(f"{name}: {100 * frac:.0f}% pomiarów HR 'zamrożonych'")
                if len(hh): res.setdefault("_hr_parts", []).append((tt, hh))
                else: res.setdefault("_empty", []).append(name)
            else:
                res.setdefault("_empty", []).append(name)
    # kilka plików (np. kilka nagrań w jednym folderze) -> sklejone po czasie; analiza i tak wybiera okno sesji
    for key, parts in (("rr", res.pop("_rr_parts", [])), ("hr", res.pop("_hr_parts", []))):
        if parts:
            t = np.concatenate([p[0] for p in parts]); v = np.concatenate([p[1] for p in parts])
            o = np.argsort(t, kind="stable"); res[key] = (t[o], v[o])
    if "rr" in res:
        res["source"] = "PPI/RR: " + ", ".join(res.pop("_rr_names"))
    elif "hr" in res and "source" not in res:
        res["source"] = "tylko HR (bez odstępów między uderzeniami - brak HRV)"
    empty = res.pop("_empty", [])
    res["quality_notes"] = res.pop("_frozen", [])
    if "rr" not in res and rr_only is not None:
        t0 = flow_t0 if flow_t0 is not None else start_hint
        if t0 is None:
            raise DataError(f"{rr_only[0]} zawiera same odstępy RR bez czasu. Dodaj eksport CSV z Polar Flow "
                            "do tego folderu albo wpisz \"polar_start\": \"2026-11-20 14:03:22\" do info.json.")
        res["rr"] = (t0 + np.cumsum(rr_only[1]) / 1000.0, rr_only[1])
        res["source"] = f"RR bez czasu ({rr_only[0]}), start {datetime.fromtimestamp(t0)}"
    if "rr" not in res and "hr" not in res:
        if empty:
            raise DataError(f"{', '.join(empty)}: wszystkie wartości HR = 0 - czujnik nie złapał tętna (brak kontaktu ze skórą?)")
        raise DataError(f"Nie rozpoznano formatu plików Polara w {folder}. Wyślij przykładowy plik.")
    res.pop("_rr_names", None)
    return res
