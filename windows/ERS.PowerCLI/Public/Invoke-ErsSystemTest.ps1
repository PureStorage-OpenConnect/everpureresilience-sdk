# Copyright 2026 [Your Organization]
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

function Get-ErsSystemTestConfig {
    param([string]$Path = 'system-test-config.json')
    if (-not (Test-Path $Path)) {
        throw "System test config not found: $Path. Copy system-test-config.example.json to " +
              "system-test-config.json and fill in your site/group/plan names."
    }
    $cfg = Get-Content -Path $Path -Raw | ConvertFrom-Json -AsHashtable

    if ($cfg.schema_version -ne 1) {
        throw "$Path has unsupported schema_version '$($cfg.schema_version)' (supported: 1)"
    }
    $required = @('source_site', 'target_site', 'group_names', 'plan_names', 'vms_file')
    $missing = $required | Where-Object { -not $cfg.ContainsKey($_) -or -not $cfg[$_] }
    if ($missing) {
        throw "$Path is missing required fields: $($missing -join ', ')"
    }

    if (-not $cfg.ContainsKey('profile'))             { $cfg.profile = 'default' }
    if (-not $cfg.ContainsKey('failback_site'))        { $cfg.failback_site = $cfg.source_site }
    if (-not $cfg.ContainsKey('with_network'))          { $cfg.with_network = $true }
    if (-not $cfg.ContainsKey('with_tags'))             { $cfg.with_tags = $true }
    if (-not $cfg.ContainsKey('create_missing_tags'))    { $cfg.create_missing_tags = $false }
    if (-not $cfg.ContainsKey('interval'))               { $cfg.interval = 10 }
    if (-not $cfg.ContainsKey('max_polls'))              { $cfg.max_polls = 30 }

    return $cfg
}

