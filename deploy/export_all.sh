#!/bin/bash
# ============================================================================
# 智标（BidMaster-Pro）源服务器「导出」脚本 —— 生成一台新服务器可用的迁移包
#
# 用法（在**当前生产服务器**上执行）：
#   bash export_all.sh                     # 默认导出到 /opt/backups/migrate_<时间戳>
#   bash export_all.sh --with-image        # 额外把 api 镜像打成 tar.gz（新服务器无需联网构建）
#   bash export_all.sh --out /data/migrate # 指定输出根目录
#
# 产物：
#   <out>/migrate_<ts>/            明细目录（db 备份 / 源码 / 前端产物 / 数据卷 / 配置 / 清单）
#   <out>/migrate_<ts>.tar.gz      单文件迁移包（拷到新服务器解包即可）
#   <out>/api_image_<ts>.tar.gz    仅 --with-image 时生成（约 0.5~1.4GB）
#
# 特性：全程只读，不改动任何生产数据；pg_dump 用 --clean --if-exists，恢复到已建表的库上不会冲突。
# ============================================================================
set -u

WITH_IMAGE=0
OUT_ROOT=/opt/backups
while [ $# -gt 0 ]; do
  case "$1" in
    --with-image) WITH_IMAGE=1 ;;
    --out) shift; OUT_ROOT="${1:-/opt/backups}" ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
  shift
done

TS=$(date +%Y%m%d_%H%M%S)
OUT="$OUT_ROOT/migrate_$TS"
PG_C=docker-postgres-1
mkdir -p "$OUT"

echo "════════ 智标迁移包导出 $TS ════════"
echo "输出目录: $OUT"

echo
echo "── 1/10 数据库（在线 pg_dump，不锁业务） ──"
# 从容器环境变量取真实库名/用户，避免写死
PGDB=$(docker exec $PG_C sh -c 'echo ${POSTGRES_DB:-bidmaster}')
PGUSER=$(docker exec $PG_C sh -c 'echo ${POSTGRES_USER:-postgres}')
echo "  库=$PGDB 用户=$PGUSER"
docker exec $PG_C sh -c "pg_dump -U \"$PGUSER\" --clean --if-exists --no-owner -d \"$PGDB\"" > "$OUT/db_$PGDB.sql" 2>"$OUT/db_dump.err"
docker exec $PG_C sh -c "pg_dumpall -U \"$PGUSER\" --roles-only" > "$OUT/db_roles.sql" 2>/dev/null
printf "  db_%s.sql %s 字节（CREATE TABLE/COPY 语句 %s 条）\n" "$PGDB" "$(stat -c%s "$OUT/db_$PGDB.sql")" "$(grep -c 'CREATE TABLE\|COPY ' "$OUT/db_$PGDB.sql" 2>/dev/null)"
[ -s "$OUT/db_dump.err" ] && echo "  pg_dump stderr: $(head -3 "$OUT/db_dump.err")"

echo
echo "── 2/10 后端源码（含本轮全部修复） ──"
tar -czf "$OUT/backend_src.tgz" -C /opt/bidmaster \
  --exclude='*.sql' --exclude='.backup*' --exclude='backup_*' \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.verify' --exclude='uploads' --exclude='projects' \
  services core db docker skills templates packages deploy alembic.ini pyproject.toml README.md 2>/dev/null
echo "  backend_src.tgz $(stat -c%s "$OUT/backend_src.tgz") 字节"

echo
echo "── 3/10 前端（80 端口线上产物 + 源码 + nginx 配置） ──"
tar -czf "$OUT/frontend_dist_live.tgz" -C /opt/bidmaster-web dist 2>/dev/null
echo "  frontend_dist_live.tgz $(stat -c%s "$OUT/frontend_dist_live.tgz") 字节  bundle=$(grep -o 'assets/index-[A-Za-z0-9_-]*\.js' /opt/bidmaster-web/dist/index.html | head -1)"
cp -a /opt/bidmaster-web/nginx.conf "$OUT/web_nginx.conf" 2>/dev/null
tar -czf "$OUT/frontend_src.tgz" -C /opt/bidmaster packages/desktop/renderer 2>/dev/null && \
  echo "  frontend_src.tgz $(stat -c%s "$OUT/frontend_src.tgz") 字节（前端源码，用于日后改界面）"

