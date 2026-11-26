#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  Dokument-Anonymisierer"
echo "============================================"
echo

# Python pruefen
if ! command -v python3 &>/dev/null; then
    echo "[FEHLER] Python3 nicht gefunden. Bitte installieren."
    exit 1
fi

# Virtuelle Umgebung erstellen falls nicht vorhanden
if [ ! -d "venv" ]; then
    echo "Erstelle virtuelle Umgebung ..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt

echo
echo "Starte Server auf http://localhost:5000"
echo "Server beendet sich automatisch wenn der Browser-Tab geschlossen wird."
echo

python3 app.py &>/dev/null &
disown

sleep 2
xdg-open http://localhost:5000 2>/dev/null || open http://localhost:5000 2>/dev/null || true
