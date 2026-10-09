#!/bin/bash
# ============================================================================
# 智标（BidMaster-Pro）新主机「导入」脚本 —— 从迁移包一键部署出一套完整系统
#
# 两种模式：
#   迁移模式（默认）：新的 PostgreSQL 实例 + 把历史数据（库 + 业务文件）一起搬过来
#   全新模式（--fresh）：新的 PostgreSQL 实例 + 空库（自动建表）+ 新建管理员账号，不带历史数据
#
# 用法（在**新主机**上执行）：
#   bash import_all.sh --bundle migrate_xxx.tar.gz --dry-run            # 先预演
#   bash import_all.sh --bundle migrate_xxx.tar.gz                     # 迁移模式
#   bash import_all.sh --bundle migrate_xxx.tar.gz \
#        --rotate-db-password --origins http://新主机IP                # 迁移模式 + 换数据库密码
#   bash import_all.sh --bundle migrate_xxx.tar.gz --fresh \
#        --admin-email me@example.com --admin-password '强密码'        # 全新空库模式
#
# 前置要求：
#   Linux + Docker 24+ 与 docker compose v2；建议 ≥2 核 4GB 内存、≥20GB 空闲磁盘
#   对外需要 80（主入口）与 3000（备用）端口；80 端口不要被宿主 nginx/apache 占用
# ============================================================================
set -u

BUNDLE=""; IMAGE=""; BASE=/opt; DRY=0; FORCE=0; SKIP_DATA=0; FRESH=0
ADMIN_EMAIL=""; ADMIN_PASSWORD=""; ROTATE_DB=0; NEW_DB_PASS=""; ORIGINS=""
declare -a SETS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --bundle) shift; BUNDLE="${1:-}" ;;
    --image) shift; IMAGE="${1:-}" ;;
    --dir) shift; BASE="${1:-/opt}" ;;
    --fresh) FRESH=1 ;;
    --skip-data) SKIP_DATA=1 ;;
    --admin-email) shift; ADMIN_EMAIL="${1:-}" ;;
    --admin-password) shift; ADMIN_PASSWORD="${1:-}" ;;
    --rotate-db-password)
      ROTATE_DB=1
      if [ $# -gt 1 ] && [ "${2:0:2}" != "--" ]; then shift; NEW_DB_PASS="${1:-}"; fi ;;
    --origins) shift; ORIGINS="${1:-}" ;;
    --set) shift; SETS+=("${1:-}") ;;
    --dry-run) DRY=1 ;;
    --force) FORCE=1 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
  shift
done
[ -z "$BUNDLE" ] && { sed -n '2,20p' "$0"; exit 2; }
[ -f "$BUNDLE" ] || { echo "找不到迁移包: $BUNDLE"; exit 2; }
[ "$FRESH" = "1" ] && SKIP_DATA=0

SRC=$BASE/bidmaster
WEB=$BASE/bidmaster-web
NET=bidmaster-net
API=docker-api-1
PG=docker-postgres-1
run() { if [ "$DRY" = "1" ]; then echo "    [dry-run] $*"; else eval "$@"; fi; }

echo "════════ 智标新主机导入 ════════"
echo "迁移包: $BUNDLE"
echo "安装目录: $SRC"
echo "模式: $([ "$FRESH" = "1" ] && echo '全新空库（不带历史数据）' || echo '数据迁移（带历史数据）')$([ "$DRY" = "1" ] && echo ' / dry-run')"

echo
echo "── 0/10 前置检查 ──"
command -v docker >/dev/null || { echo "  ✗ 未安装 docker"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "  ✗ 缺少 docker compose v2"; exit 1; }
echo "  ✓ docker $(docker version --format '{{.Server.Version}}') / compose $(docker compose version --short)"
if [ -d "$SRC" ] && [ -n "$(ls -A "$SRC" 2>/dev/null)" ] && [ "$FORCE" != "1" ]; then
  echo "  ✗ $SRC 已存在且非空。确认覆盖请加 --force（会先备份为 ${SRC}.bak.<时间戳>）"; exit 1
fi
DFT=$(df -m "$BASE" 2>/dev/null | awk 'NR==2{print $4}')
[ -z "$DFT" ] && DFT=$(df -m / 2>/dev/null | awk 'NR==2{print $4}')
FREE=${DFT:-0}
if [ -d "$BASE" ]; then
  echo "  ✓ $BASE 可用空间 ${FREE}MB"
else
  echo "  ✓ 可用空间 ${FREE}MB（$BASE 尚未创建，按 / 分区估算）"
