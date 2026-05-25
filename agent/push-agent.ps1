param(
    [string]$BotUrl = $env:FORTYTWO_BOT_URL,
    [string]$AgentToken = $env:FORTYTWO_AGENT_TOKEN,
    [int]$IntervalSeconds = 30,
    [Parameter(Mandatory=$true)]
    [string]$ScriptsRoot,
    [string]$DockerContainer = $env:FORTYTWO_DOCKER_CONTAINER,
    [switch]$Once,
    [switch]$DryRun,
    [switch]$NoAutoUpdate   # disable git ls-remote/pull cycle entirely
)

if (-not $DryRun) {
    if (-not $BotUrl) { throw "FORTYTWO_BOT_URL env not set (or pass -BotUrl, or use -DryRun)" }
    if (-not $AgentToken) { throw "FORTYTWO_AGENT_TOKEN env not set (or pass -AgentToken, or use -DryRun)" }
}

$ExtLog          = Join-Path $ScriptsRoot "extended_log.txt"
$CapsuleLog      = Join-Path $ScriptsRoot "FortytwoNode\debug\FortytwoCapsule.log"
$ReadyUrl        = "http://localhost:42442/ready"
$RoundsHistoryFile = Join-Path $PSScriptRoot "rounds-history.json"
# Repo root: this script lives in <repo>/agent/, so parent of $PSScriptRoot is the repo.
# Used by the auto-update cycle to run git from the correct working dir.
$RepoRoot = Split-Path $PSScriptRoot -Parent

# Auto-update cadence: minutes between `git ls-remote` checks. 0 disables.
# Resolution order: explicit -NoAutoUpdate switch wins, then env override, then default.
$AutoUpdateMinutes = if ($NoAutoUpdate) {
    0
} elseif ($env:FORTYTWO_AUTOUPDATE_MINUTES) {
    try { [int]$env:FORTYTWO_AUTOUPDATE_MINUTES } catch { 30 }
} else {
    30
}

function Get-AgentVersion {
    # Short SHA of the current HEAD. Returns $null if git fails or this isn't a checkout.
    try {
        $sha = & git -C $RepoRoot rev-parse --short HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $sha) { return $sha.Trim() }
    } catch { }
    return $null
}

