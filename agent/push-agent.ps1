param(
    [string]$BotUrl = $env:FORTYTWO_BOT_URL,
    [string]$AgentToken = $env:FORTYTWO_AGENT_TOKEN,
    [int]$IntervalSeconds = 30,
    [Parameter(Mandatory=$true)]
    [string]$ScriptsRoot,
    [string]$DockerContainer = $env:FORTYTWO_DOCKER_CONTAINER,
    [switch]$Once,
    [switch]$DryRun
)

if (-not $DryRun) {
    if (-not $BotUrl) { throw "FORTYTWO_BOT_URL env not set (or pass -BotUrl, or use -DryRun)" }
    if (-not $AgentToken) { throw "FORTYTWO_AGENT_TOKEN env not set (or pass -AgentToken, or use -DryRun)" }
}

$ExtLog          = Join-Path $ScriptsRoot "extended_log.txt"
$CapsuleLog      = Join-Path $ScriptsRoot "FortytwoNode\debug\FortytwoCapsule.log"
$ReadyUrl        = "http://localhost:42442/ready"
$RoundsHistoryFile = Join-Path $PSScriptRoot "rounds-history.json"

function Read-RoundsHistory($path) {
    if (-not (Test-Path $path)) { return @{} }
    try {
        $raw = Get-Content -Path $path -Raw -ErrorAction Stop
        if ([string]::IsNullOrWhiteSpace($raw)) { return @{} }
        $obj = $raw | ConvertFrom-Json -ErrorAction Stop
        $h = @{}
        foreach ($p in $obj.PSObject.Properties) { $h[$p.Name] = [int]$p.Value }
        return $h
    } catch {
        return @{}
    }
}

function Write-RoundsHistory($history, $path) {
    try {
        $tmp = "$path.tmp"
        ($history | ConvertTo-Json -Compress) | Set-Content -Path $tmp -Encoding utf8 -NoNewline
        Move-Item -Path $tmp -Destination $path -Force
    } catch { }
}

function Update-RoundsHistory($allToday, $todayUtcDate, $path) {
    $history = Read-RoundsHistory $path

    # Idempotency: zero today's keys before recounting (heartbeats can fire multiple times per hour)
    $todayPrefix = "${todayUtcDate}T"
    foreach ($key in @($history.Keys)) {
        if ($key.StartsWith($todayPrefix)) { $history.Remove($key) }
    }

    foreach ($r in $allToday) {
        if ($null -ne $r.hour) {
            $key = "$todayUtcDate" + "T" + ("{0:D2}" -f [int]$r.hour)
            if ($history.ContainsKey($key)) { $history[$key] = [int]$history[$key] + 1 }
            else { $history[$key] = 1 }
        }
    }

    $cutoffDate = (Get-Date).ToUniversalTime().AddDays(-30).ToString("yyyy-MM-dd")
    foreach ($key in @($history.Keys)) {
        if ($key.Length -ge 10 -and $key.Substring(0, 10) -lt $cutoffDate) {
            $history.Remove($key)
        }
    }

    Write-RoundsHistory $history $path
    return $history
}

function Get-LogTail($path, $n = 100) {
    if (-not (Test-Path $path)) { return ,@() }
    $result = New-Object System.Collections.ArrayList
    try {
        $lines = @(Get-Content -Path $path -Tail $n -ErrorAction Stop)
        foreach ($line in $lines) {
            $clean = $line -replace "`e\[[0-9;]*m", ""
            if ($clean.Length -gt 500) { $clean = $clean.Substring(0, 500) }
            [void]$result.Add($clean)
        }
    } catch { }
    return ,$result.ToArray()
}

