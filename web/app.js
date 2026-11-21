"use strict";
/* Monitor obciążenia VR - interfejs. Rozmawia z lokalnym serwerem (app.py) przez /api/... */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const STEPS = [["nagranie", "Nagranie"], ["polar", "Polar"], ["empatica", "Empatica"], ["fragment", "Fragment"], ["ankieta", "Ankieta"], ["analiza", "Analiza"]];

const I = {
  check: '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>',
  rec: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="m6 4 14 8-14 8z"/></svg>',
  folder: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  upload: '<svg viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M4 20h16"/></svg>',
  chart: '<svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><path d="m7 15 4-5 3 3 5-7"/></svg>',
  form: '<svg viewBox="0 0 24 24"><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/></svg>',
  ext: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  alert: '<svg viewBox="0 0 24 24"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>',
};

const S = { list: [], sel: null, det: null, view: "p", job: null, jobSeq: null, jobNext: 0, log: [], poll: null, logOpen: false, dockClosed: true };

/* ---------- API ---------- */
async function api(path, opts = {}) {
  const o = { method: opts.method || (opts.body !== undefined ? "POST" : "GET"), headers: opts.headers || {} };
  if (opts.body !== undefined) {
    if (opts.raw) o.body = opts.body;
    else { o.body = JSON.stringify(opts.body); o.headers["Content-Type"] = "application/json"; }
  }
  const r = await fetch(path, o);
  let d = null;
  try { d = await r.json(); } catch (e) { /* brak treści */ }
  if (!r.ok) { const err = new Error((d && d.error) || `Błąd ${r.status}`); err.status = r.status; throw err; }
  return d;
}

/* ---------- formatowanie ---------- */
const mmss = (s) => s == null ? "–" : `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(Math.round(s % 60)).padStart(2, "0")}`;
const parseT = (t) => { t = String(t).trim(); let m = t.match(/^(\d{1,3}):(\d{1,2}(?:\.\d+)?)$/); if (m) return +m[1] * 60 + +m[2]; if (/^\d+(\.\d+)?$/.test(t)) return +t; return null; };
const f1 = (x, d = 1) => x == null || isNaN(x) ? "–" : Number(x).toFixed(d).replace(".", ",");
const fsize = (b) => b > 1e6 ? `${f1(b / 1e6)} MB` : b > 1e3 ? `${Math.round(b / 1e3)} kB` : `${b} B`;
const dur = (s) => s == null ? "" : s >= 60 ? `${Math.floor(s / 60)} min ${String(Math.round(s % 60)).padStart(2, "0")} s` : `${Math.round(s)} s`;

function toast(msg, err = false) {
  const t = document.createElement("div"); t.className = "toast" + (err ? " err" : ""); t.textContent = msg;
  const box = $("#toasts"); box.appendChild(t);
  while (box.children.length > 2) box.firstChild.remove();
  setTimeout(() => t.remove(), err ? 6000 : 3000);
}

function envBanner(env) {
  let b = $("#env-banner");
  if (!env || env.ok !== false) { if (b) b.remove(); document.documentElement.style.setProperty("--banner", "0px"); return; }
  if (!b) { b = document.createElement("div"); b.id = "env-banner"; b.className = "env-banner"; document.body.insertBefore(b, $(".layout")); }
  b.innerHTML = `${I.alert}<div><b>Aplikacja działa na złym Pythonie - analiza i nagrywanie nie zadziałają.</b>
    Brakuje: ${esc(env.missing.join(", "))}. Używany: <code>${esc(env.python)}</code><br>
    Zamknij aplikację (Ctrl+C w terminalu) i uruchom ją w środowisku vr: <code>conda activate D:\\srodowiska\\vr</code>, potem <code>python app.py</code>
    - albo od razu <code>D:\\srodowiska\\vr\\python.exe app.py</code>.</div>`;
  document.documentElement.style.setProperty("--banner", b.offsetHeight + "px");
}

/* ---------- lista uczestników ---------- */
async function loadList() {
  const d = await api("/api/participants");
  S.list = d.participants; renderList();
  envBanner(d.env);
  onJob(d.job, true);
}

function renderList() {
  const q = $("#p-search").value.trim().toLowerCase();
  const items = S.list.filter((p) => !q || p.id.toLowerCase().includes(q));
  $("#p-count").textContent = S.list.length;
  $("#p-list").innerHTML = items.map((p) => `
    <li class="pitem ${p.id === S.sel ? "sel" : ""}" data-id="${esc(p.id)}">
      <span class="pid">${esc(p.id)}</span>
      ${p.peak != null ? `<span class="badge load" title="szczyt obciążenia">${Math.round(p.peak)}</span>` : p.warnings ? "" : '<span></span>'}
      <span class="pmeta"><span class="pips">${STEPS.map(([k]) => `<i class="pip ${p.status[k] ? "on" : ""}"></i>`).join("")}</span>
      ${p.done}/6${p.rtlx != null ? ` · RTLX ${Math.round(p.rtlx)}` : ""}${p.warnings ? ` · <span style="color:var(--warn)">${p.warnings} ostrz.</span>` : ""}</span>
    </li>`).join("") || `<li class="hint" style="padding:10px">Brak uczestników.</li>`;
}

