#!/bin/sh
# ============================================================================
# BidMaster Pro API 容器入口脚本
# 根据 BMP_DB_TYPE 等待对应数据库就绪后再启动主进程
# 支持：postgresql / mysql
# ============================================================================
set -e

DB_TYPE="${BMP_DB_TYPE:-postgresql}"
WAIT_TIMEOUT="${DB_WAIT_TIMEOUT:-60}"

# 探测 host:port 是否可连接（用 python socket，镜像内已有 python）
wait_for() {
  host="$1"
  port="$2"
  name="$3"
  echo "[entrypoint] 等待 ${name} ${host}:${port} 就绪 ..."
  i=0
  while [ $i -lt "$WAIT_TIMEOUT" ]; do
    if python -c "import socket,sys; s=socket.create_connection(('${host}', ${port}), timeout=2); s.close()" 2>/dev/null; then
      echo "[entrypoint] ${name} 已就绪（耗时 ${i}s）"
      return 0
    fi
    sleep 2
    i=$((i + 2))
  done
  echo "[entrypoint] 警告：等待 ${name} 超时（${WAIT_TIMEOUT}s），继续启动（后端将以降级模式运行）"
  return 0
}

case "$DB_TYPE" in
  mysql)
    wait_for "${BMP_MYSQL_HOST:-mysql}" "${BMP_MYSQL_PORT:-3306}" "MySQL"
    ;;
  postgresql|postgres|pg|*)
    # PG host 从 BMP_DATABASE_URL 解析，默认 postgres:5432
    pg_host="postgres"
    pg_port="5432"
    if [ -n "$BMP_DATABASE_URL" ]; then
      # 简易解析：提取 @ 后的 host:port
      after_at=$(echo "$BMP_DATABASE_URL" | sed 's#.*@##' | sed 's#/.*##')
      if [ -n "$after_at" ]; then
        pg_host=$(echo "$after_at" | cut -d: -f1)
        pg_port=$(echo "$after_at" | cut -d: -f2)
        [ -z "$pg_port" ] && pg_port="5432"
      fi
    fi
    wait_for "$pg_host" "$pg_port" "PostgreSQL"
    ;;
esac

echo "[entrypoint] 启动主进程：$@"
exec "$@"
