#!/usr/bin/env bash
#===============================================================================
# 智标（ZhiBiao）一键安装 / 部署脚本 —— Linux (bash)
#
# 支持发行版：Ubuntu / Debian (apt)  ·  CentOS / RHEL / Rocky / AlmaLinux (dnf/yum)
#
# 自动判断走哪条路：
#   * Docker 引擎可用  -> 方式一：Docker 全量部署（含 PostgreSQL/Redis/MinIO/站点）
#   * 否则              -> 方式二：本地开发（系统包管理器装 PG）
#
# 常用用法：
#   ./install.sh                                   # 自动判断
#   ./install.sh --mode docker                     # 强制 Docker
#   ./install.sh --mode local                      # 强制本地开发
#   ./install.sh --llm-api-key sk-xxx --yes        # 非交互，顺便写入 Key
#   ./install.sh --install-deps                    # 缺什么装什么（需 sudo）
#   ./install.sh --mode local --skip-frontend      # 只装后端 + 数据库
#
# 停止服务：./stop.sh  （Docker 模式：docker compose -f docker/docker-compose.yml stop）
#===============================================================================
set -uo pipefail

# ─────────────────────────── 参数解析 ───────────────────────────
MODE="auto"
LLM_API_KEY=""
LLM_API_BASE=""
ADMIN_EMAIL="admin@bidmaster.pro"
ADMIN_PASSWORD=""
DB_NAME="bidmaster"
PG_USER="postgres"
PG_PASSWORD="postgres"
PG_PORT=5432
API_PORT=8000
SITE_PORT=8080
DEV_PORT=15168
INSTALL_DEPS=0
SKIP_FRONTEND=0
NO_START=0
FORCE=0
YES=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)            MODE="$2"; shift 2 ;;
        --llm-api-key)     LLM_API_KEY="$2"; shift 2 ;;
        --llm-api-base)    LLM_API_BASE="$2"; shift 2 ;;
        --admin-email)     ADMIN_EMAIL="$2"; shift 2 ;;
        --admin-password)  ADMIN_PASSWORD="$2"; shift 2 ;;
        --db-name)         DB_NAME="$2"; shift 2 ;;
        --pg-user)         PG_USER="$2"; shift 2 ;;
        --pg-password)     PG_PASSWORD="$2"; shift 2 ;;
        --pg-port)         PG_PORT="$2"; shift 2 ;;
        --api-port)        API_PORT="$2"; shift 2 ;;
        --site-port)       SITE_PORT="$2"; shift 2 ;;
        --dev-port)        DEV_PORT="$2"; shift 2 ;;
        --install-deps)    INSTALL_DEPS=1; shift ;;
        --skip-frontend)   SKIP_FRONTEND=1; shift ;;
        --no-start)        NO_START=1; shift ;;
        --force)           FORCE=1; shift ;;
        --yes)             YES=1; shift ;;
        --help|-h)
            head -28 "$0" | tail -26; exit 0 ;;
        *)
            echo "  [X]  未知参数: $1  （--help 查看用法）"; exit 1 ;;
    esac
done

# ─────────────────────────── 输出工具 ───────────────────────────
ROOT="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"

log()  { echo "[$(date +%H:%M:%S)] $1" >> "$LOG_FILE"; }
title() { echo ""; echo "======================================================================"; echo "  $1"; echo "======================================================================"; log "TITLE $1"; }
step()  { echo ""; echo "[$1] $2" | cat; log "STEP $1 $2"; }
ok()    { echo "    [OK] $1"; log "OK   $1"; }
info()  { echo "    [..] $1"; log "INFO $1"; }
warn()  { echo "    [!]  $1"; log "WARN $1"; }
die()   { echo ""; echo "    [X]  $1"; echo ""; echo "    日志: $LOG_FILE"; log "FATAL $1"; exit 1; }