function Invoke-ErsSystemTest {
    <#
    .SYNOPSIS
        Runs the ERS system test suite against your real Pure1 deployment
        and registered vCenter site(s) — no mocking. Wraps Pester with the
        same safety model as the Python SDK's system test runner.

        Level 1 — read-only: safe any time, no confirmation.
        Level 2 — real operations: prompts for confirmation. Tests tagged
                  Dangerous (prod failover, failback) are excluded by
                  default — pass -IncludeDangerous to run them too.
        Level 3 — full managed workflows: runs with dry_run=$true by
                  default (safe, no confirmation) even if selected — pass
                  -NoDryRun to actually execute them (also requires
                  -IncludeDangerous, since a live run is dangerous).

    .EXAMPLE
        Invoke-ErsSystemTest -Level 1 2 3 -ListTests
    .EXAMPLE
        Invoke-ErsSystemTest -Level 1
    .EXAMPLE
        Invoke-ErsSystemTest -Level 2
    .EXAMPLE
        Invoke-ErsSystemTest -Level 2 -IncludeDangerous -Yes
    .EXAMPLE
        Invoke-ErsSystemTest -Level 3
    .EXAMPLE
        Invoke-ErsSystemTest -Level 3 -NoDryRun -IncludeDangerous -Yes
    #>
    [CmdletBinding()]
    param(
        [string]$ConfigPath = 'system-test-config.json',
        [string]$ProfileName,
        [int[]]$Level = @(1),
        [switch]$IncludeDangerous,
        [switch]$NoDryRun,
        [switch]$Yes,
        [string]$Only,
        [switch]$ListTests
    )

    if (-not (Get-Module -ListAvailable -Name Pester | Where-Object { $_.Version -ge [version]'5.0.0' })) {
        throw "Pester 5+ is required. Install it with: Install-Module -Name Pester -MinimumVersion 5.0 -Force"
    }
    Import-Module Pester -MinimumVersion 5.0 -ErrorAction Stop

    $config = Get-ErsSystemTestConfig -Path $ConfigPath
    if ($ProfileName) { $config.profile = $ProfileName }
    $config.dry_run = -not $NoDryRun

    $moduleRoot = Split-Path -Parent $PSScriptRoot
    $testFiles = @()
    if (1 -in $Level) { $testFiles += Join-Path $moduleRoot 'Tests/SystemTests/Level1.List.Tests.ps1' }
    if (2 -in $Level) { $testFiles += Join-Path $moduleRoot 'Tests/SystemTests/Level2.Operations.Tests.ps1' }
    if (3 -in $Level) { $testFiles += Join-Path $moduleRoot 'Tests/SystemTests/Level3.Workflows.Tests.ps1' }
    if ($testFiles.Count -eq 0) {
        throw 'No tests match the given -Level.'
    }

    $excludeTags = @()
    if (-not $IncludeDangerous) { $excludeTags += 'Dangerous' }

    $level3Live = (3 -in $Level) -and $NoDryRun
    $needsConfirmation = (2 -in $Level) -or $level3Live
    $hasDangerous = $IncludeDangerous -and ((2 -in $Level) -or $level3Live)

    Write-Host "`n$('=' * 70)`n  ERS SYSTEM TEST — PRE-FLIGHT SUMMARY`n$('=' * 70)"
    Write-Host "  Profile        : $($config.profile)"
    Write-Host "  Source site    : $($config.source_site)"
    Write-Host "  Target site    : $($config.target_site)"
    Write-Host "  Failback site  : $($config.failback_site)"
    Write-Host "  Groups         : $($config.group_names -join ', ')"
    Write-Host "  Plans          : $($config.plan_names -join ', ')"
    Write-Host "  VMs file       : $($config.vms_file)"
    Write-Host "  Levels         : $($Level -join ', ')"
    if (3 -in $Level) {
        Write-Host "  Level 3 mode   : $(if ($level3Live) { 'LIVE (-NoDryRun)' } else { 'dry-run (safe)' })"
    }
    Write-Host "  Dangerous tests: $(if ($IncludeDangerous) { 'INCLUDED' } else { 'excluded (pass -IncludeDangerous to include)' })"

    if ($ListTests) {
        $previewConfig = New-PesterConfiguration
        $previewConfig.Run.Path = $testFiles
        $previewConfig.Run.Container = New-PesterContainer -Path $testFiles -Data @{ ErsInstance = $null; Config = $config }
        $previewConfig.Run.SkipRun = $true
        $previewConfig.Run.PassThru = $true
        $previewConfig.Filter.ExcludeTag = $excludeTags
        $discovery = Invoke-Pester -Configuration $previewConfig
        Write-Host "`nTests that would run:`n"
        foreach ($t in $discovery.Tests) { Write-Host "  $($t.ExpandedPath)" }
        return
    }

    if ($needsConfirmation -and -not $Yes) {
        Write-Host "`n  This will perform REAL operations against '$($config.source_site)' and '$($config.target_site)'."
        $response = Read-Host "  Type the source site name ('$($config.source_site)') to continue"
        if ($response -ne $config.source_site) {
            Write-Host '  Confirmation did not match — aborting.'
            return
        }
    }

    if ($hasDangerous -and -not $Yes) {
        Write-Host "`n  You have included DANGEROUS test(s) that run a REAL production failover/failback (not simulated)."
        $response = Read-Host "  Type the target site name ('$($config.target_site)') to confirm you want to proceed"
        if ($response -ne $config.target_site) {
            Write-Host '  Confirmation did not match — aborting.'
            return
        }
    }

    $ers = New-ErsInstance -ProfileName $config.profile
    Register-ErsSite -ErsInstance $ers -Name $config.source_site | Out-Null
    Register-ErsSite -ErsInstance $ers -Name $config.target_site | Out-Null

    $pesterConfig = New-PesterConfiguration
    $pesterConfig.Run.Container = New-PesterContainer -Path $testFiles -Data @{ ErsInstance = $ers; Config = $config }
    $pesterConfig.Filter.ExcludeTag = $excludeTags
    if ($Only) { $pesterConfig.Filter.FullName = "*$Only*" }
    $pesterConfig.Output.Verbosity = 'Detailed'

    $result = Invoke-Pester -Configuration $pesterConfig

    # Set $LASTEXITCODE (checkable by CI/scripts) WITHOUT calling exit — exit
    # terminates the whole PowerShell process/window, not just this function,
    # which is destructive when this cmdlet is run interactively.
    $global:LASTEXITCODE = if ($result.FailedCount -eq 0) { 0 } else { 1 }

    Write-Host "`n$(if ($result.FailedCount -eq 0) { 'All tests passed.' } else { "$($result.FailedCount) test(s) failed." })"
    return $result
}