function Get-DockerProcessInfo($containerName) {
    # Resolve Capsule + Protocol PIDs and container uptime from `docker top` / `docker inspect`.
    # Returns null if container isn't running. Used when the FortyTwo node lives in a Docker
    # container instead of native processes on the host.
    $result = @{
        capsulePid       = $null
        protocolPid      = $null
        capsuleAlive     = $false
        protocolAlive    = $false
        uptimeSeconds    = $null
    }
    if (-not $containerName) { return $result }
    try {
        $running = (& docker inspect --format='{{.State.Running}}' $containerName 2>$null) -join ''
        if ($running.Trim() -ne 'true') { return $result }

        $startedAt = (& docker inspect --format='{{.State.StartedAt}}' $containerName 2>$null) -join ''
        if ($startedAt) {
            try {
                $start = [DateTimeOffset]::Parse($startedAt.Trim()).UtcDateTime
                $result.uptimeSeconds = [int]((Get-Date).ToUniversalTime() - $start).TotalSeconds
            } catch { }
        }

        $topOut = & docker top $containerName 2>$null
        if ($topOut) {
            foreach ($line in ($topOut -split "`n")) {
                if ($line -match "FortytwoCapsule") {
                    $cols = ($line -split '\s+') | Where-Object { $_ -ne '' }
                    foreach ($c in $cols) { if ($c -match '^\d+$') { $result.capsulePid = [int]$c; $result.capsuleAlive = $true; break } }
                }
                if ($line -match "FortytwoProtocol") {
                    $cols = ($line -split '\s+') | Where-Object { $_ -ne '' }
                    foreach ($c in $cols) { if ($c -match '^\d+$') { $result.protocolPid = [int]$c; $result.protocolAlive = $true; break } }
                }
            }
        }
    } catch { }
    return $result
}

function Get-GpuInfo {
    # Primary path: nvidia-smi (FortyTwo node = LLM inference = typically NVIDIA)
    $gpuName = $null; $vramUsed = $null; $vramTotal = $null
    try {
        $out = & nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader,nounits 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $first = ($out -split "`n")[0]
            $parts = $first -split ',\s*'
            if ($parts.Count -ge 3) {
                $gpuName   = $parts[0].Trim()
                $vramUsed  = [int]$parts[1].Trim()
                $vramTotal = [int]$parts[2].Trim()
            }
        }
    } catch { }
    # Fallback: WMI for the name on non-NVIDIA boxes (VRAM via WMI is unreliable)
    if (-not $gpuName) {
        try {
            $g = Get-CimInstance Win32_VideoController -ErrorAction Stop | Select-Object -First 1
            if ($g) { $gpuName = $g.Name }
        } catch { }
    }
    return @{ name = $gpuName; used = $vramUsed; total = $vramTotal }
}