fi
[ "${FREE:-0}" -lt 8000 ] 2>/dev/null && echo "  ! 警告：可用空间不足 8GB，可能放不下数据卷与镜像"
if ss -ltnp 2>/dev/null | grep -q ':80 '; then
  echo "  ! 警告：80 端口已被占用（$(ss -ltnp | grep ':80 ' | head -1 | tr -s ' ')），站点容器可能起不来"
fi
[ "$ROTATE_DB" = "1" ] && echo "  ✓ 将更换数据库密码（POSTGRES_PASSWORD）"
[ "$ORIGINS" != "" ] && echo "  ✓ 将写入 ALLOWED_ORIGINS=$ORIGINS"

echo
echo "── 1/10 解包与校验 ──"
# 解包与 SHA 校验都是只读操作（只落 /tmp），因此 dry-run 下也真实执行，让预演结果可信
WORK=$(mktemp -d /tmp/bmp_import_XXXX)
tar -xzf "$BUNDLE" -C "$WORK" || { echo "  ✗ 解包失败（包不完整？）"; exit 1; }
D=$(ls -d "$WORK"/migrate_* 2>/dev/null | head -1)
[ -z "$D" ] && { echo "  ✗ 包结构异常（未找到 migrate_* 目录）"; exit 1; }
( cd "$D" && sha256sum -c SHA256SUMS >/dev/null 2>&1 && echo "  ✓ SHA256 校验通过" || echo "  ! SHA256 校验未通过（包可能损坏，谨慎继续）" )
echo "  解包目录: $D"

echo
echo "── 2/10 后端源码与配置 ──"
if [ -d "$SRC" ] && [ "$FORCE" = "1" ]; then
  run "mv '$SRC' '${SRC}.bak.$(date +%Y%m%d_%H%M%S)'"
fi
run "mkdir -p '$SRC'"
run "tar -xzf '$D/backend_src.tgz' -C '$SRC'"
run "mkdir -p '$SRC/uploads' '$SRC/projects' '$SRC/chroma_db'"
run "cp -a '$D/_opt_bidmaster_.env' '$SRC/.env'"
run "cp -a '$D/_opt_bidmaster_docker_docker-compose.yml' '$SRC/docker/docker-compose.yml'"
run "ln -sf ../.env '$SRC/docker/.env'"
run "chmod 600 '$SRC/.env'"
echo "  源码、compose、.env（权限 600）、docker/.env 软链就位"