echo
echo "── 3b/10 运维脚本与定时任务（新主机要自己有一份） ──"
OPS=""
for f in backup_full.sh deploy_guarded.sh fe_watchdog.sh; do
  [ -f "/opt/bidmaster-web/$f" ] && OPS="$OPS $f"
done
if [ -n "$OPS" ]; then
  tar -czf "$OUT/ops_scripts.tgz" -C /opt/bidmaster-web $OPS 2>/dev/null
  echo "  ops_scripts.tgz $(stat -c%s "$OUT/ops_scripts.tgz") 字节（$OPS）"
fi
crontab -l > "$OUT/crontab.txt" 2>/dev/null && echo "  crontab.txt 已记录（$(wc -l < "$OUT/crontab.txt") 条）"
# 全新空库部署需要的建号脚本（随包走，import_all.sh --fresh 会用到）
[ -f /opt/bidmaster/deploy/seed_admin.py ] && cp -a /opt/bidmaster/deploy/seed_admin.py "$OUT/seed_admin.py" && echo "  seed_admin.py 已入包（--fresh 模式建管理员用）"
echo "  说明：新主机上这些定时任务是【迁移后需要重新安装】的，import_all.sh 会自动装"

echo
echo "── 4/10 配置与密钥 ──"
for f in /opt/bidmaster/.env /opt/bidmaster/docker/docker-compose.yml /opt/bidmaster/alembic.ini; do
  [ -f "$f" ] && cp -a "$f" "$OUT/$(echo "$f" | tr '/' '_')" && echo "  + $f"
done
if [ -L /opt/bidmaster/docker/.env ] || [ -f /opt/bidmaster/docker/.env ]; then
  echo "  注意：docker/.env 是 -> ../.env 的软链（恢复脚本会自动重建）"
fi

echo
echo "── 5/10 业务数据卷（projects / uploads / chroma / minio） ──"
for v in projects uploads chroma miniodata; do
  D=/var/lib/docker/volumes/docker_$v/_data
  if [ -d "$D" ]; then
    tar -czf "$OUT/volume_$v.tgz" -C "$D" . 2>/dev/null
    printf "  volume_%-10s %9s 字节（原始 %s，文件数 %s）\n" "$v" "$(stat -c%s "$OUT/volume_$v.tgz")" "$(du -sh "$D" 2>/dev/null | cut -f1)" "$(find "$D" -type f | wc -l)"
  else
    echo "  volume_$v 不存在，跳过"
  fi
done

echo
echo "── 6/10 容器/镜像清单与精确重建信息 ──"
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' > "$OUT/containers.txt"
docker images --format '{{.Repository}}:{{.Tag}}\t{{.CreatedAt}}\t{{.Size}}' > "$OUT/images.txt"
docker inspect bidmaster-web docker-api-1 docker-postgres-1 docker-redis-1 > "$OUT/containers_inspect.json" 2>/dev/null
echo "  containers.txt / images.txt / containers_inspect.json"
echo "  80 端口站点容器（非 compose 管理，需用 docker run 重建）:"
docker inspect bidmaster-web --format '    镜像={{.Config.Image}} 端口={{.HostConfig.PortBindings}} 网络={{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' 2>/dev/null