have()  { command -v "$1" &>/dev/null; }
test_port() { timeout 1 bash -c "echo >/dev/tcp/127.0.0.1/$1" 2>/dev/null; }
wait_http() {
    local url="$1" timeout_s="$2"
    local deadline=$(( $(date +%s) + timeout_s ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        if curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null | grep -q '^[23]'; then
            return 0
        fi
        sleep 4; echo -n '.'
    done
    echo ''; return 1
}

# ─────────────────────────── OS 检测 ───────────────────────────
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    else
        echo "unknown"
    fi
}

detect_pkg_mgr() {
    if have dnf;  then echo "dnf"
    elif have yum; then echo "yum"
    elif have apt-get; then echo "apt"
    else echo "none"
    fi
}

install_docker() {
    info "安装 Docker（get.docker.com 官方脚本）…"
    curl -fsSL https://get.docker.com | sh 2>&1 | tee -a "$LOG_FILE"
    if ! have docker; then die "Docker 安装失败。请手动安装：https://docs.docker.com/engine/install/"; fi
    systemctl enable docker 2>/dev/null
    systemctl start docker 2>/dev/null
    ok "Docker 已安装并启动"
}

install_local_deps() {
    local os; os="$(detect_os)"
    local mgr; mgr="$(detect_pkg_mgr)"
    info "发行版: $os  包管理器: $mgr"
    [ "$mgr" = "none" ] && die "无法识别包管理器（apt/dnf/yum 都没有）。请手动安装 Python3、Node.js、PostgreSQL。"

    local need_sudo=""
    [ "$(id -u)" -ne 0 ] && need_sudo="sudo"

    case "$os" in
        ubuntu|debian|linuxmint)
            $need_sudo apt-get update -y 2>&1 | tail -1 | tee -a "$LOG_FILE"
            $need_sudo apt-get install -y python3 python3-venv python3-dev nodejs npm \
                postgresql postgresql-contrib libpq-dev curl 2>&1 | tail -3 | tee -a "$LOG_FILE"
            ;;
        centos|rhel|rocky|almalinux|fedora)
            $need_sudo "$mgr" install -y python3 python3-devel nodejs npm \
                postgresql-server postgresql-contrib libpq-devel curl 2>&1 | tail -3 | tee -a "$LOG_FILE"
            # CentOS/RHEL 默认 PostgreSQL 版本可能偏旧；如需 16，建议加 PGDG 仓库
            ;;
        *)
            warn "未识别的发行版 '$os'，尝试通用安装 …"
            $need_sudo "$mgr" install -y python3 python3-venv nodejs npm postgresql 2>&1 | tail -3 | tee -a "$LOG_FILE"
            ;;
    esac
    ok "系统依赖安装完成"
}

# ─────────────────────────── 环境文件 ───────────────────────────
write_root_env() {
    local dst="$ROOT/.env"
    if [ -f "$dst" ] && [ "$FORCE" -eq 0 ]; then
        info ".env 已存在，保留原文件（如需重建加 --force）"; return
    fi
    [ -f "$dst" ] && cp "$dst" "$dst.bak-$(date +%Y%m%d-%H%M%S)" && info "已备份 .env"
    local url="postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/${DB_NAME}"
    sed -e "s|^BMP_DATABASE_URL=.*|BMP_DATABASE_URL=${url}|" \
        -e "s|^BMP_PORT=.*|BMP_PORT=${API_PORT}|" \
        -e "s|^BMP_DEBUG=.*|BMP_DEBUG=false|" \
        "$ROOT/.env.example" > "$dst"
    [ -n "$LLM_API_KEY" ]  && sed -i "s|^BMP_LLM_API_KEY=.*|BMP_LLM_API_KEY=${LLM_API_KEY}|" "$dst"
    [ -n "$LLM_API_BASE" ] && sed -i "s|^BMP_LLM_API_BASE=.*|BMP_LLM_API_BASE=${LLM_API_BASE}|" "$dst"
    ok ".env 已生成（数据库指向 127.0.0.1:$PG_PORT/$DB_NAME）"
    [ -z "$LLM_API_KEY" ] && warn "BMP_LLM_API_KEY 仍为空：模型类功能需要它，稍后可在 .env 里补"
}