echo
echo "── 3/10 .env 调整（新主机特有） ──"
if [ "$DRY" = "1" ]; then
  echo "    [dry-run] 修改 $SRC/.env：$([ "$ROTATE_DB" = 1 ] && echo '换数据库密码 ')$([ -n "$ORIGINS" ] && echo "ALLOWED_ORIGINS=$ORIGINS ")$([ ${#SETS[@]} -gt 0 ] && echo "自定义 ${#SETS[@]} 项")"
else
  if [ "$ROTATE_DB" = "1" ]; then
    [ -z "$NEW_DB_PASS" ] && NEW_DB_PASS=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 24)
    sed -i "s#^POSTGRES_PASSWORD=.*#POSTGRES_PASSWORD=${NEW_DB_PASS}#" "$SRC/.env"
    echo "  ✓ 已设置新的 POSTGRES_PASSWORD（长度 ${#NEW_DB_PASS}）"
    echo "    ★ 新密码: $NEW_DB_PASS   （请立即保存；它同时被 postgres 容器与 api 使用）"
  fi
  [ -n "$ORIGINS" ] && sed -i "s#^ALLOWED_ORIGINS=.*#ALLOWED_ORIGINS=${ORIGINS}#" "$SRC/.env" && echo "  ✓ ALLOWED_ORIGINS=$ORIGINS"
  for kv in ${SETS[@]+"${SETS[@]}"}; do
    k=${kv%%=*}; v=${kv#*=}
    if grep -q "^${k}=" "$SRC/.env"; then
      sed -i "s#^${k}=.*#${k}=${v}#" "$SRC/.env"; echo "  ✓ ${k}=${v}"
    else
      echo "${k}=${v}" >> "$SRC/.env"; echo "  ✓ 新增 ${k}=${v}"
    fi
  done
  echo "  提醒：容器里 BMP_DATABASE_URL 由 compose 用 POSTGRES_* 拼出来；只改库名/密码时改 .env 即可，"
  echo "        但若要指向【另一台已有数据库】，必须同时改 .env 并给 api 显式设置 BMP_DATABASE_URL。"
fi

echo
echo "── 4/10 前端与运维脚本 ──"
run "mkdir -p '$WEB'"
run "tar -xzf '$D/frontend_dist_live.tgz' -C '$WEB'"
run "cp -a '$D/web_nginx.conf' '$WEB/nginx.conf'"
[ -f "$D/restore_web_container.sh" ] && run "cp -a '$D/restore_web_container.sh' '$WEB/restore_web_container.sh'"
if [ -f "$D/ops_scripts.tgz" ]; then
  run "tar -xzf '$D/ops_scripts.tgz' -C '$WEB'"
  run "chmod +x '$WEB'/*.sh"
  run "mkdir -p /opt/rollback_snapshots"
  if [ "$DRY" = "1" ]; then
    echo "  将安装运维脚本: $(tar -tzf "$D/ops_scripts.tgz" | tr '\n' ' ')"
  else
    echo "  运维脚本已就位：$(cd "$WEB" && ls *.sh 2>/dev/null | tr '\n' ' ')"
  fi
fi
if [ "$DRY" != "1" ]; then
  echo "  前端 bundle: $(grep -o 'assets/index-[A-Za-z0-9_-]*\.js' "$WEB/dist/index.html" 2>/dev/null | head -1)"
fi

echo
echo "── 5/10 准备 api 镜像 ──"
if [ -n "$IMAGE" ]; then
  run "docker load -i '$IMAGE'"
  echo "  已 load 镜像（无需联网构建）"
else
  echo "  未提供镜像包，用源码构建（需要能访问 aliyun 镜像源；首次约 3~10 分钟）"
  run "cd '$SRC/docker' && docker compose build api"
fi

echo
echo "── 6/10 启动新的数据库与缓存 ──"
run "cd '$SRC/docker' && docker compose --profile infra up -d postgres redis"
if [ "$DRY" != "1" ]; then
  st=starting
  for i in $(seq 1 60); do
    st=$(docker inspect $PG --format '{{.State.Health.Status}}' 2>/dev/null || echo starting)
    [ "$st" = "healthy" ] && break
    sleep 2
  done
  echo "  postgres 状态: $st（$((i*2)) 秒）"
fi

echo
echo "── 7/10 业务数据 ──"
if [ "$FRESH" = "1" ]; then
  echo "  全新空库模式：不灌历史数据（init_pg.sql + API 启动时 create_all 自动建表）"
elif [ "$SKIP_DATA" = "1" ]; then
  echo "  已按 --skip-data 跳过数据恢复"
else
  HELPER=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^(postgres|pgvector/pgvector)' | head -1)
  [ -z "$HELPER" ] && HELPER=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^(python|alpine|nginx)' | head -1)
  # 卷名前缀 = compose 项目名 = compose 文件所在目录名（本布局里固定是 docker）
  PROJ=$(basename "$SRC/docker")
  echo "  compose 项目名（决定卷名前缀）: $PROJ"
  for v in projects uploads chroma miniodata; do
    T="$D/volume_$v.tgz"
    [ -f "$T" ] || { echo "  volume_$v 无备份，跳过"; continue; }
    run "docker volume create ${PROJ}_$v >/dev/null"
    if [ "$DRY" = "1" ]; then
      echo "    [dry-run] 把 $(basename "$T") 解到卷 ${PROJ}_$v"
    else
      docker run --rm -v "${PROJ}_$v":/data -v "$D":/src:ro "${HELPER:-busybox}" \
        sh -c "tar -xzf /src/volume_$v.tgz -C /data" && \
        echo "  ✓ ${PROJ}_$v 已恢复（文件 $(docker run --rm -v ${PROJ}_$v:/d ${HELPER:-busybox} sh -c 'find /d -type f | wc -l')）"
    fi
  done
  PGDB=$(grep -E '^POSTGRES_DB=' "$D/_opt_bidmaster_.env" 2>/dev/null | cut -d= -f2); PGDB=${PGDB:-bidmaster}
  run "docker exec -i $PG psql -U postgres -d '$PGDB' -c 'DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;'"
  run "docker exec -i $PG psql -U postgres -d '$PGDB' -c 'CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";'"
  if [ "$DRY" != "1" ]; then
    docker exec -i $PG psql -U postgres -d "$PGDB" < "$D/db_$PGDB.sql" >/tmp/bmp_restore.log 2>&1 \
      && echo "  ✓ 数据库 $PGDB 已恢复（日志 /tmp/bmp_restore.log）" \
      || { echo "  ✗ 数据库恢复报错，末尾日志："; tail -5 /tmp/bmp_restore.log; }
    if [ -f "$D/expected_counts.txt" ]; then
      echo "  行数核对（期望 vs 实际）:"
      while read -r tbl want; do
        [ -z "$tbl" ] && continue
        got=$(docker exec $PG psql -U postgres -d "$PGDB" -tAc "select count(*) from $tbl" 2>/dev/null || echo ERR)
        flag="✓"; [ "$got" != "$want" ] && flag="✗"
        printf "    %-16s %-8s %-8s %s\n" "$tbl" "$want" "$got" "$flag"
      done < "$D/expected_counts.txt"
    fi
  fi
fi

echo
echo "── 8/10 启动后端与定时任务容器 ──"
run "cd '$SRC/docker' && docker compose up -d --no-deps api celery-worker celery-beat"
if [ "$DRY" != "1" ]; then
  code=000
  for i in $(seq 1 60); do sleep 2; code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8000/api/health); [ "$code" = "200" ] && break; done
  echo "  /api/health = $code（$((i*2)) 秒）"
