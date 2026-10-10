<#
    智标（ZhiBiao）一键安装 / 部署脚本 —— Windows PowerShell

    自动判断走哪条路：
      * Docker 引擎可用  -> 方式一：Docker 全量部署（含 PostgreSQL/Redis/MinIO/站点）
      * 否则              -> 方式二：本地开发（自带便携 PostgreSQL 时优先用它）

    常用用法：
      .\install.ps1                                   # 自动判断
      .\install.ps1 -Mode local                       # 强制本地开发
      .\install.ps1 -Mode docker                      # 强制 Docker
      .\install.ps1 -LlmApiKey sk-xxx -Yes            # 非交互，顺便写入 Key
      .\install.ps1 -AdminEmail me@x.com -AdminPassword '强密码'
      .\install.ps1 -SkipFrontend -NoStart            # 只准备环境，不装前端、不起服务

    说明：
      * 可重复执行（幂等）。已存在的 .env / docker\.env.docker 默认保留，加 -Force 才重建（会先备份）。
      * 数据库表用 db/init_pg.sql（内部全是 IF NOT EXISTS），重复执行安全。
      * 全程日志写在 logs\install-*.log。
#>
[CmdletBinding()]
param(
    [ValidateSet('auto', 'docker', 'local')][string]$Mode = 'auto',
    [string]$LlmApiKey = '',
    [string]$LlmApiBase = '',
    [string]$AdminEmail = 'admin@bidmaster.pro',
    [string]$AdminPassword = '',
    [string]$DbName = 'bidmaster',
    [string]$PgUser = 'postgres',
    [string]$PgPassword = 'postgres',
    [int]$PgPort = 5432,
    [int]$ApiPort = 8000,
    [int]$SitePort = 8080,
    [int]$DevPort = 15168,
    [string]$PgRoot = '',
    [switch]$SkipFrontend,
    [switch]$NoStart,
    [switch]$Force,
    [switch]$Yes
)

$ErrorActionPreference = 'Continue'
$script:Root = $PSScriptRoot
if (-not $script:Root) { $script:Root = (Get-Location).Path }
try { Set-Location $script:Root } catch { }

# ─────────────────────────── 输出与日志 ───────────────────────────
$script:LogDir = Join-Path $script:Root 'logs'
if (-not (Test-Path $script:LogDir)) { New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null }
$script:LogFile = Join-Path $script:LogDir ('install-{0}.log' -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

function Write-Log([string]$t) {
    try { Add-Content -Path $script:LogFile -Value ('[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $t) -Encoding UTF8 } catch { }
}
function Title([string]$t) {
    Write-Host ''
    Write-Host ('=' * 72) -ForegroundColor DarkGray
    Write-Host "  $t" -ForegroundColor White
    Write-Host ('=' * 72) -ForegroundColor DarkGray
    Write-Log "TITLE $t"
}
function Step([string]$n, [string]$t) { Write-Host ''; Write-Host "[$n] $t" -ForegroundColor Cyan; Write-Log "STEP $n $t" }
function Ok([string]$t) { Write-Host "    [OK] $t" -ForegroundColor Green; Write-Log "OK   $t" }
function Info([string]$t) { Write-Host "    [..] $t" -ForegroundColor Gray; Write-Log "INFO $t" }
function Warn([string]$t) { Write-Host "    [!]  $t" -ForegroundColor Yellow; Write-Log "WARN $t" }
function Die([string]$t) {
    Write-Host ''
    Write-Host "    [X]  $t" -ForegroundColor Red
    Write-Host ''
    Write-Host "    日志：$script:LogFile" -ForegroundColor DarkGray
    Write-Log "FATAL $t"
    exit 1
}

# ─────────────────────────── 小工具 ───────────────────────────
function Have([string]$cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Test-Port([string]$h, [int]$p) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $iar = $c.BeginConnect($h, $p, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne(900)) { $c.Close(); return $false }
        $c.EndConnect($iar); $c.Close(); return $true
    } catch { return $false }
}

function Wait-Http([string]$url, [int]$timeoutSec, [string]$what) {
    $deadline = (Get-Date).AddSeconds($timeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 6
            if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400) { return $r.Content }
        } catch { }
        Start-Sleep -Seconds 4
        Write-Host '.' -NoNewline -ForegroundColor DarkGray
    }
    Write-Host ''
    return $null
}