write_docker_env() {
    local dst="$ROOT/docker/.env.docker"
    if [ -f "$dst" ] && [ "$FORCE" -eq 0 ]; then
        info "docker/.env.docker 已存在，保留原文件"; return
    fi
    [ -f "$dst" ] && cp "$dst" "$dst.bak-$(date +%Y%m%d-%H%M%S)" && info "已备份 docker/.env.docker"
    sed -e "s|^WEB_PORT=.*|WEB_PORT=${SITE_PORT}|" \
        -e "s|^API_PORT=.*|API_PORT=${API_PORT}|" \
        -e "s|^UVICORN_WORKERS=.*|UVICORN_WORKERS=1|" \
        "$ROOT/docker/.env.docker.example" > "$dst"
    [ -n "$LLM_API_KEY" ]  && sed -i "s|^LLM_API_KEY=.*|LLM_API_KEY=${LLM_API_KEY}|" "$dst"
    [ -n "$LLM_API_BASE" ] && sed -i "s|^LLM_API_BASE=.*|LLM_API_BASE=${LLM_API_BASE}|" "$dst"
    grep -q '^UVICORN_WORKERS=' "$dst" || echo 'UVICORN_WORKERS=1' >> "$dst"
    ok "docker/.env.docker 已生成（站点端口 $SITE_PORT / API $API_PORT）"
    # 根 .env 必须存在（容器会 bind-mount），否则 Docker 会把它建成目录
    [ ! -f "$ROOT/.env" ] && cp "$ROOT/.env.example" "$ROOT/.env" && ok "根 .env 已从 .env.example 创建"
}

# ─────────────────────────── PostgreSQL（方式二） ───────────────────────────
ensure_postgres() {
    # 已在运行？
    if test_port "$PG_PORT"; then ok "PostgreSQL 已在 127.0.0.1:$PG_PORT 运行"; return; fi

    # 尝试 systemctl 启动
    if have systemctl; then
        info "尝试 systemctl start postgresql …"
        sudo systemctl start postgresql 2>/dev/null || systemctl start postgresql 2>/dev/null || true
        sleep 3
    fi

    if test_port "$PG_PORT"; then ok "PostgreSQL 已启动（systemctl）"; return; fi

    # 尝试 pg_ctl（CentOS 的 PGDG 安装路径）
    local pg_ctl=""
    for d in /usr/pgsql-16/bin /usr/pgsql-15/bin /usr/lib/postgresql/16/bin /usr/lib/postgresql/15/bin; do
        [ -x "$d/pg_ctl" ] && pg_ctl="$d/pg_ctl" && break
    done
    if [ -n "$pg_ctl" ]; then
        local data_dir="/var/lib/pgsql/data"
        [ -d "/var/lib/pgsql/16/data" ] && data_dir="/var/lib/pgsql/16/data"
        if [ -d "$data_dir" ]; then
            info "pg_ctl start -D $data_dir …"
            sudo "$pg_ctl" -D "$data_dir" -l "$LOG_DIR/postgres.log" -w start 2>&1 | tee -a "$LOG_FILE" || true
            sleep 3
        fi
    fi

    if test_port "$PG_PORT"; then ok "PostgreSQL 已启动"; return; fi

    die "PostgreSQL 无法启动。请手动执行：
    Ubuntu/Debian:  sudo apt install postgresql && sudo systemctl start postgresql
    CentOS/RHEL:   sudo dnf install postgresql-server && sudo postgresql-setup --initdb && sudo systemctl start postgresql
    或改用 Docker:  ./install.sh --mode docker"
}