function Get-NodeSnapshot {
    $todayUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")

    $todayLines = @()
    if (Test-Path $ExtLog) {
        $todayLines = Select-String -Path $ExtLog -Pattern "^UTC $todayUtc" | ForEach-Object { $_.Line }
    }

    $participations = @($todayLines | Where-Object { $_ -match "Completed inference participation" }).Count
    $roundLines     = @($todayLines | Where-Object { $_ -match "Inference round.*Total time" })
    $observed       = $roundLines.Count
    # Exclude transport-layer noise (Kademlia bootstrap timeouts, peer Identify timeouts) — counts only inference-relevant errors
    $errorLines = @($todayLines | Where-Object {
        $_ -match " ERROR " -and
        $_ -notmatch "Kademlia bootstrap is timeout" -and
        $_ -notmatch "Identify: error with peer"
    })
    $errors = $errorLines.Count

    $firstRound = $null; $lastRound = $null; $lastDuration = $null
    if ($roundLines.Count -gt 0) {
        if ($roundLines[0] -match "(\d{2}:\d{2}:\d{2})") { $firstRound = $matches[1] }
        if ($roundLines[-1] -match "(\d{2}:\d{2}:\d{2}).*Total time: (\d+)s") {
            $lastRound = $matches[1]
            $lastDuration = [int]$matches[2]
        }
    }

    $allToday = @()
    foreach ($line in $roundLines) {
        if ($line -match "(\d{2}):(\d{2}):(\d{2}).*Inference round (\w+) completed.*Total time: (\d+)s") {
            $allToday += [ordered]@{
                completed_iso = ("{0}:{1}:{2}" -f $matches[1], $matches[2], $matches[3])
                hour          = [int]$matches[1]
                hash          = $matches[4]
                duration_s    = [int]$matches[5]
            }
        }
    }
    # newest-first list of last 5 for backward compat / /recent command
    $recent = @()
    foreach ($r in ($allToday | Select-Object -Last 5)) { $recent += $r }
    [array]::Reverse($recent)

    # Last 3 errors, newest-first, with timestamp + message
    $recentErrors = @()
    foreach ($line in ($errorLines | Select-Object -Last 3)) {
        $iso = $null
        if ($line -match "(\d{2}:\d{2}:\d{2})") { $iso = $matches[1] }
        $msg = $line -replace "^UTC \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\s*", ""
        $msg = $msg -replace "`e\[[0-9;]*m", ""
        if ($msg.Length -gt 500) { $msg = $msg.Substring(0, 500) }
        $recentErrors += [ordered]@{ iso = $iso; message = $msg }
    }
    if ($recentErrors.Count -gt 1) { [array]::Reverse($recentErrors) }

    # TPS/symbols capability lines emitted by the Capsule throughout the day:
    #   ... has max tokens per second: N, max symbols per second: N, max tokens size: N, max symbols size: N
    # The LATEST line = current capability. The HIGHEST seen across the log = all-time max.
    $maxTps = $null; $maxSymbols = $null
    $tpsCurrent = $null; $symbolsCurrent = $null
    if (Test-Path $ExtLog) {
        $capLines = Select-String -Path $ExtLog -Pattern "has max tokens per second:\s*(\d+),?\s*max symbols per second:\s*(\d+)"
        foreach ($m in $capLines) {
            $tps = [int]$m.Matches[0].Groups[1].Value
            $sym = [int]$m.Matches[0].Groups[2].Value
            if ($null -eq $maxTps -or $tps -gt $maxTps) { $maxTps = $tps }
            if ($null -eq $maxSymbols -or $sym -gt $maxSymbols) { $maxSymbols = [double]$sym }
        }
        if ($capLines.Count -gt 0) {
            $last = $capLines[-1]
            $tpsCurrent     = [double]$last.Matches[0].Groups[1].Value
            $symbolsCurrent = [double]$last.Matches[0].Groups[2].Value
        }
    }

    # Find the most recent POSITIVE reward (Protocol logs balance pairs even when delta is 0)
    $lastReward = $null; $lastRewardTime = $null
    if (Test-Path $ExtLog) {
        $balanceLines = Select-String -Path $ExtLog -Pattern "FOR balance (before|after) reward" | Select-Object -Last 200
        # Walk in pairs from newest to oldest; first pair with after > before wins
        for ($i = $balanceLines.Count - 1; $i -ge 1; $i--) {
            $after = $balanceLines[$i].Line
            $before = $balanceLines[$i-1].Line
            if ($after -match "balance after reward: (\d+\.?\d*)" -and $before -match "balance before reward: (\d+\.?\d*)") {
                $afterVal  = [double]([regex]::Match($after,  "balance after reward: (\d+\.?\d*)").Groups[1].Value)
                $beforeVal = [double]([regex]::Match($before, "balance before reward: (\d+\.?\d*)").Groups[1].Value)
                if ($afterVal -gt $beforeVal) {
                    $lastReward = [math]::Round($afterVal - $beforeVal, 6)
                    if ($after -match "(\d{2}:\d{2}:\d{2})") { $lastRewardTime = $matches[1] }
                    break
                }
            }
        }
    }

    # Sum + count of positive reward deltas in today's log
    $rewardsTodayTotal = $null
    $winsToday = 0
    $todayBalanceLines = @($todayLines | Where-Object { $_ -match "FOR balance (before|after) reward" })
    if ($todayBalanceLines.Count -ge 2) {
        $totalSum = 0.0
        for ($i = 1; $i -lt $todayBalanceLines.Count; $i++) {
            $before = $todayBalanceLines[$i-1]
            $after  = $todayBalanceLines[$i]
            if ($before -match "balance before reward: (\d+\.?\d*)" -and $after -match "balance after reward: (\d+\.?\d*)") {
                $beforeVal = [double]([regex]::Match($before, "balance before reward: (\d+\.?\d*)").Groups[1].Value)
                $afterVal  = [double]([regex]::Match($after,  "balance after reward: (\d+\.?\d*)").Groups[1].Value)
                if ($afterVal -gt $beforeVal) {
                    $totalSum += ($afterVal - $beforeVal)
                    $winsToday += 1
                }
            }
        }
        if ($totalSum -gt 0) { $rewardsTodayTotal = [math]::Round($totalSum, 6) }
    }

    $model = $null; $modelShort = $null
    if (Test-Path $CapsuleLog) {
        $modelLine = Select-String -Path $CapsuleLog -Pattern "Using local LLM model: (.+)$" | Select-Object -Last 1
        if ($modelLine) {
            $model = $modelLine.Matches[0].Groups[1].Value.Trim() -replace "`e\[[0-9;]*m", ""
            $modelShort = Split-Path $model -Leaf
        } else {
            $hfLine = Select-String -Path $CapsuleLog -Pattern "--llm-hf-model-name\s+(\S+)" | Select-Object -Last 1
            if ($hfLine) {
                $modelShort = $hfLine.Matches[0].Groups[1].Value
                $model = $modelShort
            }
        }
    }

    # Process detection: Docker container if -DockerContainer set, else native host processes.
    $capPid = $null; $protoPid = $null; $capUptime = $null
    $dockerProtoAlive = $false
    if ($DockerContainer) {
        $dockerInfo = Get-DockerProcessInfo $DockerContainer
        $capPid           = $dockerInfo.capsulePid
        $protoPid         = $dockerInfo.protocolPid
        $capUptime        = $dockerInfo.uptimeSeconds   # container uptime (proxy for capsule uptime)
        $dockerProtoAlive = $dockerInfo.protocolAlive
    } else {
        $cap   = Get-Process FortytwoCapsule  -ErrorAction SilentlyContinue
        $proto = Get-Process FortytwoProtocol -ErrorAction SilentlyContinue
        $capPid   = if ($cap)   { $cap.Id }   else { $null }
        $protoPid = if ($proto) { $proto.Id } else { $null }
        if ($cap -and $cap.StartTime) {
            $capUptime = [int]((Get-Date) - $cap.StartTime).TotalSeconds
        }
        $dockerProtoAlive = [bool]$proto
    }

    # Capsule + Protocol versions from Capsule.log header lines
    $capsuleVersion = $null; $protocolVersion = $null
    if (Test-Path $CapsuleLog) {
        $vLine = Select-String -Path $CapsuleLog -Pattern "Fortytwo Capsule current version: (\S+)" | Select-Object -Last 1
        if ($vLine) { $capsuleVersion = $vLine.Matches[0].Groups[1].Value.Trim() }
    }
    # Protocol writes version banner at extended_log.txt startup; pattern observed in logs
    if (Test-Path $ExtLog) {
        $pvLine = Select-String -Path $ExtLog -Pattern "(?:Protocol version|protocol.+version)[:\s]+v?(\d+\.\d+\.\d+)" | Select-Object -Last 1
        if ($pvLine) { $protocolVersion = $pvLine.Matches[0].Groups[1].Value }
    }

    $capsuleAlive = $false
    try {
        $r = Invoke-WebRequest -Uri $ReadyUrl -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $capsuleAlive = $true }
    } catch { $capsuleAlive = $false }
    $protocolAlive = $dockerProtoAlive

    # Rolling 30-day rounds history (persisted to rounds-history.json next to this script)
    $roundsHistory = Update-RoundsHistory $allToday $todayUtc $RoundsHistoryFile

    # GPU + VRAM (nvidia-smi primary, WMI fallback for name only)
    $gpu = Get-GpuInfo

    # Tail last 100 lines of each log
    $logExtended = Get-LogTail $ExtLog 500
    $logCapsule  = Get-LogTail $CapsuleLog 500

    return [ordered]@{
        ts                          = (Get-Date).ToUniversalTime().ToString("o")
        model                       = $model
        model_short                 = $modelShort
        capsule_max_tps             = $maxTps
        capsule_version             = $capsuleVersion
        protocol_version            = $protocolVersion
        capsule_uptime_seconds      = $capUptime
        rounds_participated_today   = $participations
        rounds_observed_today       = $observed
        errors_today                = $errors
        first_round_today_iso       = $firstRound
        last_round_today_iso        = $lastRound
        last_round_duration_s       = $lastDuration
        last_reward_amount          = $lastReward
        last_reward_iso             = $lastRewardTime
        rewards_today_total         = $rewardsTodayTotal
        wins_today                  = $winsToday
        tps_current                 = $tpsCurrent
        symbols_current             = $symbolsCurrent
        max_symbols                 = $maxSymbols
        gpu_name                    = $gpu.name
        gpu_vram_used_mb            = $gpu.used
        gpu_vram_total_mb           = $gpu.total
        capsule_pid                 = $capPid
        protocol_pid                = $protoPid
        capsule_alive               = $capsuleAlive
        protocol_alive              = $protocolAlive
        recent_rounds               = $recent
        all_rounds_today            = $allToday
        rounds_history              = $roundsHistory
        recent_errors               = $recentErrors
        log_extended                = @($logExtended)
        log_capsule                 = @($logCapsule)
    }
}

