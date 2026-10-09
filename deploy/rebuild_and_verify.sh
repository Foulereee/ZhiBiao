#!/bin/bash
# ============================================================================
# 智标（BidMaster-Pro）代码「固化 / 更新」脚本
#
# 作用：把 /opt/bidmaster 里的**当前源码**重新构建进 bidmaster-pro-api:latest，
#       并重建 api / celery-worker / celery-beat 三个容器。
#       构建或验证失败时**自动回滚**到构建前的镜像，业务不中断太久。
#
# 为什么需要它：镜像里烧的是构建当时的代码；只改了宿主源码 / 用 docker cp 进容器时，
#               一旦容器被 recreate（docker compose down/up），就会退回镜像里的旧代码。
#               跑一次本脚本，改动就进了镜像，之后怎么重建都不会回滚。
#
# 用法：
#   bash rebuild_and_verify.sh            # 构建 + 重建 + 验证（失败自动回滚）
#   bash rebuild_and_verify.sh --dry-run  # 只做前置检查并打印将执行的动作
#   bash rebuild_and_verify.sh --no-recreate   # 只构建打镜像，不动运行中的容器（零中断）
# ============================================================================
set -u

DRY=0; RECREATE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --no-recreate) RECREATE=0 ;;
    *) echo "未知参数: $1"; exit 2 ;;
  esac
  shift
done

SRC=/opt/bidmaster
COMPOSE_DIR=$SRC/docker
IMG=bidmaster-pro-api:latest
TS=$(date +%Y%m%d_%H%M%S)
SNAP=bidmaster-pro-api:rollback-$TS
KEY_FILES="services/main.py services/routers/generate.py services/routers/check.py services/format/skills/docx_format_skill.py"
run() { if [ "$DRY" = "1" ]; then echo "  [dry-run] $*"; else eval "$@"; fi; }

echo "════════ 代码固化 / 更新 $TS ════════"
echo "源码目录: $SRC"
echo "目标镜像: $IMG"

echo
echo "── 0/7 前置检查 ──"
[ -d "$COMPOSE_DIR" ] || { echo "  ✗ 找不到 $COMPOSE_DIR"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "  ✗ 缺少 docker compose v2"; exit 1; }
docker image inspect "$IMG" >/dev/null 2>&1 || { echo "  ✗ 本地没有 $IMG，请先 docker compose build"; exit 1; }
FREE=$(df -m "$SRC" | awk 'NR==2{print $4}')
echo "  ✓ 可用磁盘 ${FREE}MB"
[ "$FREE" -lt 4000 ] && echo "  ! 磁盘不足 4GB，构建可能失败"
echo "  ✓ compose 配置检查: $(cd "$COMPOSE_DIR" && docker compose config -q >/dev/null 2>&1 && echo 通过 || echo '有告警')"
echo "  当前运行镜像: $(docker inspect docker-api-1 --format '{{.Config.Image}}' 2>/dev/null)"

echo
echo "── 1/7 快照当前镜像（回滚用） ──"
run "docker tag '$IMG' '$SNAP'"
echo "  快照: $SNAP"
echo "  回滚命令（必要时手工执行）:"
echo "    docker tag $SNAP $IMG && cd $COMPOSE_DIR && docker compose up -d --no-deps api celery-worker celery-beat"

echo
echo "── 2/7 构建镜像（复用缓存，通常 30~90 秒） ──"
if [ "$DRY" = "1" ]; then
  echo "  [dry-run] cd $COMPOSE_DIR && docker compose build api"
else
  if ! (cd "$COMPOSE_DIR" && docker compose build api); then
    echo "  ✗ 构建失败：镜像 $IMG 未被替换，运行中的容器不受影响，无需回滚"
    exit 1
  fi
  echo "  ✓ 构建完成: $(docker image inspect "$IMG" --format '{{.Created}}')"
fi