ensure_database() {
    local psql_cmd="psql"
    have psql || die "找不到 psql。请安装 PostgreSQL 客户端：apt install postgresql-client 或 dnf install postgresql"
    export PGPASSWORD="$PG_PASSWORD"

    # 切换到 postgres 用户执行（Linux 上 PG 默认 peer 认证）
    local run_psql="$psql_cmd"
    if [ "$(id -un)" != "postgres" ] && have sudo; then
        run_psql="sudo -u postgres $psql_cmd"
    fi

    # 建库
    local exists; exists=$($run_psql -h 127.0.0.1 -p "$PG_PORT" -U "$PG_USER" -d postgres -tAc \
        "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" 2>/dev/null || echo "")
    if [ "$exists" != "1" ]; then
        info "创建数据库 $DB_NAME …"
        $run_psql -h 127.0.0.1 -p "$PG_PORT" -U "$PG_USER" -d postgres -c "CREATE DATABASE \"$DB_NAME\"" 2>&1 | tee -a "$LOG_FILE"
        ok "数据库 $DB_NAME 已创建"
    else
        ok "数据库 $DB_NAME 已存在"
    fi

    # 导入 init_pg.sql
    info "导入 db/init_pg.sql（幂等）…"
    $run_psql -h 127.0.0.1 -p "$PG_PORT" -U "$PG_USER" -d "$DB_NAME" -f "$ROOT/db/init_pg.sql" 2>&1 | tee -a "$LOG_FILE"
    ok "init_pg.sql 执行完成"

    # init_db() 补齐表
    local venv_py="$ROOT/venv/bin/python"
    if [ -x "$venv_py" ]; then
        info "执行 init_db() 补齐全部表 …"
        local url="postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/${DB_NAME}"
        BMP_DATABASE_URL="$url" "$venv_py" -c \
            'import asyncio; from services.database import init_db; asyncio.run(init_db())' 2>&1 | tee -a "$LOG_FILE" || true
        local tbl_count; tbl_count=$($run_psql -h 127.0.0.1 -p "$PG_PORT" -U "$PG_USER" -d "$DB_NAME" -tAc \
            "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null | tr -d ' ')
        ok "表结构就绪：public 下 ${tbl_count} 张表"
    else
        warn "没找到 venv 里的 python，跳过 init_db()；启动 API 时会自动补齐"
    fi
}

# ─────────────────────────── 方式二：本地开发 ───────────────────────────
install_local() {
    step "1/8" "检查 Python"
    if ! have python3; then
        if [ "$INSTALL_DEPS" -eq 1 ]; then
            install_local_deps
        else
            die "未找到 python3。安装方法：
    Ubuntu/Debian:  sudo apt install python3 python3-venv python3-dev
    CentOS/RHEL:   sudo dnf install python3 python3-devel
    或加 --install-deps 让本脚本自动安装"
        fi
    fi
    local py_ver; py_ver=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo "0.0")
    log "python3 版本 $py_ver"
    [ "$(printf '%s' "$py_ver" | awk -F. '{print $1*100+$2}')" -lt 312 ] && \
        die "Python 版本过低: $py_ver（需要 3.12+）。建议用 pyenv 或 deadsnakes PPA 装 3.12"
    ok "Python $py_ver"

    step "2/8" "创建虚拟环境并安装后端依赖（首次约 2-4 分钟）"
    local venv_py="$ROOT/venv/bin/python"
    if [ ! -x "$venv_py" ]; then
        info "创建 venv …"
        python3 -m venv "$ROOT/venv" 2>&1 | tee -a "$LOG_FILE"
        [ ! -x "$venv_py" ] && die "创建虚拟环境失败。Ubuntu 需要 python3-venv: sudo apt install python3-venv"
        ok "venv 已创建"
    else
        ok "venv 已存在，复用"
    fi
    info "pip install -e .（输出较多，只写日志）…"
    "$venv_py" -m pip install --disable-pip-version-check -e "$ROOT" 2>&1 | tail -5 | tee -a "$LOG_FILE"
    [ "${PIPESTATUS[0]}" -ne 0 ] && die "pip install -e . 失败。详见 $LOG_FILE"
    ok "后端依赖安装完成"

    step "3/8" "安装前端依赖"
    if [ "$SKIP_FRONTEND" -eq 1 ]; then
        warn "已按 --skip-frontend 跳过"
    elif ! have npm; then
        if [ "$INSTALL_DEPS" -eq 1 ]; then
            info "安装 Node.js …"
            local os; os="$(detect_os)"
            case "$os" in
                ubuntu|debian)
                    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - 2>&1 | tail -2 | tee -a "$LOG_FILE"
                    sudo apt-get install -y nodejs 2>&1 | tail -2 | tee -a "$LOG_FILE" ;;
                *)
                    curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash - 2>&1 | tail -2 | tee -a "$LOG_FILE"
                    sudo dnf install -y nodejs 2>&1 | tail -2 | tee -a "$LOG_FILE" || \
                        sudo yum install -y nodejs 2>&1 | tail -2 | tee -a "$LOG_FILE" ;;
            esac
        else
            warn "未找到 npm，跳过前端。安装 Node.js 18+：
    Ubuntu:  curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt install nodejs
    CentOS:  curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash - && sudo dnf install nodejs
    或用 nvm:  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash && nvm install --lts"
        fi
    elif [ -d "$ROOT/packages/desktop/node_modules" ]; then
        ok "node_modules 已存在，跳过"
    else
        info "npm install …"
        (cd "$ROOT/packages/desktop" && npm install) 2>&1 | tail -5 | tee -a "$LOG_FILE"
        ok "前端依赖安装完成"
    fi

    step "4/8" "准备 PostgreSQL"
    ensure_postgres

    step "5/8" "建库 + 建表"
    ensure_database

    step "6/8" "生成 .env"
    write_root_env

    step "7/8" "创建管理员账号（幂等）"
    local venv_py="$ROOT/venv/bin/python"
    export ADMIN_EMAIL="$ADMIN_EMAIL"
    [ -n "$ADMIN_PASSWORD" ] && export ADMIN_PASSWORD="$ADMIN_PASSWORD"
    export PYTHONIOENCODING=utf-8
    "$venv_py" "$ROOT/deploy/seed_admin.py" 2>&1 | tee -a "$LOG_FILE"
    ok "管理员账号: $ADMIN_EMAIL"

    step "8/8" "启动服务"
    if [ "$NO_START" -eq 1 ]; then
        warn "已按 --no-start 跳过。手动启动："
        info "后端: $ROOT/venv/bin/python -m uvicorn services.main:app --reload --host 0.0.0.0 --port $API_PORT"
        info "前端: cd packages/desktop && npm run dev -- --port $DEV_PORT --strictPort"
        return
    fi
    if test_port "$API_PORT"; then
        ok "API 已在 127.0.0.1:$API_PORT 运行，跳过启动"
    else
        export PYTHONIOENCODING=utf-8; export PYTHONUTF8=1
        export VITE_API_TARGET="http://127.0.0.1:$API_PORT"
        info "启动 uvicorn …"
        nohup "$venv_py" -m uvicorn services.main:app --host 0.0.0.0 --port "$API_PORT" \
            >"$LOG_DIR/api.out.log" 2>"$LOG_DIR/api.err.log" &
        info "等待 API 就绪（http://127.0.0.1:$API_PORT/api/health）…"
        wait_http "http://127.0.0.1:$API_PORT/api/health" 90 && ok "API 已就绪" || \
            warn "API 未在 90 秒内就绪，请看 $LOG_DIR/api.err.log"
    fi
    if [ "$SKIP_FRONTEND" -eq 0 ] && have npm && ! test_port "$DEV_PORT"; then
        export VITE_API_TARGET="http://127.0.0.1:$API_PORT"
        info "启动 vite …"
        (cd "$ROOT/packages/desktop" && nohup npm run dev -- --port "$DEV_PORT" --strictPort \
            >"$LOG_DIR/web.out.log" 2>"$LOG_DIR/web.err.log" &)
        info "等待前端就绪（http://127.0.0.1:$DEV_PORT/）…"
        wait_http "http://127.0.0.1:$DEV_PORT/" 120 && ok "前端已就绪" || \
            warn "前端未在 120 秒内就绪，请看 $LOG_DIR/web.err.log"
    fi
    echo ""
    ok "站点:        http://127.0.0.1:$DEV_PORT/"
    ok "API 文档:    http://127.0.0.1:$API_PORT/docs"
    ok "健康检查:    http://127.0.0.1:$API_PORT/api/health"
    info "登录账号:    $ADMIN_EMAIL"
    info "停止:        kill \$(cat $ROOT/logs/api.pid 2>/dev/null)  或直接 kill 对应进程"
}