function Post-Snapshot($snap) {
    $body = $snap | ConvertTo-Json -Depth 6 -Compress
    $headers = @{
        Authorization  = "Bearer $AgentToken"
        "Content-Type" = "application/json"
    }
    $url = "$($BotUrl.TrimEnd('/'))/v1/status"
    try {
        $r = Invoke-WebRequest -Uri $url -Method POST -Body $body -Headers $headers -UseBasicParsing -TimeoutSec 10
        $tag = if ($r.StatusCode -eq 200) { "ok" } else { "HTTP $($r.StatusCode)" }
        Write-Output ("[{0}] push {1}: participations={2} model={3} alive={4}/{5}" -f `
            (Get-Date -Format "HH:mm:ss"), $tag, $snap.rounds_participated_today, $snap.model_short, $snap.capsule_alive, $snap.protocol_alive)
    } catch {
        Write-Output ("[{0}] push exception: {1}" -f (Get-Date -Format "HH:mm:ss"), $_.Exception.Message)
    }
}

if ($DryRun) {
    $snap = Get-NodeSnapshot
    $snap | ConvertTo-Json -Depth 6
    return
}

if ($Once) {
    Post-Snapshot (Get-NodeSnapshot)
    return
}

Write-Output "Fortytwo agent starting. Mode: event-driven + ${HeartbeatSeconds}s heartbeat. Bot URL: $BotUrl"

# Bootstrap push so the bot has fresh data immediately on agent start
$lastPushTime = [DateTime]::MinValue
try {
    Post-Snapshot (Get-NodeSnapshot)
    $lastPushTime = Get-Date
} catch {
    Write-Output ("[bootstrap] " + $_.Exception.Message)
}

# Initial file position: skip existing content, only push on NEW events
$lastPos = if (Test-Path $ExtLog) { (Get-Item $ExtLog).Length } else { 0 }

$HeartbeatSeconds    = 30
$PollIntervalSeconds = 5
$EventPattern = "Completed inference participation|Inference round \w+ completed.*Total time"

while ($true) {
    Start-Sleep -Seconds $PollIntervalSeconds

    # Heartbeat (so bot snapshots survive its redeploys / silent periods)
    if (((Get-Date) - $lastPushTime).TotalSeconds -ge $HeartbeatSeconds) {
        $now = Get-Date -Format "HH:mm:ss"
        Write-Output "[$now] heartbeat push"
        try {
            Post-Snapshot (Get-NodeSnapshot)
            $lastPushTime = Get-Date
        } catch {
            Write-Output ("[heartbeat] " + $_.Exception.Message)
        }
    }

    if (-not (Test-Path $ExtLog)) { continue }
    $currentSize = (Get-Item $ExtLog).Length
    if ($currentSize -lt $lastPos) { $lastPos = 0 }  # rotated / truncated
    if ($currentSize -le $lastPos) { continue }

    # Read new bytes from $lastPos to EOF
    try {
        $fs = [System.IO.File]::Open(
            $ExtLog,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite
        )
        $fs.Position = $lastPos
        $sr = New-Object System.IO.StreamReader($fs)
        $newContent = $sr.ReadToEnd()
        $lastPos = $fs.Position
        $sr.Close(); $fs.Close()
    } catch {
        Write-Output ("[read] " + $_.Exception.Message)
        continue
    }

    foreach ($line in ($newContent -split "`n")) {
        if ($line -match $EventPattern) {
            $now = Get-Date -Format "HH:mm:ss"
            Write-Output "[$now] inference event - pushing snapshot"
            try {
                Post-Snapshot (Get-NodeSnapshot)
                $lastPushTime = Get-Date
            } catch {
                Write-Output ("[event push] " + $_.Exception.Message)
            }
        }
    }
}