fi

echo
echo "── 9/10 全新空库模式：创建管理员账号 ──"
if [ "$FRESH" = "1" ]; then
  if [ -f "$D/seed_admin.py" ]; then
    run "docker cp '$D/seed_admin.py' $API:/tmp/seed_admin.py"
    if [ "$DRY" = "1" ]; then
      echo "    [dry-run] 在 $API 内执行 seed_admin.py（ADMIN_EMAIL=${ADMIN_EMAIL:-admin@bidmaster.pro}）"
    else
      docker exec -e ADMIN_EMAIL="$ADMIN_EMAIL" -e ADMIN_PASSWORD="$ADMIN_PASSWORD" $API python /tmp/seed_admin.py 2>&1 | sed 's/^/    /'
      docker exec -u 0 $API rm -f /tmp/seed_admin.py
      echo "    （若上面没打印随机密码，说明你已用 --admin-password 指定）"
    fi
  else
    echo "  ! 包内没有 seed_admin.py，无法自动建管理员；请手工执行（见《全新主机部署手册》）"
  fi
else
  echo "  非全新模式：用户/角色随数据库一起迁移，无需建号"
fi

echo
echo "── 10/10 起 80 端口站点 + 安装定时任务 ──"
run "bash '$WEB/restore_web_container.sh'"
if [ "$DRY" != "1" ]; then
  sleep 3
  echo "  首页 http://127.0.0.1/ = $(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1/)"
  echo "  反代 /api/health = $(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1/api/health)"
  echo "  未授权访问 /api/format/templates = $(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1/api/format/templates)（应 401）"
  if [ -f "$WEB/backup_full.sh" ]; then
    CRON_BAK=/tmp/crontab.bak.$(date +%Y%m%d_%H%M%S)
    crontab -l > "$CRON_BAK" 2>/dev/null || true
    ( crontab -l 2>/dev/null | grep -v 'bidmaster-web/fe_watchdog.sh' | grep -v 'bidmaster-web/backup_full.sh';
      echo '*/10 * * * * /bin/bash '"$WEB"'/fe_watchdog.sh';
      echo '30 3 * * * /bin/bash '"$WEB"'/backup_full.sh >> /var/log/bidmaster_backup.log 2>&1' ) | crontab -
    echo "  ✓ 定时任务已安装（原 crontab 备份在 $CRON_BAK）："
    crontab -l | sed 's/^/      /'
  fi
fi

echo
echo "════════ 导入完成，请人工确认 ════════"
rm -rf "$WORK" 2>/dev/null
cat <<EOT
必须检查：
  1) 浏览器打开 http://<新主机IP>/ ，$( [ "$FRESH" = "1" ] && echo '用第 9 步创建的管理员账号登录' || echo '用原账号登录（用户随数据库迁移）' )
  2) 打开一个项目 → 导出 Word（带排版）：封面 22/36pt 居中、页脚「第 X 页」、正文首行缩进 2 字符、目录点线对齐
  3) 上传一份招标文件 → 解析 → 全量检查（验证数据卷权限与 LLM 密钥）
  4) 确认 /opt/backups 会按 03:30 自动产生备份：ls -la /opt/backups
  5) 域名/HTTPS：可在前面再加一层宿主 nginx 或云负载；不要改 bidmaster-net 网络名（nginx 里写死 http://api:8000）
注意事项：
  - 迁移包内含明文密钥，确认无误后删除包与包内 .env，或轮换密钥
  - UVICORN_WORKERS 保持 1（任务与登录态在进程内存，多 worker 会状态不一致）
  - 只搬代码不搬库 = 空系统；"全新空库"模式需要拿第 9 步的管理员账号登录
EOT