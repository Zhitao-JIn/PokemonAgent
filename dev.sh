#!/usr/bin/env bash
# 一键启动观测台：后端（FastAPI + 模拟器）+ 前端（vite dev）。
#
# 用法：
#   bash dev.sh              # 起两端，Ctrl+C 一起退
#   DASHSCOPE_API_KEY=sk-xx bash dev.sh   # 显式带 key（不设则 LLM 调用会失败）
#
# 端口：后端 127.0.0.1:8000（POKEMON_API_PORT 可改），前端 5173（vite 默认）。
set -euo pipefail
cd "$(dirname "$0")"

ROM="assets/rom"
[ -f "$ROM" ] || { echo "找不到 ROM: $ROM（POKEMON_ROM 指向它）"; exit 1; }

# 选 Python：优先系统 3.12（装齐了 fastapi/uvicorn 等依赖），退回 PATH 里的 python。
PY=""
if command -v py >/dev/null 2>&1; then
  PY=$(py -3.12 -c "import sys; print(sys.executable)" 2>/dev/null || py -c "import sys; print(sys.executable)")
else
  PY=$(command -v python || true)
fi
[ -n "$PY" ] || { echo "找不到 Python 3.12（py launcher 或 PATH 里的 python）"; exit 1; }
echo "使用 Python: $PY"

if [ -z "${DASHSCOPE_API_KEY:-}" ] && [ -z "${ANTHROPIC_AUTH_TOKEN:-}" ]; then
  echo "警告: 未设置 DASHSCOPE_API_KEY/ANTHROPIC_AUTH_TOKEN——后端能起，但 LLM 调用会失败"
fi

[ -d web/node_modules ] || { echo "web/node_modules 不存在，先跑: cd web && npm install"; exit 1; }

LOG_API="$(pwd)/dev-api.log"
LOG_WEB="$(pwd)/dev-web.log"
POKEMON_ROM="$ROM" "$PY" -m pokemon_agent.api >"$LOG_API" 2>&1 &
API_PID=$!
( cd web && npm run dev ) >"$LOG_WEB" 2>&1 &
WEB_PID=$!

cleanup() { kill "$API_PID" "$WEB_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo
echo "后端  : http://127.0.0.1:8000/health"
echo "前端  : http://localhost:5173"
echo "日志  : $LOG_API / $LOG_WEB"
echo "退出  : Ctrl+C（同时关掉两个进程）"
echo
wait
