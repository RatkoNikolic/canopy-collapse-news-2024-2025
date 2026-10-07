#!/usr/bin/env bash
# Start, stop or inspect the collection jobs (story-v01 window only).
# Every job is idempotent and resumes from what is stored, so `stop` is a safe
# pause and `start` a resume.
#   scripts/jobs.sh start | fetch | process | stop | status
#   (start = discovery, fetch = article pages, process = documents + lemmas once,
#    autoprocess = process every 30 min while a fetch runs; embed = Batch API embeddings, following the fetch)
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p builds/logs

start() {
  for job in mediacloud sitemaps naslovi; do
    pgrep -f "[c]anopy-news discover --route $job" >/dev/null && continue
    setsid nohup uv run canopy-news discover --route "$job" --window story-v01 \
      > "builds/logs/${job}_story.log" 2>&1 < /dev/null &
  done
  sleep 2; status
}

stop() {
  pkill -f "[a]utoprocess-loop"; pkill -f "[c]anopy-news (discover|fetch|dumps|documents|lemmas|embed)" && echo "stopped" || echo "nothing running"
}

status() {
  echo "running:"; pgrep -fa "[c]anopy-news" | grep python | sed 's/.*canopy-news /  /' || echo "  none"
  pgrep -f "[a]utoprocess-loop" >/dev/null && echo "  autoprocess loop"
  for d in builds/discovery/*/; do printf "  %-22s %s files\n" "$(basename "$d")" "$(ls "$d" | wc -l)"; done
}

fetch() {
  pgrep -f "[c]anopy-news fetch" >/dev/null && { echo "fetch already running"; return; }
  setsid nohup uv run canopy-news fetch --window story-v01 \
    >> builds/logs/fetch_story.log 2>&1 < /dev/null &
  sleep 2; status
}

process() {
  pgrep -f "[b]in/canopy-news (documents|lemmas)" >/dev/null && { echo "process already running"; return; }
  setsid nohup bash -c 'uv run canopy-news documents && OMP_NUM_THREADS=1 uv run canopy-news lemmas --workers 12' \
    >> builds/logs/process_story.log 2>&1 < /dev/null &
  sleep 2; status
}

embed() {
  # gemini-embedding-2 Batch API, one ≈ 800k-token batch at a time, following the fetch ($, budget-guarded)
  pgrep -f "[b]in/canopy-news embed run" >/dev/null && { echo "embed already running"; return; }
  setsid nohup uv run canopy-news embed run --follow \
    >> builds/logs/embed.log 2>&1 < /dev/null &
  sleep 2; status
}

autoprocess() {
  # documents + lemmas every 30 min while a fetch or discovery runs (a fetch restart
  # does not end it), then one last pass; the stages lock, so passes never overlap
  pgrep -f "[a]utoprocess-loop" >/dev/null && { echo "autoprocess already running"; return; }
  setsid nohup bash -c '
    : autoprocess-loop
    while pgrep -f "[c]anopy-news (fetch|discover)" >/dev/null; do
      uv run canopy-news documents && OMP_NUM_THREADS=1 uv run canopy-news lemmas --workers 12
      sleep 1800
    done
    uv run canopy-news documents && OMP_NUM_THREADS=1 uv run canopy-news lemmas --workers 12
  ' >> builds/logs/process_story.log 2>&1 < /dev/null &
  sleep 2; status
}

case "${1:-status}" in
  start) start ;; fetch) fetch ;; process) process ;; autoprocess) autoprocess ;; embed) embed ;;
  stop) stop ;; status) status ;;
  *) echo "usage: $0 start|fetch|process|autoprocess|embed|stop|status"; exit 1 ;;
esac