# ─────────────────────────── 方式一：Docker ───────────────────────────
install_docker() {
    step "1/6" "检查 Docker 引擎"
    if ! have docker; then
        if [ "$INSTALL_DEPS" -eq 1 ]; then
            install_docker
        else
            echo ""
            echo "    [X]  未找到 docker。安装方法："
            echo "      Ubuntu/Debian:  curl -fsSL https://get.docker.com | sh"
            echo "      CentOS/RHEL:    curl -fsSL https://get.docker.com | sh"
            echo "      或加 --install-deps 让本脚本自动安装"
            echo ""
            return 1
        fi
    fi
    if ! docker info &>/dev/null; then
        warn "Docker daemon 不可用。尝试启动 …"
        sudo systemctl start docker 2>/dev/null || systemctl start docker 2>/dev/null || true
        sleep 3
        docker info &>/dev/null || { warn "Docker daemon 仍不可用，请执行: sudo systemctl start docker"; return 1; }
    fi
    local sv; sv=$(docker info --format '{{.ServerVersion}}' 2>/dev/null | tr -d ' ')
    ok "Docker 引擎可用（Server $sv）"

    step "2/6" "生成环境文件"
    write_docker_env

    step "3/6" "构建并启动（首次构建较慢，请耐心）"
    info "docker compose -f docker/docker-compose.yml --env-file docker/.env.docker --profile infra --profile web up -d --build"
    docker compose -f docker/docker-compose.yml --env-file docker/.env.docker \
        --profile infra --profile web up -d --build 2>&1 | tee -a "$LOG_FILE"
    [ "${PIPESTATUS[0]}" -ne 0 ] && die "docker compose up 失败。详见 $LOG_FILE"
    ok "容器已创建"

    step "4/6" "等待 API 健康检查"
    info "http://127.0.0.1:$API_PORT/api/health （最多 8 分钟：首次要构建镜像 + 等数据库）"
    wait_http "http://127.0.0.1:$API_PORT/api/health" 480 && ok "API 已就绪" || \
        warn "API 未在 8 分钟内就绪，看日志: docker compose -f docker/docker-compose.yml logs -f api"

    step "5/6" "创建管理员账号（幂等）"
    local exec_args="-T -e ADMIN_EMAIL=$ADMIN_EMAIL"
    [ -n "$ADMIN_PASSWORD" ] && exec_args="$exec_args -e ADMIN_PASSWORD=$ADMIN_PASSWORD"
    docker compose -f docker/docker-compose.yml exec $exec_args api python deploy/seed_admin.py 2>&1 | tee -a "$LOG_FILE"
    ok "管理员账号: $ADMIN_EMAIL（随机密码见上方输出，只显示一次）"

    step "6/6" "完成"
    echo ""
    ok "站点:        http://0.0.0.0:$SITE_PORT/"
    ok "API 文档:    http://127.0.0.1:$API_PORT/docs"
    info "查看状态:    docker compose -f docker/docker-compose.yml ps"
    info "看日志:      docker compose -f docker/docker-compose.yml logs -f api"
    info "停止:        docker compose -f docker/docker-compose.yml stop"
    return 0
}