echo
echo "── 7/10 生成新服务器重建 80 端口站点的脚本 ──"
cat > "$OUT/restore_web_container.sh" <<'EOS'
#!/bin/bash
# 在新服务器上重建 80（+3000）端口的 nginx 站点容器。
# 前提：/opt/bidmaster-web/{dist,nginx.conf} 已就位；bidmaster-net 网络已存在（compose 起过 api 后即有）
set -eu
NET=bidmaster-net
docker network inspect "$NET" >/dev/null 2>&1 || { echo "网络 $NET 不存在：请先起 api（cd /opt/bidmaster/docker && docker compose up -d api）"; exit 1; }
docker rm -f bidmaster-web >/dev/null 2>&1 || true
docker run -d --name bidmaster-web --restart unless-stopped \
  --network "$NET" \
  -p 80:80 -p 3000:80 \
  --mount type=bind,src=/opt/bidmaster-web/dist,dst=/usr/share/nginx/html,readonly \
  --mount type=bind,src=/opt/bidmaster-web/nginx.conf,dst=/etc/nginx/conf.d/default.conf,readonly \
  nginx:1.27-alpine
sleep 3
echo "首页 http=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1/)"
echo "API  http=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1/api/health)"
EOS
chmod +x "$OUT/restore_web_container.sh"
echo "  restore_web_container.sh 已生成"

echo
echo "── 8/10 可选：打包 api 镜像（新服务器可直接 load，不用联网构建） ──"
if [ "$WITH_IMAGE" = "1" ]; then
  docker save bidmaster-pro-api:latest | gzip > "$OUT_ROOT/api_image_$TS.tar.gz"
  echo "  api_image_$TS.tar.gz $(stat -c%s "$OUT_ROOT/api_image_$TS.tar.gz") 字节"
else
  echo "  已跳过（加 --with-image 可包含；不包含时新服务器用 docker compose build 重建，需能访问 aliyun 镜像源）"
fi

echo
echo "── 9/10 记录期望行数（新服务器导入后自动核对） ──"
: > "$OUT/expected_counts.txt"
for t in users projects chapters documents check_reports analyses outlines; do
  n=$(docker exec $PG_C psql -U "$PGUSER" -d "$PGDB" -tAc "select count(*) from $t" 2>/dev/null)
  if [ -n "$n" ]; then echo "$t $n" >> "$OUT/expected_counts.txt"; printf "  %-16s %s\n" "$t" "$n"; fi
done

echo
echo "── 10/10 校验与打包 ──"
# .env 含明文 LLM/向量模型/数据库密钥：收紧权限并留下提醒
chmod 600 "$OUT/_opt_bidmaster_.env" 2>/dev/null
cat > "$OUT/安全提醒.txt" <<'EOT'
本包内含 _opt_bidmaster_.env（明文 LLM / 向量模型 / 数据库密钥）。
传输请走 scp 等加密通道；到新服务器后立刻 chmod 600；
确认新环境正常后，删除包内 .env 与迁移包，或轮换一次密钥
（改 /opt/bidmaster/.env 后：cd /opt/bidmaster/docker && docker compose up -d --no-deps --force-recreate api celery-worker celery-beat）。
EOT
( cd "$OUT" && sha256sum ./* > SHA256SUMS 2>/dev/null )
tar -czf "$OUT_ROOT/migrate_$TS.tar.gz" -C "$OUT_ROOT" "migrate_$TS"
chmod 600 "$OUT_ROOT/migrate_$TS.tar.gz" 2>/dev/null
echo "  目录体积: $(du -sh "$OUT" | cut -f1)"
echo "  单文件包: $OUT_ROOT/migrate_$TS.tar.gz  $(stat -c%s "$OUT_ROOT/migrate_$TS.tar.gz") 字节"
echo
echo "  包内清单:"
ls -la --time-style=long-iso "$OUT"
echo
echo "════════ 导出完成 ════════"
echo "把这两个文件拷到新服务器（scp / U 盘皆可）："
echo "  $OUT_ROOT/migrate_$TS.tar.gz"
[ "$WITH_IMAGE" = "1" ] && echo "  $OUT_ROOT/api_image_$TS.tar.gz"
echo "新服务器上执行： bash import_all.sh --bundle migrate_$TS.tar.gz [--image api_image_$TS.tar.gz]"