# 写 UTF-8 无 BOM 文件（PowerShell 5.1 的 Set-Content -Encoding UTF8 会带 BOM，
# 而 pydantic 读 .env 时会把 BOM 算进第一个键名，导致配置失效）
function Write-Utf8NoBom([string]$path, [string[]]$lines) {
    $enc = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllLines($path, $lines, $enc)
}

function Copy-WithBackup([string]$src, [string]$dst) {
    if (Test-Path $dst) {
        if (-not $Force) { Info "$dst 已存在，保留原文件（要重建加 -Force）"; return $false }
        $bak = "$dst.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Copy-Item $dst $bak -Force
        Info "已备份 $dst -> $bak"
    }
    Copy-Item $src $dst -Force
    return $true
}

function Get-PythonLauncher {
    foreach ($c in @('python', 'py')) { if (Have $c) { return $c } }
    return $null
}

function Assert-Root {
    if (-not (Test-Path (Join-Path $script:Root 'pyproject.toml'))) {
        Die @"
当前目录不是仓库根目录：$script:Root
    判据：pyproject.toml、docker\docker-compose.yml 必须和这个脚本在同一层。
    GitHub 的 Download ZIP 解压后常见会多套一层目录，请进入含 pyproject.toml 的那一层再运行。
"@
    }
    Ok "仓库根目录：$script:Root"
}

# ─────────────────────────── 环境文件 ───────────────────────────
function Write-RootEnv {
    $dst = Join-Path $script:Root '.env'
    if ((Test-Path $dst) -and -not $Force) {
        Info ".env 已存在，保留原文件（如需按本次参数重建：加 -Force）"
        return
    }
    if (Test-Path $dst) {
        $bak = "$dst.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Copy-Item $dst $bak -Force; Info "已备份 .env -> $bak"
    }
    $tpl = Get-Content (Join-Path $script:Root '.env.example') -Encoding UTF8
    $url = 'postgresql+asyncpg://{0}:{1}@127.0.0.1:{2}/{3}' -f $PgUser, $PgPassword, $PgPort, $DbName
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($l in $tpl) {
        if ($l -match '^BMP_DATABASE_URL=') { $out.Add("BMP_DATABASE_URL=$url") }
        elseif ($l -match '^BMP_PORT=') { $out.Add("BMP_PORT=$ApiPort") }
        elseif ($l -match '^BMP_DEBUG=') { $out.Add('BMP_DEBUG=false') }
        elseif (($l -match '^BMP_LLM_API_KEY=') -and $LlmApiKey) { $out.Add("BMP_LLM_API_KEY=$LlmApiKey") }
        elseif (($l -match '^BMP_LLM_API_BASE=') -and $LlmApiBase) { $out.Add("BMP_LLM_API_BASE=$LlmApiBase") }
        else { $out.Add($l) }
    }
    Write-Utf8NoBom $dst $out.ToArray()
    Ok ".env 已生成（数据库指向 127.0.0.1:$PgPort/$DbName）"
    if (-not $LlmApiKey) { Warn 'BMP_LLM_API_KEY 仍是空值：模型类功能需要它，随后可在 .env 里补' }
}

