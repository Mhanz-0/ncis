#!/usr/bin/env bash

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

echo "============================================"
echo " SDN DoS Detection/Mitigation Project Startup"
echo "============================================"
echo ""

# ==========================
# Scelta detection mode
# ==========================

if [ -z "$1" ]; then
    echo "Scegli la modalità di detection:"
    echo "1) percentile"
    echo "2) average&std_dev"
    echo ""
    read -p "Inserisci scelta [1/2, default=1]: " choice

    case "$choice" in
        2)
            DETECTION_MODE="average&std_dev"
            ;;
        *)
            DETECTION_MODE="percentile"
            ;;
    esac
else
    DETECTION_MODE="$1"
fi

case "$DETECTION_MODE" in
    "percentile"|"average&std_dev")
        ;;
    *)
        echo "[ERROR] Detection mode non valida: $DETECTION_MODE"
        echo "Usa: percentile oppure average&std_dev"
        exit 1
        ;;
esac

echo "[INFO] Detection mode scelta: $DETECTION_MODE"
echo ""

# ==========================
# Preparazione cartelle
# ==========================

mkdir -p log
mkdir -p log/stealth/server
mkdir -p log/burst/server
mkdir -p log/custom/server
mkdir -p jsonFile

[ -f jsonFile/statistics.json ] || echo "{}" > jsonFile/statistics.json
[ -f jsonFile/aggregatedStats.json ] || echo "{}" > jsonFile/aggregatedStats.json
[ -f jsonFile/blackList.json ] || echo "{}" > jsonFile/blackList.json
[ -f jsonFile/whiteList.json ] || echo "{}" > jsonFile/whiteList.json

# ==========================
# Cleanup precedente
# ==========================

echo "[CLEANUP] Cleaning old Mininet state..."
sudo mn -c > /dev/null 2>&1 || true

echo "[CLEANUP] Killing old Ryu instances..."
pkill -f "ryu-manager.*simple_switch13.py" 2>/dev/null || true
pkill -f "ryu-manager.*controller.py" 2>/dev/null || true

sleep 1

# ==========================
# Log file
# ==========================

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
SAFE_MODE="${DETECTION_MODE//&/_}"

BASELINE_LOG="log/ryu_simple_switch13_${TIMESTAMP}.log"
CUSTOM_LOG="log/ryu_controller_${SAFE_MODE}_${TIMESTAMP}.log"

FLASK_LOG="log/flask_dashboard_${TIMESTAMP}.log"
FLASK_URL="http://127.0.0.1:5000"

# ==========================
# Avvio controller baseline
# ==========================

echo "[START] Starting SimpleSwitch13 baseline controller on port 6633..."
ryu-manager --ofp-tcp-listen-port 6633 simple_switch13.py > "$BASELINE_LOG" 2>&1 &
BASELINE_PID=$!

sleep 2

if ! kill -0 "$BASELINE_PID" 2>/dev/null; then
    echo "[ERROR] simple_switch13.py non è partito correttamente."
    echo "Log:"
    cat "$BASELINE_LOG"
    exit 1
fi

echo "[OK] SimpleSwitch13 avviato. Log: $BASELINE_LOG"

# ==========================
# Avvio controller custom
# ==========================

echo "[START] Starting MainController on port 6634..."
DETECTION_MODE="$DETECTION_MODE" ryu-manager --ofp-tcp-listen-port 6634 controller.py > "$CUSTOM_LOG" 2>&1 &
CUSTOM_PID=$!

sleep 2

if ! kill -0 "$CUSTOM_PID" 2>/dev/null; then
    echo "[ERROR] controller.py non è partito correttamente."
    echo "Log:"
    cat "$CUSTOM_LOG"
    kill "$BASELINE_PID" 2>/dev/null || true
    exit 1
fi

echo "[OK] MainController avviato. Log: $CUSTOM_LOG"
echo ""

# ==========================
# Avvio dashboard Flask
# ==========================

echo "[START] Starting Flask dashboard on port 5000..."

if [ ! -f "flaskInterface/app.py" ]; then
    echo "[ERROR] flaskInterface/app.py non trovato."
    echo "Controlla di avere questa struttura:"
    echo "flaskInterface/app.py"
    echo "flaskInterface/templates/index.html"
    kill "$BASELINE_PID" 2>/dev/null || true
    kill "$CUSTOM_PID" 2>/dev/null || true
    exit 1
fi

if [ ! -f "flaskInterface/templates/index.html" ]; then
    echo "[ERROR] flaskInterface/templates/index.html non trovato."
    echo "Flask cerca index.html dentro flaskInterface/templates/"
    kill "$BASELINE_PID" 2>/dev/null || true
    kill "$CUSTOM_PID" 2>/dev/null || true
    exit 1
fi

cd "$PROJECT_DIR/dashboard"

python3 -m flask --app app run --host 0.0.0.0 --port 5000 > "$PROJECT_DIR/$FLASK_LOG" 2>&1 &
FLASK_PID=$!

cd "$PROJECT_DIR"

sleep 2

if ! kill -0 "$FLASK_PID" 2>/dev/null; then
    echo "[ERROR] Flask dashboard non è partita correttamente."
    echo "Log:"
    cat "$FLASK_LOG"
    kill "$BASELINE_PID" 2>/dev/null || true
    kill "$CUSTOM_PID" 2>/dev/null || true
    exit 1
fi

echo "[OK] Flask dashboard avviata. Log: $FLASK_LOG"
echo "[OPEN] Opening Firefox at $FLASK_URL"

if command -v firefox >/dev/null 2>&1; then
    firefox "$FLASK_URL" >/dev/null 2>&1 &
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$FLASK_URL" >/dev/null 2>&1 &
else
    echo "[WARN] Firefox/xdg-open non trovato. Apri manualmente: $FLASK_URL"
fi

echo ""

# ==========================
# Cleanup finale automatico
# ==========================

cleanup() {
    echo ""
    echo "[STOP] Stopping controllers and dashboard..."

    kill "$BASELINE_PID" 2>/dev/null || true
    kill "$CUSTOM_PID" 2>/dev/null || true

    if [ -n "${FLASK_PID:-}" ]; then
        kill "$FLASK_PID" 2>/dev/null || true
    fi

    wait "$BASELINE_PID" 2>/dev/null || true
    wait "$CUSTOM_PID" 2>/dev/null || true

    if [ -n "${FLASK_PID:-}" ]; then
        wait "$FLASK_PID" 2>/dev/null || true
    fi

    echo "[STOP] Cleaning Mininet..."
    sudo mn -c > /dev/null 2>&1 || true

    echo "[DONE] Shutdown completed."
}

trap cleanup EXIT INT TERM

# ==========================
# Avvio topologia
# ==========================

echo "============================================"
echo " Starting Mininet topology"
echo "============================================"
echo ""
echo "[INFO] Quando sei nella CLI Mininet puoi lanciare:"
echo "       py scenarios.run(\"stealth\")"
echo "       py scenarios.run(\"burst\")"
echo "       py scenarios.run(\"custom\")"
echo "       py scenarios.run(\"all\")"
echo ""
echo "[INFO] Per uscire dalla CLI Mininet usa:"
echo "       exit"
echo ""

sudo python3 topology.py