# ─────────────────────────── 主流程 ───────────────────────────
title "智标 一键安装 / 部署 (Linux)"
log "参数: Mode=$MODE ApiPort=$API_PORT SitePort=$SITE_PORT DevPort=$DEV_PORT DbName=$DB_NAME"

step "0/8" "检查目录（仓库根目录）"
if [ ! -f "$ROOT/pyproject.toml" ]; then
    die "当前目录不是仓库根目录: $ROOT
    判据: pyproject.toml、docker/docker-compose.yml 必须和本脚本在同一层。
    GitHub 的 Download ZIP 解压后常见会多套一层目录，请进入含 pyproject.toml 的那一层再运行。"
fi
ok "仓库根目录: $ROOT"

if [ -z "$LLM_API_KEY" ] && [ "$YES" -eq 0 ]; then
    echo ""
    echo "  提示: 模型类功能需要 LLM API Key（DeepSeek 等）。" >&2
    read -r -p "  现在输入 API Key（直接回车跳过，稍后可在 .env 里补）: " key_input
    [ -n "$key_input" ] && LLM_API_KEY="$(echo "$key_input" | tr -d '[:space:]')"
fi

case "$MODE" in
    docker)
        install_docker || die "Docker 方式不可用。可改用: ./install.sh --mode local" ;;
    local)
        install_local ;;
    auto)
        info "模式: 自动判断（Docker 可用则走 Docker，否则走本地开发）"
        if install_docker; then
            :
        else
            warn "自动改用方式二: 本地开发"
            install_local
        fi
        ;;
    *)
        die "未知 --mode: $MODE（可选 auto/docker/local）" ;;
esac

title "完成"
echo "  日志: $LOG_FILE"
[ "$YES" -eq 0 ] && echo ""