if [ "$RECREATE" = "0" ]; then
  echo
  echo "── 已按 --no-recreate 结束（仅打镜像，容器仍跑旧层） ──"
  echo "   真正生效请执行: cd $COMPOSE_DIR && docker compose up -d --no-deps api celery-worker celery-beat"
  exit 0
fi

echo
echo "── 3/7 重建容器 ──"
run "cd '$COMPOSE_DIR' && docker compose up -d --no-deps api celery-worker celery-beat"

echo
echo "── 4/7 等待就绪 ──"
code=000
if [ "$DRY" != "1" ]; then
  for i in $(seq 1 60); do sleep 2; code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8000/api/health); [ "$code" = "200" ] && break; done
  echo "  /api/health = $code（$((i*2)) 秒）"
fi

echo
echo "── 5/7 验证 ──"
FAIL=0
if [ "$DRY" = "1" ]; then
  echo "  [dry-run] 跳过实际验证"
else
  home=$(curl -s -o /dev/null -w '%{http_code}' -m 10 http://127.0.0.1/)
  echo "  旧站首页 = $home（期望 200）"; [ "$home" = "200" ] || FAIL=1
  [ "$code" = "200" ] || { echo "  ✗ API 健康检查未通过"; FAIL=1; }
  # 关键：确认新镜像里真的是当前源码（而不是旧代码）
  for f in $KEY_FILES; do
    h=$(md5sum "$SRC/$f" | cut -d' ' -f1)
    c=$(docker exec docker-api-1 md5sum "/app/$f" 2>/dev/null | cut -d' ' -f1)
    if [ "$h" = "$c" ]; then echo "  ✓ 代码已固化 $f"; else echo "  ✗ 代码不一致 $f (宿主 $h / 容器 $c)"; FAIL=1; fi
  done
  login=$(curl -s -o /dev/null -w '%{http_code}' -m 10 -X POST http://127.0.0.1:8000/api/auth/login -H 'Content-Type: application/json' -d '{"email":"x@x.com","password":"x"}')
  echo "  登录接口 = $login（401=可达且拒绝错误凭证）"; [ "$login" = "401" ] || echo "  ! 登录接口返回 $login，请人工确认"
  paths=$(curl -s -m 20 http://127.0.0.1:8000/openapi.json | grep -o '"/api/[^"]*"' | sort -u | wc -l)
  echo "  OpenAPI 路径数 = $paths"; [ "$paths" -gt 50 ] || { echo "  ✗ 路由数量异常"; FAIL=1; }
  logs=$(docker logs docker-api-1 --since 3m 2>&1 | grep -ciE 'traceback|nameerror' || true)
  echo "  近 3 分钟日志异常数 = $logs"; [ "$logs" = "0" ] || { echo "  ! 日志里有异常，请查看 docker logs docker-api-1"; }
fi

echo
echo "── 6/7 结果 ──"
if [ "$FAIL" = "0" ]; then
  echo "  ✓ 固化成功：$IMG 现在包含 $SRC 的当前源码，之后 recreate 不会回滚"
  echo "    如需清理旧快照（保留最近 3 个）:"
  echo "      docker images --format '{{.Repository}}:{{.Tag}}' | grep '^bidmaster-pro-api:rollback-' | sort | head -n -3 | xargs -r docker rmi"
else
  echo "  ✗ 验证未通过，自动回滚到 $SNAP"
  run "docker tag '$SNAP' '$IMG'"
  run "cd '$COMPOSE_DIR' && docker compose up -d --no-deps api celery-worker celery-beat"
  if [ "$DRY" != "1" ]; then
    for i in $(seq 1 45); do sleep 2; c2=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:8000/api/health); [ "$c2" = "200" ] && break; done
    echo "  回滚后 /api/health = $c2"
  fi
  exit 1
fi

echo
echo "── 7/7 善后 ──"
echo "  - 浏览器 Ctrl+F5 刷新；本轮重启会清空内存登录态，请重新登录一次"
echo "  - celery 容器同样已用新镜像重建，定时任务无需干预"