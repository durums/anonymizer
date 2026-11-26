#!/usr/bin/env python3
"""Web-UI für den Anonymisierer. Verarbeitet alles im RAM — keine Kundendaten auf Festplatte."""

import io
import json
import os
import signal
import sys
import threading
import time
import zipfile
from pathlib import Path

from flask import Flask, request, send_file, jsonify

from anony import anonymisiere_dateien

VERSION = "1.0.0"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

# PyInstaller: gebundelte Dateien liegen in sys._MEIPASS, eigene Konfig neben der .exe
_BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
_EXE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
BLACKLIST_DATEI = _EXE_DIR / "blacklist.txt"
_BUNDLE_BLACKLIST = _BUNDLE_DIR / "blacklist.txt"
ERLAUBTE_ENDUNGEN = {".eml", ".mbox", ".txt", ".csv", ".xlsx"}

_letzter_heartbeat = time.time()
_heartbeat_aktiv = False

KATEGORIEN = [
    {"id": "PERSON", "label": "Namen"},
    {"id": "EMAIL", "label": "E-Mail"},
    {"id": "TEL", "label": "Telefon"},
    {"id": "IBAN", "label": "IBAN"},
    {"id": "ADRESSE", "label": "Adressen"},
    {"id": "PLZ_ORT", "label": "PLZ/Orte"},
    {"id": "URL", "label": "URLs"},
    {"id": "IP", "label": "IP-Adressen"},
    {"id": "FIRMA", "label": "Firmennamen"},
    {"id": "POSITION", "label": "Positionen"},
    {"id": "HANDELSREGISTER", "label": "Handelsregister"},
    {"id": "STEUER_ID", "label": "Steuer-IDs"},
    {"id": "UST_ID", "label": "USt-IDs"},
    {"id": "NUMMER", "label": "Kunden-Nr."},
    {"id": "DOMAIN", "label": "Domains"},
]


def _lade_blacklist():
    # Zuerst neben der .exe schauen, dann im Bundle (PyInstaller)
    for pfad in (BLACKLIST_DATEI, _BUNDLE_BLACKLIST):
        if pfad.exists():
            return [z.strip() for z in pfad.read_text(encoding="utf-8").splitlines()
                    if z.strip() and not z.lstrip().startswith("#")]
    return []


