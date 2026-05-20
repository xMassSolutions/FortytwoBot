param(
    [string]$BotUrl = $env:FORTYTWO_BOT_URL,
    [string]$AgentToken = $env:FORTYTWO_AGENT_TOKEN,
    [int]$IntervalSeconds = 30,
    [string]$ScriptsRoot = "C:\Users\youruser\FortytwoCLI\fortytwo-p2p-inference-scripts-main",
    [switch]$Once,
    [switch]$DryRun
)

if (-not $DryRun) {
    if (-not $BotUrl) { throw "FORTYTWO_BOT_URL env not set (or pass -BotUrl, or use -DryRun)" }
    if (-not $AgentToken) { throw "FORTYTWO_AGENT_TOKEN env not set (or pass -AgentToken, or use -DryRun)" }
}

$ExtLog     = Join-Path $ScriptsRoot "extended_log.txt"
$CapsuleLog = Join-Path $ScriptsRoot "FortytwoNode\debug\FortytwoCapsule.log"
$ReadyUrl   = "http://localhost:42442/ready"

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
    $errors = @($todayLines | Where-Object {
        $_ -match " ERROR " -and
        $_ -notmatch "Kademlia bootstrap is timeout" -and
        $_ -notmatch "Identify: error with peer"
    }).Count

    $firstRound = $null; $lastRound = $null; $lastDuration = $null
    if ($roundLines.Count -gt 0) {
        if ($roundLines[0] -match "(\d{2}:\d{2}:\d{2})") { $firstRound = $matches[1] }
        if ($roundLines[-1] -match "(\d{2}:\d{2}:\d{2}).*Total time: (\d+)s") {
            $lastRound = $matches[1]
            $lastDuration = [int]$matches[2]
        }
    }

    $recent = @()
    foreach ($line in ($roundLines | Select-Object -Last 5)) {
        if ($line -match "(\d{2}:\d{2}:\d{2}).*Inference round (\w+) completed.*Total time: (\d+)s") {
            $recent += [ordered]@{
                completed_iso = $matches[1]
                hash          = $matches[2]
                duration_s    = [int]$matches[3]
            }
        }
    }
    [array]::Reverse($recent)  # newest first

    $maxTps = $null
    if (Test-Path $ExtLog) {
        $tpsLine = Select-String -Path $ExtLog -Pattern "has max tokens per second: (\d+)" | Select-Object -Last 1
        if ($tpsLine) { $maxTps = [int]$tpsLine.Matches[0].Groups[1].Value }
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

    $cap   = Get-Process FortytwoCapsule  -ErrorAction SilentlyContinue
    $proto = Get-Process FortytwoProtocol -ErrorAction SilentlyContinue
    $capPid   = if ($cap)   { $cap.Id }   else { $null }
    $protoPid = if ($proto) { $proto.Id } else { $null }

    $capsuleAlive = $false
    try {
        $r = Invoke-WebRequest -Uri $ReadyUrl -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $capsuleAlive = $true }
    } catch { $capsuleAlive = $false }
    $protocolAlive = [bool]$proto

    return [ordered]@{
        ts                          = (Get-Date).ToUniversalTime().ToString("o")
        model                       = $model
        model_short                 = $modelShort
        capsule_max_tps             = $maxTps
        rounds_participated_today   = $participations
        rounds_observed_today       = $observed
        errors_today                = $errors
        first_round_today_iso       = $firstRound
        last_round_today_iso        = $lastRound
        last_round_duration_s       = $lastDuration
        last_reward_amount          = $lastReward
        last_reward_iso             = $lastRewardTime
        capsule_pid                 = $capPid
        protocol_pid                = $protoPid
        capsule_alive               = $capsuleAlive
        protocol_alive              = $protocolAlive
        recent_rounds               = $recent
    }
}

function Post-Snapshot($snap) {
    $body = $snap | ConvertTo-Json -Depth 5 -Compress
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
    $snap | ConvertTo-Json -Depth 5
    return
}

Write-Output "Fortytwo agent starting. Push interval ${IntervalSeconds}s. Bot URL: $BotUrl"

do {
    try {
        $snap = Get-NodeSnapshot
        Post-Snapshot $snap
    } catch {
        Write-Output ("[{0}] snapshot exception: {1}" -f (Get-Date -Format "HH:mm:ss"), $_.Exception.Message)
    }
    if ($Once) { break }
    Start-Sleep -Seconds $IntervalSeconds
} while ($true)
