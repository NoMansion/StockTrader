#!/bin/bash
# Start the background jobs that are not already running. Safe to run at any time, as often as you like.
cd "$(dirname "$0")/.." || exit 1
mkdir -p data
if ! pgrep -f "research/kalshi_download.py" > /dev/null; then
    setsid nohup python3 -u research/kalshi_download.py --interval 0.4 --first-pass 2500 >> data/kalshi_download.log 2>&1 < /dev/null &
    echo "started: history download"
else
    echo "running: history download"
fi
# The paper account runs in ONE place. Once it has moved to the PC, data/PAPER_LOOP_MOVED_TO_PC says so and the
# loop is not started here again (two ledgers would drift apart).
if [ -f data/PAPER_LOOP_MOVED_TO_PC ]; then
    echo "not started: paper loop (moved to the PC; see data/PAPER_LOOP_MOVED_TO_PC)"
elif [ -f data/cloud_config.yaml ] && ! pgrep -f "scripts/paper_loop.py" > /dev/null; then
    setsid nohup python3 -u scripts/paper_loop.py --config data/cloud_config.yaml --every 3 >> data/run_cycle.log 2>&1 < /dev/null &
    echo "started: paper loop"
else
    echo "running or not configured: paper loop"
fi
sleep 2
tail -1 data/kalshi_download.log | cut -c1-160