@app.after_request
def sicherheits_header(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


@app.errorhandler(413)
def zu_gross(e):
    return jsonify({"fehler": "Datei zu groß. Maximale Größe: 50 MB."}), 413


@app.route("/")
def startseite():
    return SEITE_HTML


@app.route("/heartbeat", methods=["POST"])
def heartbeat():
    global _letzter_heartbeat
    _letzter_heartbeat = time.time()
    return "", 204


@app.route("/api/blacklist")
def blacklist_begriffe():
    return jsonify({"begriffe": _lade_blacklist()})


@app.route("/anonymize", methods=["POST"])
def anonymisieren():
    dateien_roh = request.files.getlist("files")
    if not dateien_roh:
        return jsonify({"fehler": "Keine Dateien hochgeladen."}), 400

    blacklist_raw = request.form.get("blacklist", "")
    begriffe = _lade_blacklist()
    begriffe += [z.strip() for z in blacklist_raw.splitlines() if z.strip()]

    dateien = []
    for f in dateien_roh:
        name = f.filename or "unbenannt"
        endung = Path(name).suffix.lower()
        if endung not in ERLAUBTE_ENDUNGEN:
            return jsonify({"fehler": f"Format '{endung}' nicht unterstützt. "
                                       f"Erlaubt: {', '.join(sorted(ERLAUBTE_ENDUNGEN))}"}), 400
        daten = f.read()
        dateien.append((name, daten))

    try:
        ergebnisse, statistik = anonymisiere_dateien(dateien, kein_ner=True, begriffe=begriffe)
    except Exception as e:
        return jsonify({"fehler": f"Fehler bei der Anonymisierung: {type(e).__name__}: {e}"}), 500

    if len(ergebnisse) == 1:
        name, daten = ergebnisse[0]
        buf = io.BytesIO(daten)
        resp = send_file(buf, download_name="dokument_anonym" + Path(name).suffix, as_attachment=True)
    else:
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, (name, daten) in enumerate(ergebnisse, 1):
                zf.writestr(f"dokument_{i}" + Path(name).suffix, daten)
        zip_buf.seek(0)
        resp = send_file(zip_buf, download_name="anonymisiert.zip", as_attachment=True)

    resp.headers["X-Statistik"] = json.dumps(statistik, ensure_ascii=False)
    return resp


SEITE_HTML = r"""<!DOCTYPE html>
<html lang="de" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="Automatische Anonymisierung sensibler Dokumente: Namen, E-Mails, Telefonnummern, IBANs und mehr.">
<title>Dokument-Anonymisierer</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Crect rx='20' width='100' height='100' fill='%232e7d32'/%3E%3Cpath d='M50 20 L75 40 V70 Q75 80 50 85 Q25 80 25 70 V40Z' fill='white' opacity='.9'/%3E%3Ccircle cx='50' cy='52' r='8' fill='%232e7d32'/%3E%3Crect x='47' y='55' width='6' height='14' rx='3' fill='%232e7d32'/%3E%3C/svg%3E">
<style>
:root {
  --bg: #f4f6f8;
  --card: #ffffff;
  --card-alt: #f8faf8;
  --primary: #2e7d32;
  --primary-hover: #1b5e20;
  --primary-light: #e8f5e9;
  --primary-subtle: rgba(46,125,50,0.08);
  --text: #1a2332;
  --text-soft: #4a5568;
  --muted: #64748b;
  --border: #d1d9e0;
  --border-light: #e2e8f0;
  --success-bg: #ecfdf5;
  --success-border: #86efac;
  --success-text: #166534;
  --error-bg: #fef2f2;
  --error-border: #fca5a5;
  --error-text: #991b1b;
  --info-bg: #eff6ff;
  --info-border: #93c5fd;
  --info-text: #1e40af;
  --warn-bg: #fffbeb;
  --warn-border: #fcd34d;
  --warn-text: #92400e;
  --drop-bg: #f0fdf4;
  --drop-border: #86efac;
  --radius: 12px;
  --radius-sm: 8px;
  --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.08);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #0f1117;
    --card: #1a1d2e;
    --card-alt: #1e2235;
    --primary: #4ade80;
    --primary-hover: #22c55e;
    --primary-light: rgba(74,222,128,0.1);
    --primary-subtle: rgba(74,222,128,0.06);
    --text: #e2e8f0;
    --text-soft: #94a3b8;
    --muted: #64748b;
    --border: #2d3348;
    --border-light: #252a3a;
    --success-bg: rgba(74,222,128,0.1);
    --success-border: #22c55e;
    --success-text: #4ade80;
    --error-bg: rgba(239,68,68,0.1);
    --error-border: #ef4444;
    --error-text: #fca5a5;
    --info-bg: rgba(59,130,246,0.1);
    --info-border: #3b82f6;
    --info-text: #93c5fd;
    --warn-bg: rgba(245,158,11,0.1);
    --warn-border: #f59e0b;
    --warn-text: #fcd34d;
    --drop-bg: rgba(74,222,128,0.06);
    --drop-border: #22c55e;
    --shadow: 0 1px 3px rgba(0,0,0,0.3);
    --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
  }
}
:root[data-theme="dark"] {
  --bg: #0f1117;
  --card: #1a1d2e;
  --card-alt: #1e2235;
  --primary: #4ade80;
  --primary-hover: #22c55e;
  --primary-light: rgba(74,222,128,0.1);
  --primary-subtle: rgba(74,222,128,0.06);
  --text: #e2e8f0;
  --text-soft: #94a3b8;
  --muted: #64748b;
  --border: #2d3348;
  --border-light: #252a3a;
  --success-bg: rgba(74,222,128,0.1);
  --success-border: #22c55e;
  --success-text: #4ade80;
  --error-bg: rgba(239,68,68,0.1);
  --error-border: #ef4444;
  --error-text: #fca5a5;
  --info-bg: rgba(59,130,246,0.1);
  --info-border: #3b82f6;
  --info-text: #93c5fd;
  --warn-bg: rgba(245,158,11,0.1);
  --warn-border: #f59e0b;
  --warn-text: #fcd34d;
  --drop-bg: rgba(74,222,128,0.06);
  --drop-border: #22c55e;
  --shadow: 0 1px 3px rgba(0,0,0,0.3);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.4);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  font-size: 110%;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 2rem 1rem 0;
  line-height: 1.6;
}
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0;
}
.container { max-width: 1100px; width: 100%; flex: 1; }

/* --- Header --- */
header { margin-bottom: 1.5rem; display: flex; justify-content: space-between; align-items: flex-start; }
.header-left { flex: 1; }
h1 { font-size: 1.5rem; font-weight: 800; color: var(--text); letter-spacing: -0.02em; }
.tagline { font-size: 0.92rem; color: var(--text-soft); margin-top: 0.15rem; }
.theme-toggle {
  background: none; border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 0.4rem; cursor: pointer; color: var(--muted); display: flex;
  align-items: center; justify-content: center; transition: all 0.2s; flex-shrink: 0;
  margin-top: 0.2rem;
}
.theme-toggle:hover { color: var(--text); border-color: var(--text-soft); }
.theme-toggle svg { width: 18px; height: 18px; }

/* --- Category badges --- */
.kategorien { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.6rem; }
.kat-badge {
  font-size: 0.72rem; font-weight: 600; padding: 0.15rem 0.55rem;
  border-radius: 20px; background: var(--primary-subtle); color: var(--primary);
  border: 1px solid transparent; letter-spacing: 0.01em;
}

/* --- Info box --- */
.info-box { margin-top: 0.8rem; }
.info-box summary {
  font-size: 0.85rem; color: var(--muted); cursor: pointer; font-weight: 500;
  list-style: none; display: flex; align-items: center; gap: 0.4rem;
}
.info-box summary::before { content: '\25B6'; font-size: 0.6rem; transition: transform 0.2s; }
.info-box[open] summary::before { transform: rotate(90deg); }
.info-box summary::-webkit-details-marker { display: none; }
.info-box .info-content {
  margin-top: 0.5rem; font-size: 0.85rem; color: var(--text-soft); line-height: 1.7;
  padding: 0.75rem 1rem; background: var(--card); border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
}

/* --- Two-column layout --- */
.columns { display: grid; grid-template-columns: 1fr 360px; gap: 1.25rem; align-items: start; }

/* --- Panels --- */
.panel {
  background: var(--card); border: 1px solid var(--border-light);
  border-radius: var(--radius); padding: 1.25rem; box-shadow: var(--shadow);
}
.panel-title { font-size: 0.95rem; font-weight: 700; margin-bottom: 0.2rem; }
.panel-subtitle { font-size: 0.8rem; color: var(--muted); margin-bottom: 0.75rem; line-height: 1.5; }
.panel-badge {
  font-size: 0.7rem; font-weight: 500; color: var(--muted);
  margin-left: 0.4rem; vertical-align: middle;
}

/* --- Dropzone --- */
.dropzone {
  border: 2px dashed var(--border); border-radius: var(--radius);
  padding: 2.5rem 1.5rem; text-align: center; cursor: pointer;
  transition: all 0.2s; background: var(--card-alt);
  min-height: 200px; display: flex; flex-direction: column;
  align-items: center; justify-content: center;
}
.dropzone:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.dropzone.aktiv { border-color: var(--drop-border); background: var(--drop-bg); }
.dropzone:hover { border-color: var(--primary); background: var(--primary-light); }
.dropzone.gesperrt { pointer-events: none; opacity: 0.5; }
.dropzone-icon { font-size: 2.5rem; margin-bottom: 0.5rem; opacity: 0.7; }
.dropzone-main { font-size: 1.05rem; font-weight: 600; color: var(--text); margin-bottom: 0.3rem; }
.dropzone-sub { color: var(--muted); font-size: 0.88rem; }
.link-btn {
  background: none; border: none; color: var(--primary); font-weight: 600;
  cursor: pointer; text-decoration: underline; text-underline-offset: 2px;
  font-size: inherit; font-family: inherit; padding: 0;
}
.link-btn:hover { color: var(--primary-hover); }
.link-btn:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; border-radius: 2px; }
.dropzone-formats { margin-top: 0.6rem; font-size: 0.78rem; color: var(--muted); }
.datei-input { display: none; }

/* --- File list --- */
.dateiliste {
  margin-top: 0.75rem; display: flex; flex-direction: column; gap: 0.3rem;
  max-height: 300px; overflow-y: auto;
}
.datei-eintrag {
  display: flex; align-items: center; gap: 0.6rem;
  padding: 0.5rem 0.75rem; background: var(--card-alt);
  border-radius: 6px; font-size: 0.88rem; transition: background 0.15s;
}
.datei-eintrag:hover { background: var(--border-light); }
.datei-icon { font-size: 1rem; flex-shrink: 0; }
.datei-name {
  font-weight: 600; flex: 1; min-width: 0;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.datei-size { color: var(--muted); font-size: 0.78rem; white-space: nowrap; }
.datei-entfernen {
  background: none; border: none; color: var(--error-text); cursor: pointer;
  font-size: 1.1rem; padding: 0 0.2rem; line-height: 1; opacity: 0.6;
  transition: opacity 0.15s;
}
.datei-entfernen:hover, .datei-entfernen:focus-visible { opacity: 1; }

/* --- Blacklist --- */
.server-blacklist { margin-bottom: 0.6rem; }
.server-blacklist-label { font-size: 0.72rem; color: var(--muted); margin-bottom: 0.3rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.server-tags { display: flex; flex-wrap: wrap; gap: 0.3rem; }
.server-tag {
  font-size: 0.75rem; font-weight: 500; padding: 0.15rem 0.5rem;
  border-radius: 20px; background: var(--border-light); color: var(--text-soft);
}
.blacklist-area {
  width: 100%; min-height: 120px; max-height: 260px;
  border: 1.5px solid var(--border); border-radius: var(--radius-sm);
  padding: 0.65rem 0.85rem; font-family: inherit; font-size: 0.9rem;
  color: var(--text); resize: vertical; transition: border-color 0.2s;
  line-height: 1.6; background: var(--card-alt);
}
.blacklist-area:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-subtle); }
.blacklist-area::placeholder { color: var(--muted); font-size: 0.85rem; }
.blacklist-area:disabled { opacity: 0.5; cursor: not-allowed; }
.blacklist-tags { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-top: 0.5rem; min-height: 0; }
.blacklist-tag {
  font-size: 0.75rem; font-weight: 600; padding: 0.15rem 0.5rem;
  border-radius: 20px; background: var(--primary-subtle); color: var(--primary);
  border: 1px solid var(--primary-light);
}

/* --- Bottom bar --- */
.bottom-bar { margin-top: 1.25rem; }
.btn-go {
  display: flex; align-items: center; justify-content: center; gap: 0.5rem;
  width: 100%; padding: 0.95rem 2rem; border: none; border-radius: var(--radius-sm);
  font-size: 1.05rem; font-weight: 700; cursor: pointer; transition: all 0.2s;
  background: var(--primary); color: white;
  box-shadow: 0 2px 8px rgba(46,125,50,0.25);
}
.btn-go:hover:not(:disabled) {
  background: var(--primary-hover);
  box-shadow: 0 4px 12px rgba(46,125,50,0.35); transform: translateY(-1px);
}
.btn-go:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px; }
.btn-go:active:not(:disabled) { transform: translateY(0); }
.btn-go:disabled { opacity: 0.35; cursor: not-allowed; box-shadow: none; transform: none; }

/* --- Progress --- */
.fortschritt {
  display: none; margin-top: 1rem; padding: 1rem;
  background: var(--info-bg); border: 1px solid var(--info-border);
  border-radius: var(--radius-sm); color: var(--info-text);
}
.fortschritt.sichtbar { display: block; }
.fortschritt-text { font-size: 0.95rem; font-weight: 600; text-align: center; margin-bottom: 0.6rem; }
.progress-bar {
  height: 4px; background: var(--border-light); border-radius: 2px;
  overflow: hidden;
}
.progress-bar-inner {
  height: 100%; width: 30%; background: var(--info-text); border-radius: 2px;
  animation: indeterminate 1.5s ease-in-out infinite;
}
@keyframes indeterminate {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(400%); }
}

/* --- Result --- */
.ergebnis {
  display: none; margin-top: 1rem; padding: 1rem 1.25rem;
  border-radius: var(--radius-sm); font-size: 0.92rem; line-height: 1.6;
}
.ergebnis.erfolg { display: block; background: var(--success-bg); border: 1px solid var(--success-border); color: var(--success-text); }
.ergebnis.fehler { display: block; background: var(--error-bg); border: 1px solid var(--error-border); color: var(--error-text); }
.ergebnis.info { display: block; background: var(--info-bg); border: 1px solid var(--info-border); color: var(--info-text); }
.ergebnis-titel { font-weight: 700; font-size: 1rem; margin-bottom: 0.5rem; }
.stat-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 0.4rem; margin-top: 0.6rem;
}
.stat-card {
  padding: 0.5rem 0.6rem; border-radius: 6px;
  background: rgba(255,255,255,0.5); text-align: center;
}
:root[data-theme="dark"] .stat-card,
:root:not([data-theme="light"]) .stat-card { background: rgba(255,255,255,0.05); }
@media (prefers-color-scheme: light) { :root:not([data-theme="dark"]) .stat-card { background: rgba(255,255,255,0.5); } }
.stat-number { font-size: 1.3rem; font-weight: 800; line-height: 1.2; }
.stat-label { font-size: 0.7rem; color: inherit; opacity: 0.7; }
.stat-detail { font-size: 0.65rem; opacity: 0.5; }

/* --- Toast --- */
.toast-container { position: fixed; bottom: 1.5rem; right: 1.5rem; z-index: 1000; display: flex; flex-direction: column; gap: 0.5rem; }
.toast {
  padding: 0.75rem 1rem; border-radius: var(--radius-sm); font-size: 0.88rem;
  font-weight: 500; box-shadow: var(--shadow-md); animation: toast-in 0.3s ease;
  max-width: 400px;
}
.toast-fehler { background: var(--error-bg); border: 1px solid var(--error-border); color: var(--error-text); }
.toast-info { background: var(--info-bg); border: 1px solid var(--info-border); color: var(--info-text); }
@keyframes toast-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }

/* --- Footer --- */
footer {
  margin-top: 2rem; padding: 1.25rem 0; text-align: center;
  font-size: 0.78rem; color: var(--muted); border-top: 1px solid var(--border-light);
  width: 100%; max-width: 1100px;
}
footer .privacy { margin-bottom: 0.2rem; }

/* --- Responsive --- */
@media (max-width: 800px) {
  body { padding: 1rem 1rem 0; }
  .columns { grid-template-columns: 1fr; }
  h1 { font-size: 1.25rem; }
  .btn-go { font-size: 1rem; padding: 0.9rem 1.5rem; }
  .dropzone { padding: 2rem 1rem; min-height: 160px; }
  .stat-grid { grid-template-columns: repeat(auto-fill, minmax(90px, 1fr)); }
  .toast-container { left: 1rem; right: 1rem; }
  .toast { max-width: 100%; }
}
</style>
</head>
<body>
<div class="container">

  <header>
    <div class="header-left">
      <h1>Dokument-Anonymisierer</h1>
      <p class="tagline">Personenbezogene Daten automatisch durch Platzhalter ersetzen</p>
      <div class="kategorien" id="kategorien"></div>
      <details class="info-box">
        <summary>So funktioniert es</summary>
        <div class="info-content">
          Laden Sie Ihre Dokumente hoch &mdash; der Anonymisierer erkennt automatisch
          personenbezogene Daten und ersetzt sie durch Platzhalter wie <code>[PERSON_1]</code>,
          <code>[EMAIL_1]</code> usw. Gleiche Werte erhalten den gleichen Platzhalter,
          damit Zuordnungen im Text erhalten bleiben. Die gesamte Verarbeitung findet
          ausschließlich im Arbeitsspeicher statt &mdash; es werden keine Daten gespeichert.
        </div>
      </details>
    </div>
    <button class="theme-toggle" id="themeToggle" type="button" aria-label="Farbschema wechseln">
      <svg id="iconSun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
      </svg>
      <svg id="iconMoon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:none">
        <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/>
      </svg>
    </button>
  </header>

  <main>
    <div class="columns">
      <div class="panel" id="panelLeft">
        <div class="dropzone" id="dropzone" role="button" tabindex="0" aria-label="Dateien zum Anonymisieren hochladen">
          <div class="dropzone-icon">&#128194;</div>
          <div class="dropzone-main">Dateien hier hineinziehen</div>
          <div class="dropzone-sub">oder <button type="button" class="link-btn" id="durchsuchen">Dateien auswählen</button></div>
          <div class="dropzone-formats">.eml, .mbox, .txt, .csv, .xlsx &mdash; max. 50 MB</div>
          <input type="file" class="datei-input" id="dateiInput" multiple accept=".eml,.mbox,.txt,.csv,.xlsx" aria-hidden="true">
        </div>
        <div class="dateiliste" id="dateiliste" role="list"></div>
      </div>

      <div class="panel" id="panelRight">
        <div class="panel-title">Blacklist <span class="panel-badge">Optional</span></div>
        <div class="panel-subtitle">Begriffe, die zusätzlich anonymisiert werden sollen &mdash; ein Begriff pro Zeile.</div>
        <div class="server-blacklist" id="serverBlacklist" style="display:none">
          <div class="server-blacklist-label">Server-Blacklist</div>
          <div class="server-tags" id="serverTags"></div>
        </div>
        <label for="blacklist" class="sr-only">Blacklist-Begriffe</label>
        <textarea class="blacklist-area" id="blacklist"
                  placeholder="Mustermann GmbH&#10;Projekt Sonnenschein&#10;Vertrag 2024-ABC"></textarea>
        <div class="blacklist-tags" id="blacklistTags"></div>
      </div>
    </div>

    <div class="bottom-bar">
      <button class="btn-go" id="startBtn" disabled type="button">
        Jetzt anonymisieren &amp; herunterladen
      </button>
      <div class="fortschritt" id="fortschritt" role="status" aria-live="polite">
        <div class="fortschritt-text">Dateien werden anonymisiert &hellip;</div>
        <div class="progress-bar"><div class="progress-bar-inner"></div></div>
      </div>
      <div class="ergebnis" id="ergebnis" role="alert" aria-live="assertive"></div>
    </div>
  </main>

</div>

<footer>
  <div class="privacy">Verarbeitung ausschließlich im Arbeitsspeicher &mdash; keine Daten werden gespeichert.</div>
  <div>Dokument-Anonymisierer v""" + VERSION + r"""</div>
</footer>

<div class="toast-container" id="toasts"></div>

<script>
const dropzone = document.getElementById('dropzone');
const dateiInput = document.getElementById('dateiInput');
const dateiliste = document.getElementById('dateiliste');
const startBtn = document.getElementById('startBtn');
const fortschritt = document.getElementById('fortschritt');
const ergebnis = document.getElementById('ergebnis');
const blacklistArea = document.getElementById('blacklist');
const blacklistTags = document.getElementById('blacklistTags');
const toasts = document.getElementById('toasts');

let dateien = [];

const FILE_ICONS = { '.eml':'✉️', '.mbox':'✉️', '.txt':'📄', '.csv':'📊', '.xlsx':'📊' };
const KATEGORIEN = [
  'Namen','E-Mail','Telefon','IBAN','Adressen','PLZ/Orte','URLs',
  'IP-Adressen','Firmennamen','Positionen','Handelsregister','Steuer-IDs','USt-IDs','Kunden-Nr.','Domains'
];

// --- Heartbeat: Server beendet sich wenn Browser-Tab geschlossen ---
setInterval(() => { fetch('/heartbeat', {method:'POST'}).catch(() => {}); }, 15000);

// --- Init ---
(function init() {
  // Category badges
  const kat = document.getElementById('kategorien');
  KATEGORIEN.forEach(k => {
    const s = document.createElement('span');
    s.className = 'kat-badge';
    s.textContent = k;
    kat.appendChild(s);
  });
  // Server blacklist
  fetch('/api/blacklist').then(r => r.json()).then(d => {
    if (d.begriffe && d.begriffe.length) {
      document.getElementById('serverBlacklist').style.display = '';
      const tags = document.getElementById('serverTags');
      d.begriffe.forEach(b => {
        const s = document.createElement('span');
        s.className = 'server-tag';
        s.textContent = b;
        tags.appendChild(s);
      });
    }
  }).catch(() => {});
  // Theme
  initTheme();
})();

// --- Theme ---
function initTheme() {
  const toggle = document.getElementById('themeToggle');
  const sun = document.getElementById('iconSun');
  const moon = document.getElementById('iconMoon');
  let theme;
  try { theme = localStorage.getItem('theme'); } catch(e) {}
  if (theme) document.documentElement.setAttribute('data-theme', theme);
  updateIcons();
  toggle.addEventListener('click', () => {
    const current = document.documentElement.getAttribute('data-theme');
    const isDark = current === 'dark' || (!current && matchMedia('(prefers-color-scheme: dark)').matches);
    const next = isDark ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch(e) {}
    updateIcons();
  });
  function updateIcons() {
    const t = document.documentElement.getAttribute('data-theme');
    const dark = t === 'dark' || (!t && matchMedia('(prefers-color-scheme: dark)').matches);
    sun.style.display = dark ? 'none' : '';
    moon.style.display = dark ? '' : 'none';
  }
}

// --- Helpers ---
function formatSize(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
  return (b / 1048576).toFixed(1) + ' MB';
}
function getExt(n) { const i = n.lastIndexOf('.'); return i >= 0 ? n.substring(i).toLowerCase() : ''; }
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function toast(text, typ) {
  const el = document.createElement('div');
  el.className = 'toast toast-' + (typ || 'fehler');
  el.textContent = text;
  toasts.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.3s'; setTimeout(() => el.remove(), 300); }, 4000);
}

// --- File list ---
function listeAnzeigen() {
  dateiliste.innerHTML = '';
  dateien.forEach((f, i) => {
    const ext = getExt(f.name);
    const icon = FILE_ICONS[ext] || '📁';
    const div = document.createElement('div');
    div.className = 'datei-eintrag';
    div.setAttribute('role', 'listitem');
    div.innerHTML =
      '<span class="datei-icon">' + icon + '</span>' +
      '<span class="datei-name" title="' + esc(f.name) + '">' + esc(f.name) + '</span>' +
      '<span class="datei-size">' + formatSize(f.size) + '</span>' +
      '<button class="datei-entfernen" data-i="' + i + '" title="Entfernen" aria-label="' + esc(f.name) + ' entfernen">&times;</button>';
    dateiliste.appendChild(div);
  });
  updateBtn();
}

function updateBtn() { startBtn.disabled = dateien.length === 0; }

function dateienHinzufuegen(neueDateien) {
  const erlaubt = ['.eml', '.mbox', '.txt', '.csv', '.xlsx'];
  for (const f of neueDateien) {
    const ext = getExt(f.name);
    if (!erlaubt.includes(ext)) {
      toast('Format nicht unterstützt: ' + f.name + ' — Erlaubt: ' + erlaubt.join(', '));
      continue;
    }
    if (!dateien.some(d => d.name === f.name && d.size === f.size)) {
      dateien.push(f);
    }
  }
  listeAnzeigen();
  ergebnis.className = 'ergebnis';
  ergebnis.style.display = 'none';
}

// --- Dropzone ---
dropzone.addEventListener('click', () => dateiInput.click());
dropzone.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); dateiInput.click(); }
});
document.getElementById('durchsuchen').addEventListener('click', (e) => {
  e.stopPropagation(); dateiInput.click();
});
dateiInput.addEventListener('change', () => {
  if (dateiInput.files.length) dateienHinzufuegen(dateiInput.files);
  dateiInput.value = '';
});
dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('aktiv'); });
dropzone.addEventListener('dragleave', () => dropzone.classList.remove('aktiv'));
dropzone.addEventListener('drop', (e) => {
  e.preventDefault(); dropzone.classList.remove('aktiv');
  if (e.dataTransfer.files.length) dateienHinzufuegen(e.dataTransfer.files);
});

// File remove
dateiliste.addEventListener('click', (e) => {
  const btn = e.target.closest('.datei-entfernen');
  if (btn) { dateien.splice(parseInt(btn.dataset.i), 1); listeAnzeigen(); }
});

// Blacklist tag preview
blacklistArea.addEventListener('input', () => {
  const terms = blacklistArea.value.split('\n').map(s => s.trim()).filter(Boolean);
  blacklistTags.innerHTML = '';
  terms.forEach(t => {
    const tag = document.createElement('span');
    tag.className = 'blacklist-tag';
    tag.textContent = t;
    blacklistTags.appendChild(tag);
  });
});

function setGesperrt(val) {
  blacklistArea.disabled = val;
  dropzone.classList.toggle('gesperrt', val);
}

// --- Submit ---
startBtn.addEventListener('click', async () => {
  if (!dateien.length) return;
  startBtn.disabled = true;
  setGesperrt(true);
  fortschritt.classList.add('sichtbar');
  ergebnis.className = 'ergebnis';
  ergebnis.style.display = 'none';

  const formData = new FormData();
  dateien.forEach(f => formData.append('files', f));
  formData.append('blacklist', blacklistArea.value);

  try {
    const resp = await fetch('/anonymize', { method: 'POST', body: formData });
    if (!resp.ok) {
      let msg = 'Unbekannter Fehler';
      try { const err = await resp.json(); msg = err.fehler || msg; } catch(e) {}
      throw new Error(msg);
    }
    const blob = await resp.blob();
    const disposition = resp.headers.get('Content-Disposition') || '';
    let filename = 'anonymisiert.zip';
    const match = disposition.match(/filename[*]?=(?:UTF-8''|"?)([^";]+)/i);
    if (match) filename = decodeURIComponent(match[1].replace(/"/g, ''));

    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename; a.click();
    URL.revokeObjectURL(url);

    // Statistics
    const statHeader = resp.headers.get('X-Statistik');
    let stat = null;
    if (statHeader) { try { stat = JSON.parse(statHeader); } catch(e) {} }

    if (stat && stat.treffer && Object.keys(stat.treffer).length) {
      let html = '<div class="ergebnis-titel">✔ Anonymisierung abgeschlossen</div>';
      html += '<div>Download wurde gestartet.</div>';
      html += '<div class="stat-grid">';
      const sortiert = Object.entries(stat.treffer).sort((a, b) => b[1] - a[1]);
      for (const [label, anzahl] of sortiert) {
        const versch = stat.zaehler[label] || '?';
        html += '<div class="stat-card"><div class="stat-number">' + anzahl + '</div>' +
          '<div class="stat-label">' + esc(label) + '</div>' +
          '<div class="stat-detail">' + versch + ' versch.</div></div>';
      }
      html += '</div>';
      ergebnis.className = 'ergebnis erfolg';
      ergebnis.innerHTML = html;
    } else {
      ergebnis.className = 'ergebnis info';
      ergebnis.innerHTML = '<div class="ergebnis-titel">ℹ️ Keine personenbezogenen Daten erkannt</div>' +
        '<div>Die Datei wurde heruntergeladen, aber es wurden keine Treffer gefunden. ' +
        'Prüfen Sie, ob die Datei Text enthält oder nutzen Sie die Blacklist für spezifische Begriffe.</div>';
    }
    ergebnis.style.display = 'block';
    dateien = [];
    listeAnzeigen();
  } catch (e) {
    ergebnis.className = 'ergebnis fehler';
    ergebnis.innerHTML = '<div class="ergebnis-titel">Fehler</div><div>' + esc(e.message) + '</div>';
    ergebnis.style.display = 'block';
  } finally {
    fortschritt.classList.remove('sichtbar');
    setGesperrt(false);
    startBtn.disabled = dateien.length === 0;
  }
});
</script>
</body>
</html>
"""


def _heartbeat_watchdog(timeout=30):
    global _letzter_heartbeat
    while True:
        time.sleep(3)
        if time.time() - _letzter_heartbeat > timeout:
            os._exit(0)


if __name__ == "__main__":
    import webbrowser
    port = int(os.environ.get("PORT", 5000))
    print(f"Anonymisierer läuft auf http://localhost:{port}")
    print("Keine Daten werden gespeichert — alles nur im RAM.")
    _letzter_heartbeat = time.time()
    _heartbeat_aktiv = True
    t = threading.Thread(target=_heartbeat_watchdog, daemon=True)
    t.start()
    threading.Timer(1.5, webbrowser.open, args=[f"http://localhost:{port}"]).start()
    app.run(host="127.0.0.1", port=port, debug=False)
