#!/bin/bash
# Pełny przebieg jednej sesji: symulator (C) -> gniazdo TCP -> odbiornik/analiza (Python).
# Użycie: ./run_demo.sh [P01] [speed]
set -e
cd "$(dirname "$0")"
P=${1:-P01}; SPEED=${2:-10}
make -s -C simulator
python3 analysis/receiver.py --port 5555 --video data/$P/video.avi --out results/stream_$P.csv &
RX=$!
./simulator/sim 127.0.0.1 5555 $SPEED data/$P/polar_rr.csv:POLAR_RR data/$P/empatica_eda.csv:EMP_EDA data/$P/empatica_bvp.csv:EMP_BVP
wait $RX
