[CmdletBinding()]
param(
    [ValidateSet('Start', 'Status')]
    [string]$Action = 'Start',
    [switch]$Rebuild,
    [switch]$SkipDashboard,
    [switch]$SkipApp,
    [switch]$SkipAgent,
    [switch]$SkipWeb
)

$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RuntimeRoot = Join-Path $ProjectRoot '.local-runtime'
$LogRoot = Join-Path $RuntimeRoot 'logs'

$RedisRoot = 'D:\JAVA\Redis-x64-5.0.14.1'
$RedisServer = Join-Path $RedisRoot 'redis-server.exe'
$RedisConfig = Join-Path $RedisRoot 'redis.windows.conf'

$RocketMqRoot = 'E:\JAVA\rocketmq-all-5.1.4-bin-release'
$NameServerScript = Join-Path $RocketMqRoot 'bin\mqnamesrv.cmd'
$BrokerScript = Join-Path $RocketMqRoot 'bin\mqbroker.cmd'
$BrokerConfig = Join-Path $RocketMqRoot 'conf\broker.conf'

$CanalRoot = 'D:\JAVA\canal.deployer-1.1.4'
$CanalScript = Join-Path $CanalRoot 'bin\startup.bat'

$DashboardRoot = 'C:\Users\22331\rocketmq-dashboard\target'
$DashboardJar = Join-Path $DashboardRoot 'rocketmq-dashboard-2.0.1-SNAPSHOT.jar'

$AppRoot = Join-Path $ProjectRoot 'incentive'
$AppJar = Join-Path $AppRoot 'target\incentive-0.0.1-SNAPSHOT.jar'
$AgentRoot = Join-Path $ProjectRoot 'agent-service'
$AgentPython = Join-Path $AgentRoot '.venv\Scripts\python.exe'
$AgentEnv = Join-Path $AgentRoot '.env'
$AgentPort = 8090
$WebRoot = Join-Path $ProjectRoot 'web-ui'
$WebPackage = Join-Path $WebRoot 'package.json'
$WebDistIndex = Join-Path $WebRoot 'dist\index.html'
if (Test-Path -LiteralPath $AgentEnv) {
    $agentPortLine = Get-Content -LiteralPath $AgentEnv |
        Where-Object { $_ -match '^\s*AGENT_PORT\s*=\s*\d+\s*$' } |
        Select-Object -Last 1
    if ($null -ne $agentPortLine -and $agentPortLine -match '=\s*(\d+)\s*$') {
        $AgentPort = [int]$Matches[1]
    }
}

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Test-TcpPort([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        return $task.Wait(500) -and $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Wait-TcpPort(
    [string]$Name,
    [int]$Port,
    [int]$TimeoutSeconds = 30,
    [switch]$Optional
) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPort $Port) {
            Write-Host "[READY] $Name 127.0.0.1:$Port" -ForegroundColor Green
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    $message = "$Name did not listen on port $Port within $TimeoutSeconds seconds."
    if ($Optional) {
        Write-Warning $message
        return $false
    }
    throw $message
}

function Assert-Path([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Name not found: $Path"
    }
}

function Start-LoggedProcess(
    [string]$Name,
    [string]$FilePath,
    [string[]]$ArgumentList,
    [string]$WorkingDirectory
) {
    New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
    $stdout = Join-Path $LogRoot "$Name.out.log"
    $stderr = Join-Path $LogRoot "$Name.err.log"
    $startProcessArgs = @{
        FilePath = $FilePath
        ArgumentList = $ArgumentList
        WorkingDirectory = $WorkingDirectory
        WindowStyle = 'Hidden'
        RedirectStandardOutput = $stdout
        RedirectStandardError = $stderr
        PassThru = $true
    }
    $process = Start-Process @startProcessArgs
    Write-Host "[STARTED] $Name pid=$($process.Id), logs=$LogRoot"
}

function Start-CmdScript(
    [string]$Name,
    [string]$ScriptPath,
    [string]$Arguments,
    [string]$WorkingDirectory
) {
    $command = "call `"$ScriptPath`" $Arguments"
    $processArgs = @{
        Name = $Name
        FilePath = $env:ComSpec
        ArgumentList = @('/d', '/c', $command)
        WorkingDirectory = $WorkingDirectory
    }
    Start-LoggedProcess @processArgs
}

function Start-MySql {
    if (Test-TcpPort 3306) {
        Write-Host '[SKIP] MySQL is already listening on 3306.'
        return
    }

    Write-Step 'Starting MySQL'
    $service = Get-Service -Name 'MySQL80' -ErrorAction SilentlyContinue
    if ($null -eq $service) {
        $service = Get-Service | Where-Object {
            $_.Name -match '^MySQL|^MariaDB' -or
            $_.DisplayName -match '^MySQL|^MariaDB'
        } | Select-Object -First 1
    }
    if ($null -eq $service) {
        throw 'No MySQL Windows service was found. Start MySQL manually first.'
    }
    if ($service.Status -ne 'Running') {
        try {
            Start-Service -Name $service.Name
        }
        catch {
            throw "Unable to start $($service.Name). Run this script as administrator or start the service manually."
        }
    }
    Wait-TcpPort -Name 'MySQL' -Port 3306 -TimeoutSeconds 30 | Out-Null
}

function Start-Redis {
    if (Test-TcpPort 6379) {
        Write-Host '[SKIP] Redis is already listening on 6379.'
        return
    }

    Write-Step 'Starting Redis'
    Assert-Path $RedisServer 'redis-server.exe'
    Assert-Path $RedisConfig 'Redis config'
    $processArgs = @{
        Name = 'redis'
        FilePath = $RedisServer
        ArgumentList = @("`"$RedisConfig`"")
        WorkingDirectory = $RedisRoot
    }
    Start-LoggedProcess @processArgs
    Wait-TcpPort -Name 'Redis' -Port 6379 -TimeoutSeconds 20 | Out-Null
}

