#!/bin/bash
# Odtworzenie sesji w czasie rzeczywistym: symulator C (Moduł 1) -> TCP -> odbiornik (Moduł 2).
# Najpierw: python analysis/process_session.py sesje/<ID>   (tworzy wyniki/strumienie/)
# Użycie (Linux/WSL/QNX):  ./run_stream.sh sesje/P01 [przyspieszenie] [host]
#   host - gdzie działa odbiornik; domyślnie uruchamiany lokalnie (127.0.0.1)
set -e
cd "$(dirname "$0")"
SES=${1:?podaj folder sesji}; SPEED=${2:-1}; HOST=${3:-}
D=$SES/wyniki/strumienie
make -s -C simulator
ARGS=()
for pair in polar_rr:POLAR_RR polar_hr:POLAR_HR empatica_eda:EMP_EDA empatica_bvp:EMP_BVP empatica_acc:EMP_ACC; do
  f=$D/${pair%%:*}.csv; [ -f "$f" ] && ARGS+=("$f:${pair##*:}")
done
[ ${#ARGS[@]} -eq 0 ] && { echo "Brak $D - uruchom najpierw process_session.py"; exit 1; }
if [ -z "$HOST" ]; then
  python3 analysis/receiver.py --session "$SES" &
  RX=$!; HOST=127.0.0.1; sleep 1
fi
./simulator/sim "$HOST" 5555 "$SPEED" "${ARGS[@]}"
[ -n "$RX" ] && wait $RX
