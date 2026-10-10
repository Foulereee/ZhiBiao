<#
    智标（ZhiBiao）停止脚本

    用法：
      .\stop.ps1                     # 停止本地方式二启动的 API 与前端（按端口定位进程）
      .\stop.ps1 -WithPg             # 连便携 PostgreSQL 一起停
      .\stop.ps1 -Docker             # 停止 Docker 方式一（compose stop，容器与数据卷都保留）
      .\stop.ps1 -Docker -Remove     # 删除容器与网络（数据卷仍保留；加 -Volumes 才会删数据）
      .\stop.ps1 -Docker -Remove -Volumes   # ⚠️ 连数据卷一起删 = 删库
#>
[CmdletBinding()]
param(
    [int]$ApiPort = 8000,
    [int]$DevPort = 15168,
    [switch]$WithPg,
    [switch]$Docker,
    [switch]$Remove,
    [switch]$Volumes
)

$Root = $PSScriptRoot
if (-not $Root) { $Root = (Get-Location).Path }
try { Set-Location $Root } catch { }

function Ok([string]$t) { Write-Host "    [OK] $t" -ForegroundColor Green }
function Info([string]$t) { Write-Host "    [..] $t" -ForegroundColor Gray }
function Warn([string]$t) { Write-Host "    [!]  $t" -ForegroundColor Yellow }

function Stop-ByPort([int]$port, [string]$what) {
    $conns = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($conns.Count -eq 0) { Info "$what（端口 $port）本来就没在运行"; return }
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
        $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($p) {
            Info "停止 $what：$($p.ProcessName) (PID $procId)"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 2
    if (@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).Count -eq 0) {
        Ok "$what 已停止"
    } else {
        Warn "$what 仍在监听 $port，可手动结束进程"
    }
}

if ($Docker) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Warn '未找到 docker 命令'; exit 1 }
    $file = 'docker/docker-compose.yml'
    if ($Remove) {
        $a = @('compose', '-f', $file, 'down')
        if ($Volumes) { $a += '-v'; Warn '⚠️ 将同时删除数据卷（数据库数据会丢）' }
        Info ('docker ' + ($a -join ' '))
        & docker @a
    } else {
        $a = @('compose', '-f', $file, 'stop')
        Info ('docker ' + ($a -join ' '))
        & docker @a
    }
    if ($LASTEXITCODE -eq 0) { Ok 'Docker 服务处理完成' } else { Warn "docker 返回 $LASTEXITCODE" }
    exit 0
}

Write-Host ''
Write-Host '  停止本地服务（方式二）' -ForegroundColor Cyan
Stop-ByPort $ApiPort 'API（uvicorn）'
Stop-ByPort $DevPort '前端（vite dev）'

if ($WithPg) {
    $bat = Join-Path $Root 'stop-postgres.bat'
    if (Test-Path $bat) {
        Info '停止便携 PostgreSQL（stop-postgres.bat）…'
        & cmd.exe /c "`"$bat`""
    } elseif (Get-Command pg_ctl -ErrorAction SilentlyContinue) {
        & pg_ctl -D (Join-Path $Root '.pgsql\data') stop
    } else {
        Warn '没找到 stop-postgres.bat / pg_ctl，PostgreSQL 请自行停止'
    }
}

Write-Host ''
Ok '处理完成（Docker 容器请用：.\stop.ps1 -Docker）'