function Start-RocketMq {
    Assert-Path $NameServerScript 'RocketMQ NameServer script'
    Assert-Path $BrokerScript 'RocketMQ Broker script'
    Assert-Path $BrokerConfig 'RocketMQ Broker config'

    if (-not (Test-TcpPort 9876)) {
        Write-Step 'Starting RocketMQ NameServer'
        $scriptArgs = @{
            Name = 'rocketmq-nameserver'
            ScriptPath = $NameServerScript
            Arguments = ''
            WorkingDirectory = (Join-Path $RocketMqRoot 'bin')
        }
        Start-CmdScript @scriptArgs
        Wait-TcpPort -Name 'RocketMQ NameServer' -Port 9876 -TimeoutSeconds 45 | Out-Null
    }
    else {
        Write-Host '[SKIP] RocketMQ NameServer is already listening on 9876.'
    }

    if (-not (Test-TcpPort 10911)) {
        Write-Step 'Starting RocketMQ Broker'
        $arguments = "-n 127.0.0.1:9876 -c `"$BrokerConfig`" autoCreateTopicEnable=true"
        $scriptArgs = @{
            Name = 'rocketmq-broker'
            ScriptPath = $BrokerScript
            Arguments = $arguments
            WorkingDirectory = (Join-Path $RocketMqRoot 'bin')
        }
        Start-CmdScript @scriptArgs
        Wait-TcpPort -Name 'RocketMQ Broker' -Port 10911 -TimeoutSeconds 60 | Out-Null
    }
    else {
        Write-Host '[SKIP] RocketMQ Broker is already listening on 10911.'
    }
}

function Start-Canal {
    if (Test-TcpPort 11111) {
        Write-Host '[SKIP] Canal is already listening on 11111.'
        return
    }

    Write-Step 'Starting Canal'
    Assert-Path $CanalScript 'Canal startup script'
    $scriptArgs = @{
        Name = 'canal'
        ScriptPath = $CanalScript
        Arguments = ''
        WorkingDirectory = (Join-Path $CanalRoot 'bin')
    }
    Start-CmdScript @scriptArgs
    Wait-TcpPort -Name 'Canal' -Port 11111 -TimeoutSeconds 45 | Out-Null
}

function Start-Dashboard {
    if ($SkipDashboard) {
        Write-Host '[SKIP] RocketMQ Dashboard was disabled by -SkipDashboard.'
        return
    }
    if (Test-TcpPort 8080) {
        Write-Host '[SKIP] Port 8080 is already in use; dashboard startup was skipped.'
        return
    }

    Write-Step 'Starting RocketMQ Dashboard (optional)'
    Assert-Path $DashboardJar 'RocketMQ Dashboard jar'
    $java = (Get-Command java -ErrorAction Stop).Source
    $processArgs = @{
        Name = 'rocketmq-dashboard'
        FilePath = $java
        ArgumentList = @('-jar', "`"$DashboardJar`"")
        WorkingDirectory = $DashboardRoot
    }
    Start-LoggedProcess @processArgs
    Wait-TcpPort -Name 'RocketMQ Dashboard' -Port 8080 -TimeoutSeconds 45 -Optional | Out-Null
}