function Write-DockerEnv {
    $dst = Join-Path $script:Root 'docker\.env.docker'
    if ((Test-Path $dst) -and -not $Force) {
        Info "docker\.env.docker 已存在，保留原文件（如需按本次参数重建：加 -Force）"
    } else {
        if (Test-Path $dst) {
            $bak = "$dst.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
            Copy-Item $dst $bak -Force; Info "已备份 docker\.env.docker -> $bak"
        }
        $tplPath = Join-Path $script:Root 'docker\.env.docker.example'
        $tpl = Get-Content $tplPath -Encoding UTF8
        $out = New-Object System.Collections.Generic.List[string]
        foreach ($l in $tpl) {
            if (($l -match '^LLM_API_KEY=') -and $LlmApiKey) { $out.Add("LLM_API_KEY=$LlmApiKey") }
            elseif (($l -match '^LLM_API_BASE=') -and $LlmApiBase) { $out.Add("LLM_API_BASE=$LlmApiBase") }
            elseif ($l -match '^WEB_PORT=') { $out.Add("WEB_PORT=$SitePort") }
            elseif ($l -match '^API_PORT=') { $out.Add("API_PORT=$ApiPort") }
            elseif ($l -match '^UVICORN_WORKERS=') { $out.Add('UVICORN_WORKERS=1') }
            else { $out.Add($l) }
        }
        if (-not ($out -match '^UVICORN_WORKERS=')) { $out.Add('UVICORN_WORKERS=1') }
        Write-Utf8NoBom $dst $out.ToArray()
        Ok "docker\.env.docker 已生成（站点端口 $SitePort / API $ApiPort）"
    }
    # 容器要挂载根 .env，文件不存在时 Docker 会把它建成目录
    $rootEnv = Join-Path $script:Root '.env'
    if (-not (Test-Path $rootEnv)) {
        Copy-Item (Join-Path $script:Root '.env.example') $rootEnv -Force
        Ok '根 .env 已从 .env.example 创建（容器会挂载它；文件缺失时 Docker 会建同名目录）'
    } else {
        Ok '根 .env 已存在（容器挂载源就绪）'
    }
}

# ─────────────────────────── PostgreSQL（方式二） ───────────────────────────
function Resolve-PgBin {
    $cands = @()
    if ($PgRoot) { $cands += (Join-Path $PgRoot 'extracted\pgsql\bin'); $cands += (Join-Path $PgRoot 'bin') }
    $cands += (Join-Path $script:Root '.pgsql\extracted\pgsql\bin')
    foreach ($c in $cands) {
        if (Test-Path (Join-Path $c 'pg_ctl.exe')) { return $c }
    }
    if (Have 'pg_ctl') { return '' }   # 已在 PATH 里
    return $null
}

function Ensure-Postgres {
    $bin = Resolve-PgBin
    if ($null -eq $bin) {
        Die @"
本机没有找到 PostgreSQL（方式二必需）。
    三种办法，任选其一后重新运行本脚本：

    1) 便携版（免安装、免管理员）：把解压好的 pgsql 目录放到
         $script:Root\.pgsql\extracted\pgsql\
       使得 $script:Root\.pgsql\extracted\pgsql\bin\pg_ctl.exe 存在，并准备好数据目录
         $script:Root\.pgsql\data   （用 initdb 初始化）
       本机现成的一份在 D:\esa\BidMaster-Pro\.pgsql（PG 16），可直接复制过来。

    2) 官方安装包：https://www.postgresql.org/download/windows/
       安装后确保 psql/pg_ctl 在 PATH 中，或加参数：-PgRoot "C:\Program Files\PostgreSQL\16"

    3) 用 Docker 只起数据库（需要 Docker 引擎可用）：
         docker compose -f docker/docker-compose.yml --profile infra up -d postgres
