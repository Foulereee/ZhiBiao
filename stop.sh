#!/usr/bin/env bash
#===============================================================================
# 智标（ZhiBiao）停止脚本 —— Linux
#
# 用法：
#   ./stop.sh                         # 停本地模式启动的 API 与前端
#   ./stop.sh --api-port 8010         # 指定 API 端口
#   ./stop.sh --docker                # 停 Docker 容器（compose stop）
#   ./stop.sh --docker --remove       # 删容器与网络（数据卷保留）
#   ./stop.sh --docker --remove --volumes  # 连数据卷一起删（等于删库！）
#===============================================================================
set -uo pipefail

API_PORT=8000
DEV_PORT=15168
MODE="auto"
REMOVE=0
VOLUMES=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --api-port)  API_PORT="$2"; shift 2 ;;
        --dev-port)  DEV_PORT="$2"; shift 2 ;;
        --docker)    MODE="docker"; shift ;;
        --local)     MODE="local"; shift ;;
        --remove)    REMOVE=1; shift ;;
        --volumes)   VOLUMES=1; shift ;;
        --help|-h)   head -14 "$0"; exit 0 ;;
        *) echo "  [X]  未知参数: $1"; exit 1 ;;
    esac
done

ROOT="$(cd "$(dirname "$0")" && pwd)"

# 按端口找到监听进程并杀掉
stop_by_port() {
    local port="$1" name="$2"
    local pids=""
    # 优先 ss（iproute2，大多数发行版自带）
    if command -v ss &>/dev/null; then
        pids=$(ss -tlnp 2>/dev/null | grep ":${port} " | grep -oP 'pid=\K\d+' | sort -u | tr '\n' ' ')
    fi
    # 退而求其次用 fuser
    if [ -z "$pids" ] && command -v fuser &>/dev/null; then
        pids=$(fuser "${port}/tcp" 2>/dev/null | tr -d ' ' | tr ' ' '\n' | sort -u | tr '\n' ' ')
    fi
    # 再退 lsof
    if [ -z "$pids" ] && command -v lsof &>/dev/null; then
        pids=$(lsof -ti :"${port}" 2>/dev/null | sort -u | tr '\n' ' ')
    fi
    if [ -n "$pids" ]; then
        echo "  [..] 停止 $name（端口 $port，PID: $pids）"
        echo "$pids" | tr ' ' '\n' | xargs -r kill 2>/dev/null || true
        sleep 2
        echo "$pids" | tr ' ' '\n' | xargs -r kill -9 2>/dev/null || true
        echo "  [OK] $name 已停止"
    else
        echo "  [OK] $name 未在运行（端口 $port 无监听）"
    fi
}

if [ "$MODE" = "docker" ] || { [ "$MODE" = "auto" ] && command -v docker &>/dev/null && [ -f "$ROOT/docker/docker-compose.yml" ]; }; then
    echo "=== Docker 模式 ==="
    if ! docker info &>/dev/null; then
        echo "  [!]  Docker daemon 不可用，尝试本地模式"
        stop_by_port "$API_PORT" "API (uvicorn)"
        stop_by_port "$DEV_PORT" "前端 (vite)"
    elif [ "$REMOVE" -eq 1 ]; then
        if [ "$VOLUMES" -eq 1 ]; then
            echo "  [!]  --volumes 会删除数据卷（等于删库！），3 秒后执行（Ctrl+C 取消）"
            sleep 3
            docker compose -f "$ROOT/docker/docker-compose.yml" down -v
        else
            docker compose -f "$ROOT/docker/docker-compose.yml" down
            echo "  [OK] 容器与网络已删除（数据卷保留）"
        fi
    else
        docker compose -f "$ROOT/docker/docker-compose.yml" stop
        echo "  [OK] 容器已停止（数据卷保留）"
    fi
else
    echo "=== 本地模式 ==="
    stop_by_port "$API_PORT" "API (uvicorn)"
    stop_by_port "$DEV_PORT" "前端 (vite)"
fi

echo "完成。"
