# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Sync-ErsPlan {
    <#
    .SYNOPSIS
        Queries Pure1 for the latest operation on each plan and updates
        the local state files — useful when operations were kicked off
        outside this module (e.g. via the GUI), or when state was lost.
    .EXAMPLE
        Sync-ErsPlan -ErsInstance $Ers
    .EXAMPLE
        Sync-ErsPlan -ErsInstance $Ers -Name plan1, plan2
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [string[]]$Name
    )

    if ($Name -and $Name.Count -gt 0) {
        $resolveNames = $Name
    } else {
        $allPlans = @(Invoke-ErsApiGetAll -ErsInstance $ErsInstance `
            -Path (Get-ErsPlansPath) `
            -BaseParams @{ deployment_id = $ErsInstance.DeploymentId })
        $resolveNames = @($allPlans | ForEach-Object { $_.name })
    }

    if ($resolveNames.Count -eq 0) {
        Write-Host 'No plans found to sync.'
        return
    }

    $resolved = Resolve-ErsPlans -ErsInstance $ErsInstance -Names $resolveNames
    if ($resolved.NotFound.Count -gt 0) {
        Write-Warning "Plans not found: $($resolved.NotFound -join ', ')"
    }
    if ($resolved.Matched.Count -eq 0) {
        Write-Host 'No matching plans — nothing to sync.'
        return
    }

    $opEndpoints = @(
        @{ Label = 'failover';  Path = Get-ErsFailoverPath;  TypeMap = @{ TEST = 'test_failover'; PROD = 'prod_failover' } }
        @{ Label = 'cleanup';   Path = Get-ErsCleanupPath;   TypeMap = @{ CLEANUP = 'cleanup' } }
        @{ Label = 'promotion'; Path = Get-ErsFbPromotePath;  TypeMap = @{ PROMOTION = 'failback' } }
    )

    $ops   = @{}
    $state = @{}

    Write-Host "`nSyncing operation state for $($resolved.Matched.Count) plan(s)...`n"
    Write-Host ("  {0,-30} {1,-20} {2,-16} {3}" -f 'Plan', 'Action', 'Status', 'Op ID')
    Write-Host ("  " + ('-' * 100))

    foreach ($plan in $resolved.Matched) {
        $planId   = $plan.id
        $planName = $plan.name
        $key      = $planName.ToLower()

        $bestOp     = $null
        $bestAction = $null
        $bestTime   = -1

        foreach ($ep in $opEndpoints) {
            try {
                $params = @{
                    offset            = 0
                    limit             = 5
                    deployment_id     = $ErsInstance.DeploymentId
                    recovery_plan_id  = $planId
                }
                $result = Invoke-ErsApiRequest -ErsInstance $ErsInstance `
                    -Method GET -Path $ep.Path -QueryParams $params
                foreach ($item in @($result.items)) {
                    $created = if ($item.created_at) { $item.created_at } else { 0 }
                    if ($created -gt $bestTime) {
                        $opType     = if ($item.type) { $item.type } else { '' }
                        $bestTime   = $created
                        $bestOp     = $item
                        $mapped     = $ep.TypeMap[$opType]
                        $bestAction = if ($mapped) { $mapped } else { $ep.Label }
                    }
                }
            } catch {
                # Endpoint may return empty for plans that never ran this action
            }
        }

        if ($bestOp) {
            $opId   = if ($bestOp.id) { $bestOp.id } else { '-' }
            $status = if ($bestOp.status) { $bestOp.status } else { 'UNKNOWN' }

            $ops[$key] = @{
                op_id       = $opId
                last_action = $bestAction
                plan_id     = $planId
                plan_name   = $planName
            }
            $state[$key] = @{
                last_action = $bestAction
                last_status = $status
                op_id       = $opId
            }
            Write-Host ("  {0,-30} {1,-20} {2,-16} {3}" -f $planName, $bestAction, $status, $opId)
        } else {
            Write-Host ("  {0,-30} {1,-20}" -f $planName, '(no operations)')
        }
    }

    if ($ops.Count -gt 0) {
        Set-ErsPlanOps -Ops $ops
    }
    if ($state.Count -gt 0) {
        $existingState = Get-ErsPlanState
        foreach ($k in $state.Keys) { $existingState[$k] = $state[$k] }
        Set-ErsPlanState -State $existingState
    }

    Write-Host "`n  State files updated ($($ops.Count) plan(s) synced)."
    Write-Host "  You can now run: Wait-ErsPlan -ErsInstance `$Ers -Name ..."
}