function Invoke-AutoUpdateCheck {
    # Compare local HEAD to origin/main; if different, ff-only pull and exit so the
    # scheduled task respawns us on the new code. Failures are logged and ignored --
    # an RPC blip or local divergence must never crash the monitor.
    if ($AutoUpdateMinutes -le 0) { return }
    $now = Get-Date -Format "HH:mm:ss"
    try {
        $remoteOut = & git -C $RepoRoot ls-remote origin main 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $remoteOut) {
            Write-Output "[$now] auto-update: ls-remote failed (skipping this cycle)"
            return
        }
        $remoteSha = ($remoteOut -split "\s+")[0]
        $localSha  = (& git -C $RepoRoot rev-parse HEAD 2>$null).Trim()
        if (-not $remoteSha -or -not $localSha) { return }
        if ($remoteSha -eq $localSha) { return }
        $remoteShort = $remoteSha.Substring(0, 7)
        Write-Output "[$now] auto-update: remote $remoteShort differs from local, pulling..."
        $pullOut = & git -C $RepoRoot pull --ff-only 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Output "[$now] auto-update: pulled, killing any stray push-agent processes then exiting to restart with new code"
            # Defensive sibling-process cleanup: if a previous restart left
            # a stale copy of push-agent.ps1 running (rare but seen during
            # earlier debugging), it'd keep posting old-code snapshots over
            # the fresh respawn's. Kill any sibling powershell.exe whose
            # command line references this script before exiting ourselves.
            try {
                $myPid = $PID
                $strays = Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
                          Where-Object {
                              $_.ProcessId -ne $myPid -and
                              ($_.CommandLine -like '*push-agent.ps1*' -or $_.CommandLine -like '*_agent-wrapper*')
                          }
                foreach ($p in $strays) {
                    Write-Output ("[{0}] auto-update: killing stray PID {1}" -f $now, $p.ProcessId)
                    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                }
            } catch { }
            exit 0   # Scheduled Task "restart on failure" respawns with new code
        } else {
            Write-Output ("[{0}] auto-update: git pull --ff-only failed (probably local divergence) -- staying on current code. Output: {1}" -f $now, ($pullOut -join ' '))
        }
    } catch {
        Write-Output ("[{0}] auto-update: exception {1} (skipping this cycle)" -f $now, $_.Exception.Message)
    }
}

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

    # Pre-scan: collect round hashes the node DECIDED to participate in.
    # v9 primary marker: "Capsule has decided to participate in inference
    # request <hash>" fires only when the decision is yes and carries the
    # round hash directly. (The older "Completed inference participation"
    # line, which has no hash, was removed by a recent Capsule update.)
    $decidedHashes = New-Object System.Collections.Generic.HashSet[string]
    foreach ($line in $todayLines) {
        if ($line -match "Capsule has decided to participate in inference request (\w{40,})") {
            [void]$decidedHashes.Add($matches[1])
        }
    }
    # Initial count from the legacy END-of-round marker (now ~0 in modern
    # logs). Recomputed below from the per-round `participated` tag after
    # all_today is built so the count matches what's tagged.
    $participations = @($todayLines | Where-Object { $_ -match "Completed inference participation" }).Count
    $roundLines     = @($todayLines | Where-Object { $_ -match "Inference round.*Total time" })
    $observed       = $roundLines.Count
    # Exclude transport-layer noise (Kademlia bootstrap timeouts, peer Identify timeouts) -- counts only inference-relevant errors
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

    # Walk today_lines in order, building all_today with two pieces of
    # state:
    #   - $lastReceiptHash: paired with the next round-completed line as
    #     tx_hash (legacy data from when older Capsule versions still
    #     emitted "Resolution of ... receipt hash 0x...").
    #   - $pendingRoundIdx: the index in $allToday of the most recent
    #     "Inference round X completed" line. When we subsequently see
    #     "Completed inference participation" (the END-of-round marker
    #     that fires only for true participations, no hash), we tag that
    #     round's dict participated=True.
    #
    # Note: "Completed inference participation" is the authoritative
    # marker -- it's what $participations already counts. The earlier
    # "Participating in inference request <hash>" line fires for EVERY
    # round the node sees (observer too), so it can't be used to tag
    # specific participations.
    $allToday = New-Object System.Collections.ArrayList
    $lastReceiptHash = $null
    $pendingRoundIdx = -1
    foreach ($line in $todayLines) {
        if ($line -match "receipt hash (0x[0-9a-fA-F]+)") {
            $lastReceiptHash = $matches[1]
            continue
        }
        if ($line -match "(\d{2}):(\d{2}):(\d{2}).*Inference round (\w+) completed.*Total time: (\d+)s") {
            $roundHash = $matches[4]
            $entry = [ordered]@{
                completed_iso = ("{0}:{1}:{2}" -f $matches[1], $matches[2], $matches[3])
                hour          = [int]$matches[1]
                hash          = $roundHash
                duration_s    = [int]$matches[5]
                tx_hash       = $lastReceiptHash
                participated  = $false   # promoted to $true by the END-of-round marker
            }
            [void]$allToday.Add($entry)
            $pendingRoundIdx = $allToday.Count - 1
            $lastReceiptHash = $null
            continue
        }
        if ($line -match "Completed inference participation" -and $pendingRoundIdx -ge 0) {
            $allToday[$pendingRoundIdx]["participated"] = $true
            $pendingRoundIdx = -1
        }
    }
    # v9 primary marker: union $decidedHashes into per-round participated tag.
    foreach ($entry in $allToday) {
        if ($decidedHashes.Contains($entry["hash"])) {
            $entry["participated"] = $true
        }
    }
    $allToday = @($allToday)  # convert back to plain array for downstream consumers

    # Recompute participations from the per-round tag (legacy
    # "Completed inference participation" line is ~0 in modern logs, so the
    # initial count from before would under-report). wins_today below
    # already mirrors this.
    $participations = @($allToday | Where-Object { $_.participated }).Count
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

    # Reward parser -- full-file scan + windowed pairing.
    # Why: the old `$todayLines` filter dropped any balance line that didn't
    # start with `UTC YYYY-MM-DD`, and the strict consecutive-pair loop
    # desynced permanently the moment ONE line was lost. Both undercounted
    # wins_today / rewards_today_total.
    # New approach:
    #   - Scan the whole file for ALL balance lines (no prefix filter).
    #   - For each, extract date + time from `UTC YYYY-MM-DD HH:MM:SS`
    #     anywhere in the line (lines without that pattern are skipped).
    #   - Pair each `after` with the nearest preceding `before` within
    #     a 5-line window.
    #   - Sum positive deltas where the after-line's date == today_utc.
    $lastReward = $null; $lastRewardTime = $null
    $rewardsTodayTotal = $null
    # rewardsLoggedToday = positive-delta pairs (rewards captured inside the
    # Capsule's ~7-second balance-before/after snapshot window). This is a
    # subset of participations -- the rest of the rewards land on-chain
    # outside the snapshot window and are visible via chain_rewards on the bot.
    $rewardsLoggedToday = 0
    if (Test-Path $ExtLog) {
        $allBal = Select-String -Path $ExtLog -Pattern "FOR balance (before|after) reward" | ForEach-Object { $_.Line }
        # Build a parsed list: [{ kind, value, date, time, raw }]
        $parsed = New-Object System.Collections.ArrayList
        foreach ($ln in $allBal) {
            $kind = $null; $value = $null; $date = $null; $time = $null
            if     ($ln -match "balance before reward:\s*(\d+\.?\d*)") { $kind = "before"; $value = [double]$matches[1] }
            elseif ($ln -match "balance after reward:\s*(\d+\.?\d*)")  { $kind = "after";  $value = [double]$matches[1] }
            else { continue }
            if ($ln -match "UTC (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})") {
                $date = $matches[1]; $time = $matches[2]
            }
            [void]$parsed.Add([pscustomobject]@{ kind=$kind; value=$value; date=$date; time=$time; raw=$ln })
        }

        $totalSum = 0.0
        for ($i = 0; $i -lt $parsed.Count; $i++) {
            if ($parsed[$i].kind -ne "after") { continue }
            $afterVal = $parsed[$i].value
            $beforeVal = $null
            $lookback = [Math]::Max(0, $i - 5)
            for ($j = $i - 1; $j -ge $lookback; $j--) {
                if ($parsed[$j].kind -eq "before") { $beforeVal = $parsed[$j].value; break }
            }
            if ($null -eq $beforeVal) { continue }
            if ($afterVal -le $beforeVal) { continue }
            # Only trust deltas with a parseable date -- otherwise the line may
            # be a stray fragment and would pollute lastReward.
            if (-not $parsed[$i].date) { continue }
            $delta = $afterVal - $beforeVal
            # Last reward -- most recent dated positive delta (across all dates).
            $lastReward = [math]::Round($delta, 6)
            $lastRewardTime = $parsed[$i].time
            # Today's totals
            if ($parsed[$i].date -eq $todayUtc) {
                $totalSum += $delta
                $rewardsLoggedToday += 1
            }
        }
        if ($totalSum -gt 0) { $rewardsTodayTotal = [math]::Round($totalSum, 6) }
    }
    # wins_today now mirrors participations -- every round the node participated
    # in counts as a win (rewards land on-chain async, often outside the
    # Capsule's snapshot window, so a positive-delta count under-reports wins).
    $winsToday = $participations

    $model = $null; $modelShort = $null; $modelSizeGb = $null
    # v9.1 diagnostic — exposed on snapshot so we can see why model_size_gb
    # is null without asking the operator to run ad-hoc PS commands.
    $modelDebug = [ordered]@{ direct_tried = $null; cache_path = $null; cache_exists = $false; subdirs_seen = 0; found_at = $null; size_bytes = $null; error = $null }
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
    # Model file size on disk (GB).
    # The Capsule's "Using local LLM model: <path>" line may give a bare
    # filename or a full path. On the user's install the GGUF lives in an
    # HF cache layout like
    # <ScriptsRoot>\FortytwoNode\model_cache\models--<org>--<repo>\snapshots\<sha>\<file>.gguf
    # The <sha> changes between model updates so we can't hardcode it.
    #
    # v8.9 strategy: walk the HF cache layout EXPLICITLY (no -Recurse).
    # v8.7's -Recurse approach silently returned nothing on this setup,
    # likely because Get-ChildItem -Recurse was descending into the
    # blobs/ subdir and an error mid-walk aborted the enumeration. The
    # explicit walk only enumerates 3 directory levels and never
    # touches blobs/. Falls back to v8.7's recursive search under
    # ScriptsRoot as a last resort if the HF layout doesn't match.
    if ($model) {
        $modelPath = $null
        $modelDebug.direct_tried = $model
        if (Test-Path -LiteralPath $model)                              { $modelPath = $model }
        elseif (Test-Path -LiteralPath (Join-Path $ScriptsRoot $model)) { $modelPath = (Join-Path $ScriptsRoot $model) }
        # Explicit walk: model_cache -> models--*/ -> snapshots/ -> <sha>/ -> <file>
        if (-not $modelPath -and $modelShort) {
            $cachePath = Join-Path $ScriptsRoot "FortytwoNode\model_cache"
            $modelDebug.cache_path = $cachePath
            if (Test-Path -LiteralPath $cachePath) {
                $modelDebug.cache_exists = $true
                $dirs = @(Get-ChildItem -LiteralPath $cachePath -Directory -ErrorAction SilentlyContinue)
                $modelDebug.subdirs_seen = $dirs.Count
                foreach ($modelDir in $dirs) {
                    $snapsDir = Join-Path $modelDir.FullName "snapshots"
                    if (-not (Test-Path -LiteralPath $snapsDir)) { continue }
                    foreach ($shaDir in @(Get-ChildItem -LiteralPath $snapsDir -Directory -ErrorAction SilentlyContinue)) {
                        $maybe = Join-Path $shaDir.FullName $modelShort
                        if (Test-Path -LiteralPath $maybe) {
                            $modelPath = $maybe
                            break
                        }
                    }
                    if ($modelPath) { break }
                }
            }
        }
        # Last resort: full recursive search under ScriptsRoot (slow but
        # catches non-HF layouts -- e.g. user manually placed the model).
        if (-not $modelPath -and $modelShort) {
            try {
                $hit = Get-ChildItem -LiteralPath $ScriptsRoot -Recurse -File -ErrorAction SilentlyContinue |
                       Where-Object { $_.Name -eq $modelShort -and $_.Length -gt 0 } |
                       Select-Object -First 1
                if ($hit) { $modelPath = $hit.FullName }
            } catch { $modelDebug.error = "recursive fallback: $($_.Exception.Message)" }
        }
        if ($modelPath) {
            $modelDebug.found_at = $modelPath
            try {
                $size = (Get-Item -LiteralPath $modelPath).Length
                $modelDebug.size_bytes = $size
                if ($size -gt 0) { $modelSizeGb = [math]::Round($size / 1GB, 2) }
            } catch { $modelDebug.error = "Get-Item: $($_.Exception.Message)" }
        }
    }

    # Process detection: Docker container if -DockerContainer set, else native host processes.
    # `Select-Object -First 1` makes `$cap` a single object instead of an array if
    # multiple FortytwoCapsule processes happen to exist -- otherwise `$cap.StartTime`
    # is an array and the `(Get-Date) - $cap.StartTime` arithmetic silently breaks,
    # which is what caused Uptime to be stuck at 0.
    $capPid = $null; $protoPid = $null; $capUptime = $null
    $dockerProtoAlive = $false
    if ($DockerContainer) {
        $dockerInfo = Get-DockerProcessInfo $DockerContainer
        $capPid           = $dockerInfo.capsulePid
        $protoPid         = $dockerInfo.protocolPid
        $capUptime        = $dockerInfo.uptimeSeconds   # container uptime (proxy for capsule uptime)
        $dockerProtoAlive = $dockerInfo.protocolAlive
    } else {
        $cap   = Get-Process FortytwoCapsule  -ErrorAction SilentlyContinue | Select-Object -First 1
        $proto = Get-Process FortytwoProtocol -ErrorAction SilentlyContinue | Select-Object -First 1
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
        agent_version               = (Get-AgentVersion)
        model                       = $model
        model_short                 = $modelShort
        model_size_gb               = $modelSizeGb
        model_debug                 = $modelDebug
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
        rewards_logged_today        = $rewardsLoggedToday
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

$HeartbeatSeconds    = 60   # 1 min floor. Inference-event pushes still fire immediately on round completion / participation.
$PollIntervalSeconds = 5
$EventPattern = "Completed inference participation|Inference round \w+ completed.*Total time"

$autoUpdateBanner = if ($AutoUpdateMinutes -gt 0) { "auto-update every ${AutoUpdateMinutes}m" } else { "auto-update disabled" }
Write-Output "Fortytwo agent starting. Mode: event-driven + ${HeartbeatSeconds}s heartbeat, $autoUpdateBanner. Bot URL: $BotUrl"

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
$lastUpdateCheck = Get-Date  # don't auto-update on the first cycle -- wait one interval

while ($true) {
    Start-Sleep -Seconds $PollIntervalSeconds

    # Auto-update check (every AutoUpdateMinutes). Runs git ls-remote / pull,
    # and exit 0 on a successful pull so the scheduled task respawns us on
    # the new code. Cheap (1 RPC per interval) and never crashes the agent.
    if ($AutoUpdateMinutes -gt 0 -and ((Get-Date) - $lastUpdateCheck).TotalMinutes -ge $AutoUpdateMinutes) {
        Invoke-AutoUpdateCheck
        $lastUpdateCheck = Get-Date
    }

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