async function select(id, keepScroll = false) {
  S.sel = id; renderList();
  const top = $("#p-main").scrollTop;
  try { S.det = await api(`/api/p/${encodeURIComponent(id)}`); } catch (e) { toast(e.message, true); return; }
  renderDetail();
  if (keepScroll) $("#p-main").scrollTop = top; else $("#p-main").scrollTop = 0;
}

async function refreshSel() {
  const d = await api("/api/participants"); S.list = d.participants; renderList();
  if (S.sel) await select(S.sel, true);
}

/* ---------- szczegóły uczestnika ---------- */
function renderDetail() {
  const d = S.det; if (!d) return;
  $("#p-empty").hidden = true; const el = $("#p-detail"); el.hidden = false;
  const st = d.status, frag = d.fragment;
  const busy = S.job && S.job.running;
  const myJob = S.job && S.job.pid === d.id ? S.job : null;

  const pipeline = STEPS.map(([k, n], i) => `${i ? '<i class="psep"></i>' : ""}<span class="pstep ${st[k] ? "on" : ""}"><span class="dot">${st[k] ? I.check : ""}</span>${n}</span>`).join("");
  const sub = [d.duration ? `nagranie ${mmss(d.duration)}` : "brak nagrania", frag ? `fragment ${mmss(frag[0])}–${mmss(frag[1])}` : null].filter(Boolean).join(" · ");

  const fileList = (kind, files) => files.length ? `<ul class="flist">${files.slice(0, 60).map((f) =>
    `<li><span title="${esc(f.name)}">${esc(f.name)}</span><span class="fs">${fsize(f.size)} <button class="x" data-del="${kind}" data-name="${esc(f.name)}" title="Usuń">✕</button></span></li>`).join("")}
    ${files.length > 60 ? `<li><span>… i ${files.length - 60} więcej</span></li>` : ""}</ul>` : "";

  const D = d.duration || 0;
  const base = d.results && d.results.baseline ? d.results.baseline : null;
  const timeline = D ? `<div class="timeline"><div class="tl-bar">
      ${base ? `<i class="tl-base" style="left:${100 * base[0] / D}%;width:${100 * (base[1] - base[0]) / D}%" title="spoczynek"></i>` : ""}
      ${frag ? `<i class="tl-frag" style="left:${100 * frag[0] / D}%;width:${100 * (frag[1] - frag[0]) / D}%"></i>` : ""}</div>
      <span class="tl-lab l0" style="left:0">00:00</span>
      ${frag ? `<span class="tl-lab" style="left:${100 * (frag[0] + frag[1]) / 2 / D}%">${mmss(frag[0])}–${mmss(frag[1])}</span>` : ""}
      <span class="tl-lab l1" style="left:100%">${mmss(D)}</span></div>` : `<p class="hint">Najpierw nagranie - wtedy pojawi się oś czasu.</p>`;

  const sv = d.survey;
  const surveyBody = sv ? `<div class="row" style="gap:22px;align-items:flex-end">
      <div><div class="bigval">${f1(sv.rtlx)}<small>RTLX</small></div></div>
      <div><div class="bigval">${sv.stres_1_5 ?? "–"}<small>/5 stres</small></div></div>
      <div><div class="bigval" style="font-size:20px">${esc(sv.najwieksze_napiecie_czas || "–")}</div><div class="hint" style="margin:0">szczyt wg uczestnika</div></div></div>
      <div class="tlx">${[["mental", "Umysłowe"], ["physical", "Fizyczne"], ["temporal", "Czas"], ["performance", "Wykonanie"], ["effort", "Wysiłek"], ["frustration", "Frustracja"]]
        .map(([k, n]) => `<div><b>${sv[k] ?? "–"}</b>${n}</div>`).join("")}</div>`
    : `<p class="hint" style="margin-top:0">Uczestnik wypełnia suwaki NASA-TLX, prowadzący wpisuje odpowiedzi z wywiadu. Wynik zapisze się tu automatycznie.</p>`;

  const prog = myJob && (myJob.running || S.job.name === "Analiza") && myJob.name === "Analiza" ? progressHTML(myJob) : "";

  el.innerHTML = `<div class="wrap">
    <div class="phead"><div><h1>${esc(d.id)}</h1><div class="sub">${sub}</div></div><div class="pipeline">${pipeline}</div></div>
    <div class="grid">
      <section class="card">
        <div class="card-h"><span class="step-n ${st.nagranie ? "on" : ""}">1</span><h3>Nagranie sesji</h3><span class="state ${st.nagranie ? "ok" : ""}">${st.nagranie ? "nagrano " + mmss(d.duration) : "brak"}</span></div>
        <div class="row">
          <button class="btn rec" data-act="record" ${busy ? "disabled" : ""}>${I.rec} ${st.nagranie ? "Nagraj ponownie" : "Nagraj sesję"}</button>
          <button class="btn" data-open="app" ${d.has_app_video ? "" : "disabled"}>${I.play} Gogle</button>
          <button class="btn" data-open="webcam" ${d.has_webcam_video ? "" : "disabled"}>${I.play} Kamera</button>
        </div>
        ${d.events && d.events.length ? `<ul class="evs">${d.events.map((e) => `<li><span class="num">${mmss(e.t)}</span><span class="ev ev-${e.name}">${({ SYNC: "synchronizacja", TASK_START: "start zadania", EVENT: "znacznik" })[e.name] || esc(e.name)}</span></li>`).join("")}</ul>`
          : st.nagranie ? `<p class="hint">Brak znaczników w nagraniu - spoczynek = pierwsza minuta.</p>` : ""}
        <div class="keys"><span><kbd>R</kbd> start / stop</span><span><kbd>T</kbd> start zadania</span><span><kbd>M</kbd> synchronizacja</span><span><kbd>Q</kbd> koniec</span></div>
      </section>

      <section class="card">
        <div class="card-h"><span class="step-n ${st.polar && st.empatica ? "on" : ""}">2</span><h3>Pliki z opasek</h3><span class="state">przeciągnij pliki albo wybierz</span></div>
        <div class="drops">
          <div class="drop ${st.polar ? "has" : ""}" data-drop="polar">
            <div class="drop-t">Polar ${st.polar ? `<span class="state ok">${d.polar_files.length} pl.</span>` : ""}</div>
            <div class="drop-s">_HR.txt i _PPI.txt</div>
            <div class="row"><button class="btn" data-pick="polar">${I.upload} Wybierz pliki</button>${st.polar ? `<button class="btn ghost" data-delall="polar">Wyczyść</button>` : ""}</div>
            ${fileList("polar", d.polar_files)}
          </div>
          <div class="drop ${st.empatica ? "has" : ""}" data-drop="empatica">
            <div class="drop-t">Empatica ${st.empatica ? `<span class="state ok">${d.empatica_files.length} pl.</span>` : ""}</div>
            <div class="drop-s">folder dnia z raw_data (.avro) lub pliki E4</div>
            <div class="row"><button class="btn" data-pickdir="empatica">${I.folder} Folder</button><button class="btn" data-pick="empatica">${I.upload} Pliki</button>${st.empatica ? `<button class="btn ghost" data-delall="empatica">Wyczyść</button>` : ""}</div>
            ${fileList("empatica", d.empatica_files)}
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-h"><span class="step-n ${st.fragment ? "on" : ""}">3</span><h3>Fragment do analizy</h3><span class="state ${st.fragment ? "ok" : ""}">${st.fragment ? "ustawiony" : "cała część zadania"}</span></div>
        ${timeline}
        <div class="row">
          <span>od</span><input class="tin" id="fr-from" placeholder="mm:ss" value="${frag ? mmss(frag[0]) : ""}">
          <span>do</span><input class="tin" id="fr-to" placeholder="mm:ss" value="${frag ? mmss(frag[1]) : ""}">
          <button class="btn primary" data-act="frag-save">Zapisz</button>
          <button class="btn ghost" data-act="frag-clear" ${frag ? "" : "disabled"}>Cała sesja</button>
        </div>
      </section>

      <section class="card">
        <div class="card-h"><span class="step-n ${st.ankieta ? "on" : ""}">4</span><h3>Ankieta po sesji</h3><span class="state ${st.ankieta ? "ok" : ""}">${st.ankieta ? "wypełniona" : "brak"}</span></div>
        ${surveyBody}
        <div class="row" style="margin-top:12px"><button class="btn" data-act="survey">${I.form} ${st.ankieta ? "Wypełnij ponownie" : "Otwórz formularz"}</button></div>
      </section>

      <section class="card wide">
        <div class="card-h"><span class="step-n ${st.analiza ? "on" : ""}">5</span><h3>Analiza</h3>
          <span class="state">${st.analiza ? `ostatnia: ${d.results && d.results.part === "fragment" ? "fragment" : "zadanie"}` : "obraz z gogli i kamery, sygnały z opasek, wskaźnik obciążenia"}</span></div>
        <div class="row">
          <button class="btn primary big" data-act="analyze" ${busy ? "disabled" : ""}>${I.chart} ${st.analiza ? "Analizuj ponownie" : "Analizuj"}</button>
          <button class="btn ghost" data-open="folder">${I.folder} Folder sesji</button>
        </div>
        <div id="an-prog">${prog}</div>
      </section>
    </div>
    ${resultsHTML(d)}
  </div>`;
}