function Test-AppJarNeedsBuild {
    if ($Rebuild -or -not (Test-Path -LiteralPath $AppJar)) {
        return $true
    }
    $jarTime = (Get-Item -LiteralPath $AppJar).LastWriteTimeUtc
    $newerSource = Get-ChildItem -LiteralPath (Join-Path $AppRoot 'src') -Recurse -File |
        Where-Object { $_.LastWriteTimeUtc -gt $jarTime } |
        Select-Object -First 1
    if ($null -ne $newerSource) {
        return $true
    }
    return (Get-Item -LiteralPath (Join-Path $AppRoot 'pom.xml')).LastWriteTimeUtc -gt $jarTime
}

function Start-App {
    if ($SkipApp) {
        Write-Host '[SKIP] Spring Boot application was disabled by -SkipApp.'
        return
    }
    if (Test-TcpPort 8088) {
        Write-Host '[SKIP] Spring Boot application is already listening on 8088.'
        return
    }

    if (Test-AppJarNeedsBuild) {
        Write-Step 'Building Spring Boot application'
        Push-Location $AppRoot
        try {
            & mvn -q -DskipTests package
            if ($LASTEXITCODE -ne 0) {
                throw "Maven build failed with exit code $($LASTEXITCODE)."
            }
        }
        finally {
            Pop-Location
        }
    }

    Write-Step 'Starting Spring Boot application (HTTP + project consumer)'
    Assert-Path $AppJar 'Spring Boot jar'
    $java = (Get-Command java -ErrorAction Stop).Source
    $processArgs = @{
        Name = 'incentive-app'
        FilePath = $java
        ArgumentList = @('-jar', "`"$AppJar`"")
        WorkingDirectory = $AppRoot
    }
    Start-LoggedProcess @processArgs
    Wait-TcpPort -Name 'Spring Boot application' -Port 8088 -TimeoutSeconds 120 | Out-Null
}

function Test-WebNeedsBuild {
    if ($Rebuild -or -not (Test-Path -LiteralPath $WebDistIndex)) {
        return $true
    }

    $distTime = (Get-Item -LiteralPath $WebDistIndex).LastWriteTimeUtc
    $candidatePaths = @(
        (Join-Path $WebRoot 'src'),
        (Join-Path $WebRoot 'index.html'),
        (Join-Path $WebRoot 'package.json'),
        (Join-Path $WebRoot 'vite.config.mjs')
    )
    $newerSource = Get-ChildItem -LiteralPath $candidatePaths -Recurse -File |
        Where-Object { $_.LastWriteTimeUtc -gt $distTime } |
        Select-Object -First 1
    return $null -ne $newerSource
}

function Build-Web {
    if ($SkipWeb -or $SkipAgent) {
        $reason = if ($SkipWeb) { '-SkipWeb' } else { '-SkipAgent' }
        Write-Host "[SKIP] Web UI build was disabled by $reason."
        return
    }

    Assert-Path $WebPackage 'Web UI package.json'
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    Push-Location $WebRoot
    try {
        if (-not (Test-Path -LiteralPath (Join-Path $WebRoot 'node_modules'))) {
            Write-Step 'Installing Web UI dependencies'
            & $npm install
            if ($LASTEXITCODE -ne 0) {
                throw "Web UI dependency installation failed with exit code $($LASTEXITCODE)."
            }
        }

        if (Test-WebNeedsBuild) {
            Write-Step 'Building Web UI'
            & $npm run build
            if ($LASTEXITCODE -ne 0) {
                throw "Web UI build failed with exit code $($LASTEXITCODE)."
            }
        }
        else {
            Write-Host '[SKIP] Web UI build output is up to date.'
        }
    }
    finally {
        Pop-Location
    }
}

function Start-Agent {
    if ($SkipAgent) {
        Write-Host '[SKIP] Agent HTTP service was disabled by -SkipAgent.'
        return
    }
    if (Test-TcpPort $AgentPort) {
        Write-Host "[SKIP] Agent HTTP service is already listening on $AgentPort."
        return
    }

    Write-Step 'Starting Agent HTTP service'
    Assert-Path $AgentPython 'Agent Python virtual environment'
    Assert-Path $AgentEnv 'Agent .env config'
    $processArgs = @{
        Name = 'agent-service'
        FilePath = $AgentPython
        ArgumentList = @('-m', 'app.server')
        WorkingDirectory = $AgentRoot
    }
    Start-LoggedProcess @processArgs
    Wait-TcpPort -Name 'Agent HTTP service' -Port $AgentPort -TimeoutSeconds 45 | Out-Null
}

function Show-Status {
    $services = @(
        [pscustomobject]@{ Name = 'MySQL'; Port = 3306; Required = $true },
        [pscustomobject]@{ Name = 'Redis'; Port = 6379; Required = $true },
        [pscustomobject]@{ Name = 'RocketMQ NameServer'; Port = 9876; Required = $true },
        [pscustomobject]@{ Name = 'RocketMQ Broker'; Port = 10911; Required = $true },
        [pscustomobject]@{ Name = 'Canal'; Port = 11111; Required = $true },
        [pscustomobject]@{ Name = 'RocketMQ Dashboard'; Port = 8080; Required = $false },
        [pscustomobject]@{ Name = 'Spring Boot application'; Port = 8088; Required = $true },
        [pscustomobject]@{ Name = 'Agent HTTP service'; Port = $AgentPort; Required = (-not $SkipAgent) }
    )
    $services | ForEach-Object {
        $state = 'DOWN'
        if (Test-TcpPort $_.Port) {
            $state = 'UP'
        }
        [pscustomobject]@{
            Service = $_.Name
            Address = "127.0.0.1:$($_.Port)"
            Required = $_.Required
            Status = $state
        }
    } | Format-Table -AutoSize
    if ((Test-Path -LiteralPath $WebDistIndex) -and (Test-TcpPort $AgentPort)) {
        Write-Host "Web UI: http://127.0.0.1:$AgentPort/"
    }
    Write-Host "Logs: $LogRoot"
}

if ($Action -eq 'Status') {
    Show-Status
    exit 0
}

try {
    Start-MySql
    Start-Redis
    Start-RocketMq
    Start-Canal
    Start-Dashboard
    Start-App
    Build-Web
    Start-Agent
    Write-Step 'Local environment startup completed'
    Show-Status
}
catch {
    Write-Host "`n[FAILED] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Check logs under: $LogRoot" -ForegroundColor Yellow
    exit 1
}