"@
    }
    if ($bin) { Ok "PostgreSQL 客户端：$bin" } else { Ok 'PostgreSQL 客户端：PATH 中已有 pg_ctl' }

    if (Test-Port '127.0.0.1' $PgPort) {
        Ok "PostgreSQL 已在 127.0.0.1:$PgPort 运行"
    } else {
        $bat = Join-Path $script:Root 'start-postgres.bat'
        if ($PgRoot) { $dataDir = Join-Path $PgRoot 'data' } else { $dataDir = Join-Path $script:Root '.pgsql\data' }
        if ($bin) {
            # 优先直接用 pg_ctl：实测仓库自带的 start-postgres.bat 在中文 Windows 上会因
            # "UTF-8 批处理 + 中途 chcp 65001" 被 cmd 丢掉后续语句而**静默不干活**。
            $pgctl = Join-Path $bin 'pg_ctl.exe'
            $log = Join-Path $script:LogDir 'postgres.log'
            Info "启动 PostgreSQL：pg_ctl -D `"$dataDir`" -l `"$log`" -w start"
            $p = Start-Process -FilePath $pgctl -ArgumentList @('-D', $dataDir, '-l', $log, '-w', 'start') -NoNewWindow -PassThru `
                -RedirectStandardOutput (Join-Path $script:LogDir 'pg_ctl.out.log') `
                -RedirectStandardError (Join-Path $script:LogDir 'pg_ctl.err.log')
            $deadline = (Get-Date).AddSeconds(90)
            while (-not $p.HasExited -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
        } elseif ((Test-Path $bat) -and (Test-Path $dataDir)) {
            Info '启动便携 PostgreSQL（start-postgres.bat）…'
            # 关键：不要把被启动进程的 stdout 接进管道 —— postgres 会一直持有那个句柄，脚本会卡死。
            # 统一重定向到日志文件，再用轮询等方式它退出（最多 60 秒，超时也继续走下面的端口探测）。
            $p = Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', "`"$bat`"" -NoNewWindow -PassThru `
                -RedirectStandardOutput (Join-Path $script:LogDir 'pg_start.out.log') `
                -RedirectStandardError (Join-Path $script:LogDir 'pg_start.err.log')
            $deadline = (Get-Date).AddSeconds(60)
            while (-not $p.HasExited -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
        } else {
            Die "PostgreSQL 未运行，且没有可用的 pg_ctl 启动它。请先启动 PostgreSQL（服务或便携版）后重试。"
        }
        for ($i = 0; $i -lt 15; $i++) {
            Start-Sleep -Seconds 2
            if (Test-Port '127.0.0.1' $PgPort) { break }
        }
        if (-not (Test-Port '127.0.0.1' $PgPort)) { Die "PostgreSQL 启动后仍未监听 127.0.0.1:$PgPort，请看 $script:LogDir\postgres.log" }
        Ok "PostgreSQL 已启动（127.0.0.1:$PgPort）"
    }
    return $bin
}

function Get-PsqlPath([string]$bin) {
    if ($bin) { $p = Join-Path $bin 'psql.exe'; if (Test-Path $p) { return $p } }
    if (Have 'psql') { return 'psql' }
    Die '找不到 psql.exe，无法建库建表。请用官方安装包安装（含客户端工具），或改用 Docker 方式。'
}

function Ensure-Database([string]$bin) {
    $psql = Get-PsqlPath $bin
    $env:PGPASSWORD = $PgPassword
    $sql = "SELECT 1 FROM pg_database WHERE datname='$DbName'"
    $exists = (& $psql -h 127.0.0.1 -p $PgPort -U $PgUser -d postgres -tAc $sql 2>&1 | Out-String)
    Write-Log "psql 检查库是否存在: $exists"
    if ($exists -notmatch '1') {
        Info "创建数据库 $DbName …"
        & $psql -h 127.0.0.1 -p $PgPort -U $PgUser -d postgres -c "CREATE DATABASE `"$DbName`"" 2>&1 | ForEach-Object { Write-Log "  $_" }
        if ($LASTEXITCODE -ne 0) { Die "创建数据库失败（口令是否正确？见 -PgPassword）。日志：$script:LogFile" }
        Ok "数据库 $DbName 已创建"
    } else {
        Ok "数据库 $DbName 已存在"
    }
    Info '导入 db/init_pg.sql（幂等；内含循环外键，允许个别语句报错）…'
    $sqlFile = Join-Path $script:Root 'db\init_pg.sql'
    $raw = & $psql -h 127.0.0.1 -p $PgPort -U $PgUser -d $DbName -f $sqlFile 2>&1
    $raw | ForEach-Object { Write-Log "  $_" }
    $errCount = @($raw | Select-String -Pattern 'ERROR:').Count
    if ($errCount -gt 0) {
        Warn "init_pg.sql 有 $errCount 条语句报错（不中断，完整表结构由下一步 init_db() 补齐）"
    } else {
        Ok 'init_pg.sql 全部语句执行成功'
    }

    # 权威建表路径：应用的 Base.metadata.create_all。不启动服务也能把 schema 建全。
    $venvPy = Join-Path $script:Root 'venv\Scripts\python.exe'
    if (Test-Path $venvPy) {
        Info '执行 init_db() 补齐全部表 …'
        $url = 'postgresql+asyncpg://{0}:{1}@127.0.0.1:{2}/{3}' -f $PgUser, $PgPassword, $PgPort, $DbName
        $prevUrl = $env:BMP_DATABASE_URL
        $env:BMP_DATABASE_URL = $url
        & $venvPy -c 'import asyncio; from services.database import init_db; asyncio.run(init_db())' 2>&1 |
            ForEach-Object { Write-Log "  $_" }
        if ($LASTEXITCODE -ne 0) { Warn "init_db() 返回 $LASTEXITCODE，详见 $script:LogFile" }
        if ($prevUrl) { $env:BMP_DATABASE_URL = $prevUrl } else { Remove-Item Env:\BMP_DATABASE_URL -ErrorAction SilentlyContinue }
        $tblCount = (& $psql -h 127.0.0.1 -p $PgPort -U $PgUser -d $DbName -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>&1 | Out-String).Trim()
        Ok "表结构就绪：public 下 $tblCount 张表"
    } else {
        Warn '没找到 venv 里的 python，跳过 init_db()；启动 API 时会自动补齐表'
    }
}

# ─────────────────────────── 方式二：本地开发 ───────────────────────────
function Install-Local {
    $py = Get-PythonLauncher
    Step '1/8' '检查 Python'
    if (-not $py) { Die '未找到 python。请安装 Python 3.12+ 并勾选"Add to PATH"，然后重新打开终端。' }
    $ver = (& $py -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>&1 | Out-String).Trim()
    Write-Log "python $py 版本 $ver"
    $v = [version]$ver
    if ($v -lt [version]'3.12') { Die "Python 版本过低：$ver（需要 3.12+）" }
    Ok "Python $ver（$py）"

    Step '2/8' '创建虚拟环境并安装后端依赖（首次约 2-4 分钟）'
    $venvPy = Join-Path $script:Root 'venv\Scripts\python.exe'
    if (-not (Test-Path $venvPy)) {
        Info '创建 venv …'
        & $py -m venv (Join-Path $script:Root 'venv') 2>&1 | ForEach-Object { Write-Log "  $_" }
        if (-not (Test-Path $venvPy)) { Die '创建虚拟环境失败。' }
        Ok 'venv 已创建'
    } else {
        Ok 'venv 已存在，复用'
    }
    Info 'pip install -e .（输出较多，只写日志）…'
    & $venvPy -m pip install --disable-pip-version-check -e $script:Root 2>&1 | ForEach-Object { Write-Log "  $_" }
    if ($LASTEXITCODE -ne 0) { Die "pip install -e . 失败。详见 $script:LogFile" }
    Ok '后端依赖安装完成'

    Step '3/8' '安装前端依赖'
    if ($SkipFrontend) {
        Warn '已按 -SkipFrontend 跳过'
    } elseif (-not (Have 'npm')) {
        Warn '未找到 npm，跳过前端依赖。装好 Node.js 18+ 后执行：cd packages\desktop; npm install'
    } elseif (Test-Path (Join-Path $script:Root 'packages\desktop\node_modules')) {
        Ok 'node_modules 已存在，跳过（需要更新时自行 npm install）'
    } else {
        Info 'npm install …（输出较多，只写日志）'
        Push-Location (Join-Path $script:Root 'packages\desktop')
        & npm install 2>&1 | ForEach-Object { Write-Log "  $_" }
        $code = $LASTEXITCODE
        Pop-Location
        if ($code -ne 0) { Warn "npm install 返回 $code，请自行确认（不阻塞后端）" } else { Ok '前端依赖安装完成' }
    }

    Step '4/8' '准备 PostgreSQL'
    $bin = Ensure-Postgres

    Step '5/8' '建库 + 建表'
    Ensure-Database $bin

    Step '6/8' '生成 .env'
    Write-RootEnv

    Step '7/8' '创建管理员账号（幂等）'
    $env:ADMIN_EMAIL = $AdminEmail
    if ($AdminPassword) { $env:ADMIN_PASSWORD = $AdminPassword } else { Remove-Item Env:\ADMIN_PASSWORD -ErrorAction SilentlyContinue }
    $env:PYTHONIOENCODING = 'utf-8'
    & $venvPy (Join-Path $script:Root 'deploy\seed_admin.py') 2>&1 | ForEach-Object { Write-Log "  $_"; Write-Host "    $_" -ForegroundColor Gray }
    if ($LASTEXITCODE -ne 0) { Warn "seed_admin.py 返回 $LASTEXITCODE（若账号已存在可忽略）" } else { Ok "管理员账号：$AdminEmail" }

    Step '8/8' '启动服务'
    if ($NoStart) {
        Warn '已按 -NoStart 跳过启动。手动启动：'
        Info "后端： .\venv\Scripts\python.exe -m uvicorn services.main:app --reload --port $ApiPort"
        Info "前端： cd packages\desktop; npm run dev"
        return
    }
    if (Test-Port '127.0.0.1' $ApiPort) {
        Ok "API 已在 127.0.0.1:$ApiPort 运行，跳过启动"
    } else {
        $env:PYTHONIOENCODING = 'utf-8'; $env:PYTHONUTF8 = '1'
        Start-Process -FilePath $venvPy `
            -ArgumentList '-m', 'uvicorn', 'services.main:app', '--host', '0.0.0.0', '--port', "$ApiPort" `
            -WorkingDirectory $script:Root -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $script:LogDir 'api.out.log') `
            -RedirectStandardError (Join-Path $script:LogDir 'api.err.log')
        Info "等待 API 就绪（http://127.0.0.1:$ApiPort/api/health）…"
        $body = Wait-Http "http://127.0.0.1:$ApiPort/api/health" 90 'api'
        if ($body) { Ok 'API 已就绪' } else { Warn "API 未在 90 秒内就绪，请看 $script:LogDir\api.err.log" }
    }
    if (-not $SkipFrontend -and (Have 'npm') -and -not (Test-Port '127.0.0.1' $DevPort)) {
        $env:VITE_API_TARGET = "http://127.0.0.1:$ApiPort"
        # vite 的端口在 vite.config.ts 里写死为 15168，这里显式覆盖，让 -DevPort 真正生效
        $webCmd = "npm run dev -- --port $DevPort --strictPort"
        Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $webCmd `
            -WorkingDirectory (Join-Path $script:Root 'packages\desktop') -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $script:LogDir 'web.out.log') `
            -RedirectStandardError (Join-Path $script:LogDir 'web.err.log')
        Info "等待前端就绪（http://127.0.0.1:$DevPort/）…"
        $html = Wait-Http "http://127.0.0.1:$DevPort/" 120 'web'
        if ($html) { Ok '前端已就绪' } else { Warn "前端未在 120 秒内就绪，请看 $script:LogDir\web.err.log" }
    }
    Write-Host ''
    Ok "站点：        http://127.0.0.1:$DevPort/"
    Ok "API 文档：    http://127.0.0.1:$ApiPort/docs"
    Ok "健康检查：    http://127.0.0.1:$ApiPort/api/health"
    Info "登录账号：    $AdminEmail"
    Info "停止服务：    .\stop.ps1    （日志在 logs\）"
}

# ─────────────────────────── 方式一：Docker ───────────────────────────
function Install-Docker {
    Step '1/6' '检查 Docker 引擎'
    if (-not (Have 'docker')) { return $false }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Warn 'Docker 引擎不可用（daemon 没起来）。常见原因与处理：'
        Info '1) 没启动 Docker Desktop：先打开它，等托盘图标就绪'
        Info '2) 未启用 WSL2 / Hyper-V：管理员 PowerShell 执行 wsl --install（或启用「虚拟机平台」'
        Info '   +「适用于 Linux 的 Windows 子系统」，专业版也可用 Hyper-V），然后重启电脑'
        Info '3) 验证：docker info 能输出 Server 版本即正常'
        Write-Log 'docker info 失败，Docker 不可用'
        return $false
    }
    $sv = (& docker info --format '{{.ServerVersion}}' 2>&1 | Out-String).Trim()
    Ok "Docker 引擎可用（Server $sv）"

    Step '2/6' '生成环境文件'
    Write-DockerEnv

    Step '3/6' '构建并启动（首次构建较慢，请耐心）'
    $composeArgs = @('compose', '-f', 'docker/docker-compose.yml', '--env-file', 'docker/.env.docker',
        '--profile', 'infra', '--profile', 'web', 'up', '-d', '--build')
    Info ('docker ' + ($composeArgs -join ' '))
    & docker @composeArgs 2>&1 | ForEach-Object { Write-Log "  $_"; Write-Host "    $_" -ForegroundColor DarkGray }
    if ($LASTEXITCODE -ne 0) { Die "docker compose up 失败。详见 $script:LogFile" }
    Ok '容器已创建'

    Step '4/6' '等待 API 健康检查'
    Info "http://127.0.0.1:$ApiPort/api/health （最多 8 分钟：首次要构建镜像 + 等数据库）"
    $body = Wait-Http "http://127.0.0.1:$ApiPort/api/health" 480 'api'
    if ($body) { Ok 'API 已就绪' } else { Warn "API 未在 8 分钟内就绪，执行下面命令看日志：docker compose -f docker/docker-compose.yml logs -f api" }

    Step '5/6' '创建管理员账号（幂等）'
    if ($AdminPassword) {
        & docker compose -f docker/docker-compose.yml exec -T -e "ADMIN_EMAIL=$AdminEmail" -e "ADMIN_PASSWORD=$AdminPassword" api python deploy/seed_admin.py 2>&1 |
            ForEach-Object { Write-Log "  $_"; Write-Host "    $_" -ForegroundColor Gray }
    } else {
        & docker compose -f docker/docker-compose.yml exec -T -e "ADMIN_EMAIL=$AdminEmail" api python deploy/seed_admin.py 2>&1 |
            ForEach-Object { Write-Log "  $_"; Write-Host "    $_" -ForegroundColor Gray }
    }
    Ok "管理员账号：$AdminEmail（随机密码见上方输出，只显示一次）"

    Step '6/6' '完成'
    Write-Host ''
    Ok "站点：        http://127.0.0.1:$SitePort/"
    Ok "API 文档：    http://127.0.0.1:$ApiPort/docs"
    Info '查看状态：    docker compose -f docker/docker-compose.yml ps'
    Info '看日志：      docker compose -f docker/docker-compose.yml logs -f api'
    Info '停止：        docker compose -f docker/docker-compose.yml stop（数据卷保留；down -v 会删库）'
    return $true
}

# ─────────────────────────── 主流程 ───────────────────────────
Title '智标 一键安装 / 部署'
Write-Log "参数：Mode=$Mode ApiPort=$ApiPort SitePort=$SitePort DevPort=$DevPort DbName=$DbName SkipFrontend=$SkipFrontend NoStart=$NoStart Force=$Force"

Step '0/8' '检查目录（仓库根目录）'
Assert-Root

if (-not $LlmApiKey -and -not $Yes) {
    Write-Host ''
    Write-Host '  提示：模型类功能需要 LLM API Key（DeepSeek 等）。' -ForegroundColor Yellow
    $keyInput = Read-Host '  现在输入 API Key（直接回车跳过，稍后可在 .env 里补）'
    if ($keyInput) { $LlmApiKey = $keyInput.Trim() }
}

if ($Mode -eq 'docker') {
    if (-not (Install-Docker)) { Die 'Docker 方式不可用（见上方原因）。可改用：.\install.ps1 -Mode local' }
} elseif ($Mode -eq 'local') {
    Install-Local
} else {
    Info '模式：自动判断（Docker 可用则走 Docker，否则走本地开发）'
    if (-not (Install-Docker)) {
        Warn '自动改用方式二：本地开发'
        Install-Local
    }
}

Title '完成'
Write-Host "  日志：$script:LogFile" -ForegroundColor DarkGray
if (-not $Yes) { Write-Host '' }