function progressHTML(j) {
  const pct = j.pct, run = j.running;
  let eta = "";
  if (run && pct && pct >= 3 && pct < 100 && j.elapsed > 3) eta = ` · zostało ok. ${dur(j.elapsed * (100 - pct) / pct)}`;
  const label = run ? (j.label || "uruchamianie…") + eta : j.code === 0 ? `gotowe w ${dur(j.elapsed)}` : "zakończone z błędem - szczegóły w logu";
  return `<div class="prog"><div class="bar ${run && pct == null ? "indet" : ""}"><i style="width:${pct ?? 0}%"></i></div>
    <div class="prog-l"><span>${esc(label)}</span><b>${pct != null ? Math.round(pct) + "%" : ""}</b></div></div>`;
}

function resultsHTML(d) {
  const r = d.results; if (!r) return "";
  const pct = (x) => (x == null ? null : Math.max(0, Math.min(100, x)));
  const rm = r.rmssd_ratio != null ? Math.round((r.rmssd_ratio - 1) * 100) : null;
  const eda = r.eda_ratio != null ? Math.round((r.eda_ratio - 1) * 100) : null;
  const sign = (v, d = 0) => (v > 0 ? "+" : v < 0 ? "−" : "") + f1(Math.abs(v), d);
  const ver = d.plot_version || 0;
  const frames = d.frames || [];
  return `
    <div class="section-t"><h2>Wyniki</h2><span>${r.part === "fragment" && r.fragment ? `fragment ${mmss(r.fragment[0])}–${mmss(r.fragment[1])}` : "część zadania"} · spoczynek ${r.baseline ? mmss(r.baseline[0]) + "–" + mmss(r.baseline[1]) : "–"}</span></div>
    <div class="kpis">
      <div class="kpi main"><div class="k-l">Szczyt obciążenia</div><div class="k-v">${r.peak != null ? Math.round(r.peak) : "–"}<small>/ 100</small></div>
        <div class="gauge"><i style="width:${pct(r.peak) ?? 0}%"></i></div><div class="k-s">w ${mmss(r.peak_time)}</div></div>
      <div class="kpi"><div class="k-l">Średni wskaźnik</div><div class="k-v">${r.load_mean != null ? Math.round(r.load_mean) : "–"}<small>/ 100</small></div>
        <div class="groups"><span>fizjologia <b>${r.idx.fizjologia != null ? Math.round(r.idx.fizjologia) : "–"}</b></span><span>ruch <b>${r.idx.ruch != null ? Math.round(r.idx.ruch) : "–"}</b></span><span>scena <b>${r.idx.scena != null ? Math.round(r.idx.scena) : "–"}</b></span></div></div>
      <div class="kpi"><div class="k-l">Tętno</div><div class="k-v">${f1(r.hr, 0)}<small>bpm</small></div>
        <div class="k-s">${r.hr_delta != null ? `<span class="${r.hr_delta > 0 ? "up" : "down"}">${sign(r.hr_delta, 1)} bpm</span> wzgl. spoczynku` : "brak danych"}</div></div>
      <div class="kpi"><div class="k-l">Zmienność rytmu (RMSSD)</div><div class="k-v">${f1(r.rmssd, 0)}<small>ms</small></div>
        <div class="k-s">${rm != null ? `<span class="${rm < 0 ? "up" : "down"}">${sign(rm)}%</span> wzgl. spoczynku` : "brak danych (PPI/RR)"}</div></div>
      <div class="kpi"><div class="k-l">Przewodnictwo skóry (EDA)</div><div class="k-v">${f1(r.eda, 2)}<small>µS</small></div>
        <div class="k-s">${eda != null ? `<span class="${eda > 0 ? "up" : "down"}">${sign(eda)}%</span> wzgl. spoczynku` : "brak danych z Empatiki"}</div></div>
    </div>
    ${r.warnings && r.warnings.length ? `<details class="warns"><summary>${r.warnings.length} ${r.warnings.length === 1 ? "ostrzeżenie" : "ostrzeżenia"} dotyczące danych</summary><ul>${r.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></details>` : ""}
    <div class="section-t"><h2>Przebieg sesji</h2><span>szare - spoczynek, żółte - fragment, czerwona linia - szczyt wg uczestnika</span>
      <button class="btn ghost" style="margin-left:auto" data-open="plot">${I.ext} Otwórz osobno</button></div>
    <div class="card" style="padding:10px"><img class="plot" src="/files/${encodeURIComponent(d.id)}/wyniki/przebieg.png?v=${ver}" alt="Wykres przebiegu sesji" data-lb="plot"></div>
    ${frames.length ? `<div class="section-t"><h2>Klatki z fragmentu</h2><span>${frames.length} klatek · obiekty, ruch sceny, ruch użytkownika</span>
      <button class="btn ghost" style="margin-left:auto" data-open="frames">${I.folder} Folder</button></div>
      <div class="frames">${frames.map((f, i) => `<div class="frame" data-lb="frame" data-i="${i}"><img loading="lazy" src="/files/${encodeURIComponent(d.id)}/wyniki/klatki/${encodeURIComponent(f)}?v=${ver}" alt=""><span>${esc(f.replace("klatka_", "").replace(".png", "").replace("m", ":").replace("s", ""))}</span></div>`).join("")}</div>` : ""}`;
}

/* ---------- akcje w szczegółach ---------- */
$("#p-detail").addEventListener("click", async (ev) => {
  const b = ev.target.closest("button, [data-lb]"); if (!b || !S.det) return;
  const id = S.det.id, P = `/api/p/${encodeURIComponent(id)}`;
  try {
    if (b.dataset.act === "record") return startRecord(false);
    if (b.dataset.act === "analyze") { await api(`${P}/analyze`, { body: {} }); return jobStarted(); }
    if (b.dataset.act === "frag-save") {
      const a = parseT($("#fr-from").value), e = parseT($("#fr-to").value);
      if (a == null || e == null) return toast("Wpisz czas jako mm:ss, np. 01:30", true);
      S.det = await api(`${P}/fragment`, { body: { from: a, to: e } }); renderDetail(); refreshListOnly();
      return toast(`Fragment ${mmss(a)}–${mmss(e)} zapisany`);
    }
    if (b.dataset.act === "frag-clear") { S.det = await api(`${P}/fragment`, { body: { clear: true } }); renderDetail(); refreshListOnly(); return toast("Analiza całej części zadania"); }
    if (b.dataset.act === "survey") return window.open(`/ankieta?id=${encodeURIComponent(id)}`, "_blank");
    if (b.dataset.open) { const r = await api(`${P}/open`, { body: { what: b.dataset.open } }); if (!r.ok) toast("Tego jeszcze nie ma", true); return; }
    if (b.dataset.pick) return pickFiles(b.dataset.pick, false);
    if (b.dataset.pickdir) return pickFiles(b.dataset.pickdir, true);
    if (b.dataset.del) { S.det = await api(`${P}/delete-file`, { body: { kind: b.dataset.del, name: b.dataset.name } }); renderDetail(); return refreshListOnly(); }
    if (b.dataset.delall) {
      if (!(await confirmBox("Usunąć pliki?", `Wszystkie pliki ${b.dataset.delall === "polar" ? "Polara" : "Empatiki"} tego uczestnika zostaną usunięte z folderu sesji.`, "Usuń", true))) return;
      S.det = await api(`${P}/delete-file`, { body: { kind: b.dataset.delall, all: true } }); renderDetail(); return refreshListOnly();
    }
    if (b.dataset.lb === "plot") return lightbox([[b.src, "Przebieg sesji"]], 0);
    if (b.dataset.lb === "frame") {
      const imgs = $$(".frame", $("#p-detail")).map((f) => [f.querySelector("img").src, f.querySelector("span").textContent]);
      return lightbox(imgs, +b.dataset.i);
    }
  } catch (e) { toast(e.message, true); }
});

async function refreshListOnly() { const d = await api("/api/participants"); S.list = d.participants; renderList(); }

async function startRecord(overwrite) {
  try {
    await api(`/api/p/${encodeURIComponent(S.det.id)}/record`, { body: { overwrite } });
    toast("Otwieram okno nagrywania - R start, T zadanie, Q koniec");
    jobStarted();
  } catch (e) {
    if (e.status === 409 && e.message === "exists") {
      if (await confirmBox("Nagranie już istnieje", "Stare pliki zostaną przeniesione do podfolderu „stare_nagranie_…”, a potem zacznie się nowe nagranie.", "Nagraj ponownie")) startRecord(true);
    } else toast(e.message, true);
  }
}

/* ---------- pliki: wybór i przeciąganie ---------- */
let pickKind = null;
function pickFiles(kind, dir) { pickKind = kind; const inp = dir ? $("#dir-in") : $("#file-in"); inp.value = ""; inp.click(); }
$("#file-in").addEventListener("change", (e) => uploadFiles(pickKind, [...e.target.files].map((f) => [f, f.name])));
$("#dir-in").addEventListener("change", (e) => uploadFiles(pickKind, [...e.target.files].map((f) => [f, f.webkitRelativePath || f.name])));

$("#p-detail").addEventListener("dragover", (e) => { const z = e.target.closest("[data-drop]"); if (!z) return; e.preventDefault(); z.classList.add("over"); });
$("#p-detail").addEventListener("dragleave", (e) => { const z = e.target.closest("[data-drop]"); if (z && !z.contains(e.relatedTarget)) z.classList.remove("over"); });
$("#p-detail").addEventListener("drop", async (e) => {
  const z = e.target.closest("[data-drop]"); if (!z) return; e.preventDefault(); z.classList.remove("over");
  const entries = [...e.dataTransfer.items].map((i) => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  const out = [];
  async function walk(ent, path) {
    if (ent.isFile) { const f = await new Promise((res, rej) => ent.file(res, rej)); out.push([f, path + f.name]); }
    else if (ent.isDirectory) {
      const rd = ent.createReader();
      let batch; do { batch = await new Promise((res, rej) => rd.readEntries(res, rej)); for (const c of batch) await walk(c, path + ent.name + "/"); } while (batch.length);
    }
  }
  if (entries.length) { for (const en of entries) await walk(en, ""); } else out.push(...[...e.dataTransfer.files].map((f) => [f, f.name]));
  uploadFiles(z.dataset.drop, out);
});

async function uploadFiles(kind, files) {
  if (!files.length || !S.det) return;
  files = files.filter(([, p]) => !/(^|\/)digital_biomarkers\//.test(p) && !/(^|\/)\.[^/]+$/.test(p));
  const id = S.det.id; let n = 0, bytes = 0;
  for (const [f, rel] of files) {
    try {
      await api(`/api/p/${encodeURIComponent(id)}/upload?kind=${kind}`, { body: f, raw: true, headers: { "X-Relpath": encodeURIComponent(rel), "Content-Type": "application/octet-stream" } });
      n++; bytes += f.size;
    } catch (e) { toast(`${rel}: ${e.message}`, true); }
  }
  toast(`Dodano ${n} ${n === 1 ? "plik" : "plików"} (${fsize(bytes)})`);
  if (S.sel === id) { await select(id, true); refreshListOnly(); }
}

/* ---------- zadania w tle ---------- */
function jobStarted() { S.dockClosed = false; S.logOpen = false; S.jobNext = 0; S.log = []; pollJob(); }

async function pollJob() {
  clearTimeout(S.poll);
  try { const j = await api(`/api/job?since=${S.jobNext}`); onJob(j); } catch (e) { /* serwer zamknięty? */ }
  if (S.job && S.job.running) S.poll = setTimeout(pollJob, 600);
}

function onJob(j, initial = false) {
  if (!j || !j.name) return;
  if (S.jobSeq !== j.seq) { S.jobSeq = j.seq; S.log = []; S.jobNext = 0; if (!initial) S.dockClosed = false; }
  if (j.lines) { S.log.push(...j.lines); S.jobNext = j.next; }
  const was = S.job && S.job.running;
  S.job = j;
  if (initial && j.running) { S.dockClosed = false; S.jobNext = 0; S.log = []; pollJob(); }
  renderDock();
  if (S.det && j.pid === S.det.id && j.name === "Analiza") { const p = $("#an-prog"); if (p) p.innerHTML = progressHTML(j); }
  $$('[data-act="record"],[data-act="analyze"]').forEach((b) => (b.disabled = !!j.running));
  if (was && !j.running) finished(j);
}

async function finished(j) {
  if (j.code === 0) toast(`${j.name}: gotowe`); else toast(`${j.name}: błąd - zobacz log`, true);
  if (j.code !== 0) S.logOpen = true;
  await refreshListOnly();
  if (S.det && (j.pid === S.det.id)) {
    await select(S.det.id, true);
    if (j.name === "Analiza" && j.code === 0) { const t = $(".section-t"); if (t) t.scrollIntoView({ behavior: "smooth", block: "start" }); }
  }
  if (j.name === "Zestawienie" && S.view === "eval") renderEval();
  renderDock();
}

function reason() {
  const l = S.log.slice().reverse().find((x) => /^(BŁĄD|Błąd)|^\s*!/.test(x));
  return l ? l.replace(/^BŁĄD w [^:]+:\s*/, "").replace(/^\s*!\s*/, "") : `Zakończone z błędem (kod ${S.job.code})`;
}

function renderDock() {
  const j = S.job, el = $("#dock");
  if (!j || !j.name || S.dockClosed) { el.hidden = true; return; }
  el.hidden = false;
  const pct = j.pct, run = j.running;
  let eta = "";
  if (run && pct && pct >= 3 && pct < 100 && j.elapsed > 3) eta = `zostało ok. ${dur(j.elapsed * (100 - pct) / pct)}`;
  const status = run ? `<span>${esc(j.label || "pracuję…")}</span><span>${eta}</span>`
    : j.code === 0 ? `<span>Gotowe</span><span>${dur(j.elapsed)}</span>` : `<span>${esc(reason())}</span>`;
  el.innerHTML = `
    <div class="dock-h">${run ? '<span class="spin"></span>' : ""}<span class="ttl">${esc(j.name)}${j.pid ? `<small>${esc(j.pid)}</small>` : ""}</span>
      <span class="pct">${pct != null ? Math.round(pct) + "%" : ""}</span></div>
    <div class="dock-b"><div class="bar ${run && pct == null ? "indet" : ""} ${!run && j.code !== 0 ? "err" : ""}"><i style="width:${pct ?? (run ? 0 : 100)}%"></i></div>
      <div class="status ${run ? "" : j.code === 0 ? "ok" : "err"}">${status}</div></div>
    <div class="dock-f"><button class="btn ghost" id="dock-log">${S.logOpen ? "Ukryj log" : "Pokaż log"} (${S.log.length})</button>
      ${run ? "" : '<button class="btn ghost" id="dock-close" style="margin-left:auto">Zamknij</button>'}</div>
    ${S.logOpen ? `<div class="log" id="log">${S.log.map((l) => `<div class="${/^\s*!/.test(l) ? "w" : /BŁĄD|Traceback|Error/.test(l) ? "e" : ""}">${esc(l)}</div>`).join("")}</div>` : ""}`;
  const lg = $("#log"); if (lg) lg.scrollTop = lg.scrollHeight;
  $("#dock-log").onclick = () => { S.logOpen = !S.logOpen; renderDock(); };
  const c = $("#dock-close"); if (c) c.onclick = () => { S.dockClosed = true; renderDock(); };
}

/* ---------- zestawienie ---------- */
async function renderEval() {
  const el = $("#eval-main");
  let d; try { d = await api("/api/eval"); } catch (e) { el.innerHTML = `<div class="wrap"><p>${esc(e.message)}</p></div>`; return; }
  const ready = S.list.filter((p) => p.status.analiza && p.status.ankieta).length;
  const head = `<div class="phead"><div><h1>Zestawienie</h1><div class="sub">wyniki obiektywne vs ankieta (Raw NASA-TLX) · gotowych uczestników: ${ready} z ${S.list.length}</div></div>
    <div class="row"><button class="btn" id="ev-open">${I.folder} Folder</button><button class="btn primary" id="ev-run" ${S.job && S.job.running ? "disabled" : ""}>${I.chart} ${d.ready ? "Przelicz" : "Policz zestawienie"}</button></div></div>`;
  if (!d.ready) {
    el.innerHTML = `<div class="wrap">${head}<div class="card"><p style="margin:0">Zestawienie jeszcze nie było liczone. Potrzebni są uczestnicy po analizie i z wypełnioną ankietą (do korelacji co najmniej 5).</p></div></div>`;
  } else {
    const num = (x, dg = 2) => x === "" || x == null ? "–" : f1(+x, dg);
    const rows = d.rows.map((r) => `<tr><td><b>${esc(r.id)}</b></td><td>${num(r.rtlx, 1)}</td><td>${num(r.stres_1_5, 0)}</td><td>${num(r.load_index, 1)}</td><td>${num(r.peak_load_index, 1)}</td><td>${num(r.hr_delta, 1)}</td><td>${num(r.rmssd_ratio, 2)}</td><td>${num(r.eda_tonic_ratio, 2)}</td></tr>`).join("");
    const labels = { load_index: "wskaźnik obciążenia (średni)", peak_load_index: "wskaźnik obciążenia (szczyt)", idx_fizjologia: "składowa fizjologiczna", idx_ruch: "składowa ruchu", idx_scena: "składowa sceny",
      hr_delta: "Δ tętna", rmssd_ratio: "RMSSD (zmiana)", eda_tonic_ratio: "EDA (zmiana)", scr_rate: "reakcje skórne / min", user_motion: "ruch użytkownika (kamera)", acc_motion: "ruch ręki (Empatica)", head_motion: "ruch głowy", n_objects: "liczba obiektów", scene_dynamics: "dynamika sceny" };
    const corr = d.corr.slice().sort((a, b) => Math.abs(+b.spearman_rho) - Math.abs(+a.spearman_rho)).map((c) => {
      const r = +c.spearman_rho, p = +c.spearman_p, w = Math.abs(r) * 50;
      return `<tr><td>${esc(labels[c.miara] || c.miara)}</td><td>${c.n}</td><td style="width:40%"><div class="rbar"><i style="${r >= 0 ? `left:50%;width:${w}%` : `left:${50 - w}%;width:${w}%`};background:${r >= 0 ? "var(--accent)" : "var(--warn)"}"></i><span class="mid"></span></div></td>
        <td><b>${f1(r, 2)}</b></td><td>${p < 0.05 ? `<span class="sig">p=${f1(p, 3)}</span>` : `<span class="nsig">p=${f1(p, 2)}</span>`}</td></tr>`;
    }).join("");
    const pk = d.peaks.length ? (() => { const diffs = d.peaks.map((x) => +x.roznica_s).sort((a, b) => a - b); const med = diffs[Math.floor(diffs.length / 2)]; const ok = diffs.filter((x) => x <= 60).length;
      return `<div class="kpis" style="grid-template-columns:repeat(3,minmax(0,1fr))"><div class="kpi"><div class="k-l">Szczyt wg uczestnika vs wskaźnik</div><div class="k-v">${ok}/${diffs.length}<small>w ±60 s</small></div></div>
        <div class="kpi"><div class="k-l">Mediana różnicy</div><div class="k-v">${Math.round(med)}<small>s</small></div></div><div class="kpi"><div class="k-l">Uczestników</div><div class="k-v">${d.rows.length}</div></div></div>`; })() : "";
    el.innerHTML = `<div class="wrap">${head}
      ${pk}
      <div class="section-t"><h2>Korelacje z RTLX</h2><span>Spearman · zielone p &lt; 0,05 · przy małej liczbie osób traktować ostrożnie</span></div>
      <div class="card" style="padding:6px 8px">${corr ? `<table class="t"><thead><tr><th>Miara</th><th>n</th><th>kierunek i siła</th><th>rho</th><th>istotność</th></tr></thead><tbody>${corr}</tbody></table>` : `<p class="hint" style="padding:8px">Za mało uczestników do korelacji (potrzeba co najmniej 5).</p>`}</div>
      ${d.plot_version ? `<div class="section-t"><h2>Wykresy rozrzutu</h2></div><div class="card" style="padding:10px"><img class="plot" data-lb="plot" src="/eval-files/wykresy.png?v=${d.plot_version}" alt="Wykresy rozrzutu"></div>` : ""}
      <div class="section-t"><h2>Uczestnicy</h2></div>
      <div class="card" style="padding:6px 8px;overflow-x:auto"><table class="t"><thead><tr><th>Kod</th><th>RTLX</th><th>Stres 1-5</th><th>Wskaźnik śr.</th><th>Szczyt</th><th>Δ tętna</th><th>RMSSD</th><th>EDA</th></tr></thead><tbody>${rows}</tbody></table></div>
    </div>`;
  }
  $("#ev-run").onclick = async () => { try { await api("/api/evaluate", { body: {} }); jobStarted(); } catch (e) { toast(e.message, true); } };
  $("#ev-open").onclick = () => api("/api/open-eval", { body: {} }).then((r) => !r.ok && toast("Folder jeszcze nie istnieje", true));
  $$("img[data-lb]", el).forEach((im) => (im.onclick = () => lightbox([[im.src, "Wykresy rozrzutu"]], 0)));
}

/* ---------- modale ---------- */
function modal(html, onReady) {
  $("#modal-box").innerHTML = html; $("#modal").hidden = false;
  if (onReady) onReady($("#modal-box"));
}
function closeModal() { $("#modal").hidden = true; }
$("#modal").addEventListener("mousedown", (e) => { if (e.target.id === "modal") closeModal(); });

function confirmBox(title, text, ok, danger = false) {
  return new Promise((res) => {
    modal(`<h3>${esc(title)}</h3><p>${esc(text)}</p><div class="foot"><button class="btn ghost" id="m-no">Anuluj</button><button class="btn ${danger ? "danger" : "primary"}" id="m-ok">${esc(ok)}</button></div>`, (m) => {
      $("#m-no", m).onclick = () => { closeModal(); res(false); };
      $("#m-ok", m).onclick = () => { closeModal(); res(true); };
    });
  });
}

function newParticipant() {
  const ids = new Set(S.list.map((p) => p.id));
  let n = S.list.length + 1; while (ids.has(`P${String(n).padStart(2, "0")}`)) n++;
  modal(`<h3>Nowy uczestnik</h3><p>Użyj kodu, nie imienia i nazwiska. Listę „kod → osoba” trzymaj osobno.</p>
    <label for="m-id">Kod uczestnika</label><input type="text" id="m-id" value="P${String(n).padStart(2, "0")}" autocomplete="off">
    <div class="err-t" id="m-err"></div><div class="foot"><button class="btn ghost" id="m-no">Anuluj</button><button class="btn primary" id="m-ok">Dodaj</button></div>`, (m) => {
    const inp = $("#m-id", m); inp.focus(); inp.select();
    const go = async () => {
      try { const d = await api("/api/participants", { body: { id: inp.value.trim() } }); closeModal(); await refreshListOnly(); select(d.id); toast(`Dodano ${d.id}`); }
      catch (e) { $("#m-err", m).textContent = e.message; }
    };
    $("#m-ok", m).onclick = go; inp.onkeydown = (e) => { if (e.key === "Enter") go(); if (e.key === "Escape") closeModal(); };
    $("#m-no", m).onclick = closeModal;
  });
}

async function settingsBox() {
  const s = await api("/api/settings");
  modal(`<h3>Ustawienia kamer</h3><p>Numery kamer w systemie. Kamera gogli to wirtualna kamera OBS. Wpisz „brak”, żeby nagrywać bez gogli (test).</p>
    <label for="s-lap">Kamera laptopa</label><input type="text" id="s-lap" value="${esc(s.laptop_cam)}">
    <label for="s-q">Kamera gogli (OBS)</label><input type="text" id="s-q" value="${esc(s.quest_cam)}">
    <label class="check"><input type="checkbox" id="s-ds" ${s.dshow ? "checked" : ""}> DirectShow (Windows, szybsze otwieranie kamer)</label>
    <div class="foot"><button class="btn" id="s-test" style="margin-right:auto">Sprawdź kamery</button><button class="btn ghost" id="m-no">Anuluj</button><button class="btn primary" id="m-ok">Zapisz</button></div>`, (m) => {
    const save = () => api("/api/settings", { body: { laptop_cam: $("#s-lap", m).value, quest_cam: $("#s-q", m).value, dshow: $("#s-ds", m).checked } });
    $("#m-ok", m).onclick = async () => { await save(); closeModal(); toast("Zapisano ustawienia"); };
    $("#m-no", m).onclick = closeModal;
    $("#s-test", m).onclick = async () => { await save(); closeModal(); try { await api("/api/cameras", { body: {} }); jobStarted(); S.logOpen = true; } catch (e) { toast(e.message, true); } };
  });
}

/* ---------- lightbox ---------- */
let LB = { list: [], i: 0 };
function lightbox(list, i) { LB = { list, i }; showLB(); $("#lightbox").hidden = false; }
function showLB() { const [src, cap] = LB.list[LB.i]; $("#lb-img").src = src; $("#lb-cap").textContent = LB.list.length > 1 ? `${cap}  ·  ${LB.i + 1} / ${LB.list.length}` : cap;
  $("#lb-prev").hidden = $("#lb-next").hidden = LB.list.length < 2; }
$("#lightbox").addEventListener("click", (e) => {
  if (e.target.id === "lb-prev") { LB.i = (LB.i - 1 + LB.list.length) % LB.list.length; showLB(); }
  else if (e.target.id === "lb-next") { LB.i = (LB.i + 1) % LB.list.length; showLB(); }
  else $("#lightbox").hidden = true;
});
document.addEventListener("keydown", (e) => {
  if (!$("#lightbox").hidden) {
    if (e.key === "Escape") $("#lightbox").hidden = true;
    if (e.key === "ArrowRight") { LB.i = (LB.i + 1) % LB.list.length; showLB(); }
    if (e.key === "ArrowLeft") { LB.i = (LB.i - 1 + LB.list.length) % LB.list.length; showLB(); }
  } else if (e.key === "Escape" && !$("#modal").hidden) closeModal();
});

/* ---------- start ---------- */
$("#p-list").addEventListener("click", (e) => { const li = e.target.closest(".pitem"); if (li) select(li.dataset.id); });
$("#p-search").addEventListener("input", renderList);
$("#btn-new").onclick = newParticipant;
$("#btn-settings").onclick = settingsBox;
$$(".tab").forEach((t) => (t.onclick = () => {
  $$(".tab").forEach((x) => x.classList.toggle("active", x === t)); S.view = t.dataset.view;
  $("#view-p").hidden = S.view !== "p"; $("#view-eval").hidden = S.view !== "eval";
  if (S.view === "eval") renderEval();
}));
window.addEventListener("focus", () => { if (S.det && !(S.job && S.job.running)) refreshSel(); });   // np. po wypełnieniu ankiety w drugiej karcie
loadList().then(() => { if (S.list.length) select(S.list[0].id); }).catch((e) => toast("Brak połączenia z aplikacją: " + e.message, true));
