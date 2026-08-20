#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME=""
PID=""
DURATION=60
INTERVAL=1
OUT_DIR=""

usage() {
  cat <<'EOF'
Usage:
  bash ops/linux_perf_capture.sh [options]

Options:
  --service <name>     systemd service name, for example incentive-api
  --pid <pid>          target process id
  --duration <sec>     total capture duration, default 60
  --interval <sec>     sample interval, default 1
  --out-dir <path>     output directory, default ops/output/<timestamp>
  --help               show this message

Examples:
  bash ops/linux_perf_capture.sh --service incentive-api --duration 90 --interval 1
  bash ops/linux_perf_capture.sh --pid 12345 --duration 120 --out-dir /tmp/seckill-capture
EOF
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

run_optional() {
  local name="$1"
  shift
  if "$@" >"$OUT_DIR/$name" 2>&1; then
    return 0
  fi
  echo "command failed: $*" >"$OUT_DIR/$name"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)
      SERVICE_NAME="$2"
      shift 2
      ;;
    --pid)
      PID="$2"
      shift 2
      ;;
    --duration)
      DURATION="$2"
      shift 2
      ;;
    --interval)
      INTERVAL="$2"
      shift 2
      ;;
    --out-dir)
      OUT_DIR="$2"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$PID" && -z "$SERVICE_NAME" ]]; then
  echo "Either --service or --pid must be provided." >&2
  usage
  exit 1
fi

if [[ -z "$PID" && -n "$SERVICE_NAME" ]]; then
  PID="$(systemctl show -p MainPID --value "$SERVICE_NAME" 2>/dev/null || true)"
  if [[ "$PID" == "0" ]]; then
    PID=""
  fi
fi

STAMP="$(date '+%Y%m%d_%H%M%S')"
OUT_DIR="${OUT_DIR:-ops/output/$STAMP}"
mkdir -p "$OUT_DIR"

COUNT=$(( (DURATION + INTERVAL - 1) / INTERVAL ))
START_TIME="$(date '+%Y-%m-%d %H:%M:%S')"

cat >"$OUT_DIR/meta.txt" <<EOF
service=$SERVICE_NAME
pid=$PID
duration=$DURATION
interval=$INTERVAL
start_time=$START_TIME
host=$(hostname)
EOF

run_optional "date.log" date
run_optional "uname.log" uname -a
run_optional "uptime.log" uptime
run_optional "free.log" free -h
run_optional "df.log" df -h

if command_exists lscpu; then
  run_optional "lscpu.log" lscpu
fi

if command_exists lsblk; then
  run_optional "lsblk.log" lsblk
fi

if command_exists ss; then
  run_optional "ss_summary.log" ss -s
fi

if [[ -n "$PID" ]]; then
  run_optional "ps_process.log" ps -fp "$PID"
  run_optional "ps_threads.log" ps -Lp "$PID" -o pid,tid,%cpu,%mem,stat,comm --sort=-%cpu
  if command_exists top; then
    run_optional "top_threads_start.log" top -b -H -n 1 -p "$PID"
  fi
  if command_exists jcmd; then
    run_optional "jcmd_vm_flags.log" jcmd "$PID" VM.flags
    run_optional "jcmd_gc_heap.log" jcmd "$PID" GC.heap_info
  fi
  if command_exists jstack; then
    run_optional "jstack_start.log" jstack "$PID"
  fi
fi

declare -a bg_pids=()

if command_exists vmstat; then
  vmstat "$INTERVAL" "$COUNT" >"$OUT_DIR/vmstat.log" 2>&1 &
  bg_pids+=("$!")
fi

if command_exists iostat; then
  iostat -xz "$INTERVAL" "$COUNT" >"$OUT_DIR/iostat.log" 2>&1 &
  bg_pids+=("$!")
fi

if command_exists mpstat; then
  mpstat -P ALL "$INTERVAL" "$COUNT" >"$OUT_DIR/mpstat.log" 2>&1 &
  bg_pids+=("$!")
fi

if command_exists sar; then
  sar -n DEV "$INTERVAL" "$COUNT" >"$OUT_DIR/sar_dev.log" 2>&1 &
  bg_pids+=("$!")
fi

if [[ -n "$PID" ]] && command_exists pidstat; then
  pidstat -rud -h -p "$PID" "$INTERVAL" "$COUNT" >"$OUT_DIR/pidstat.log" 2>&1 &
  bg_pids+=("$!")
fi

if [[ -n "$PID" ]] && command_exists jstat; then
  jstat -gcutil "$PID" $((INTERVAL * 1000)) "$COUNT" >"$OUT_DIR/jstat_gcutil.log" 2>&1 &
  bg_pids+=("$!")
fi

for job_pid in "${bg_pids[@]}"; do
  wait "$job_pid" || true
done

if [[ -n "$PID" ]]; then
  if command_exists top; then
    run_optional "top_threads_end.log" top -b -H -n 1 -p "$PID"
  fi
  if command_exists jstack; then
    run_optional "jstack_end.log" jstack "$PID"
  fi
fi

if [[ -n "$SERVICE_NAME" ]] && command_exists journalctl; then
  journalctl -u "$SERVICE_NAME" --since "$START_TIME" --no-pager >"$OUT_DIR/journal.log" 2>&1 || true
fi

if command_exists ss; then
  run_optional "ss_connections.log" ss -antp
fi

echo "capture_complete=true" >>"$OUT_DIR/meta.txt"
echo "output_dir=$OUT_DIR" >>"$OUT_DIR/meta.txt"
echo "Linux performance capture finished. Output: $OUT_DIR"
