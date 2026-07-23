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

function Invoke-ErsManagedFailback {
    <#
    .SYNOPSIS
        Orchestrates a full failback: (optionally) captures tags, powers
        off target-side VMs, protects groups, runs failback on the plans,
        (optionally) applies tags to source-side VMs, (optionally)
        reconnects source-side VM networks. -ToSite doubles as the Pure1
        site name passed to Invoke-ErsPlanFailback.
    .EXAMPLE
        Invoke-ErsManagedFailback -ErsInstance $Ers -VmsFile vm-list.json `
            -GroupName G1, G2 -PlanName P1, P2 -FromSite dr-dc -ToSite prod-dc `
            -WithNetwork -WithTags -CreateMissingTags
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$VmsFile,
        [Parameter(Mandatory)][string[]]$GroupName,
        [Parameter(Mandatory)][string[]]$PlanName,
        [Parameter(Mandatory)][string]$FromSite,
        [Parameter(Mandatory)][string]$ToSite,
        [switch]$WithNetwork,
        [switch]$WithTags,
        [switch]$CreateMissingTags,
        [switch]$DryRun,
        [int]$IntervalSeconds = 10,
        [int]$MaxPolls = 30
    )

    if (-not $ErsInstance.Sites.ContainsKey($FromSite) -or -not $ErsInstance.Sites.ContainsKey($ToSite)) {
        Write-Host "Error: register both sites first — '$FromSite' and '$ToSite'"
        return $false
    }
    $src = $ErsInstance.Sites[$FromSite]
    $tgt = $ErsInstance.Sites[$ToSite]

    Write-ErsBanner 'MANAGED FAILBACK'
    Write-Host "  Plans     : $($PlanName -join ', ')"
    Write-Host "  Groups    : $($GroupName -join ', ')"
    Write-Host "  VMs file  : $VmsFile"
    Write-Host "  From      : $FromSite   To (site): $ToSite"
    if ($DryRun) { Write-Host '  Mode      : DRY RUN' }

    if ($WithTags) {
        if (-not $DryRun) {
            Write-ErsStep 'Capture tags from target-side VMs'
            Export-ErsTag -ErsSite $src -VmsFile $VmsFile | Out-Null
        } else {
            Write-ErsDry "Export-ErsTag -ErsSite $FromSite -VmsFile $VmsFile"
        }
    }

    if (-not $DryRun) {
        Write-ErsStep 'Power off target-side VMs'
        Stop-ErsVM -ErsSite $src -VmsFile $VmsFile | Out-Null
    } else {
        Write-ErsDry "Stop-ErsVM -ErsSite $FromSite -VmsFile $VmsFile"
    }

    if (-not $DryRun) {
        Write-ErsStep "Protect groups: $($GroupName -join ', ')"
        Invoke-ErsGroupRun -ErsInstance $ErsInstance -Name $GroupName | Out-Null
    } else {
        Write-ErsDry "Invoke-ErsGroupRun -Name $($GroupName -join ',')"
    }

    if (-not $DryRun) {
        Write-ErsStep "Failback: $($PlanName -join ', ') -> $ToSite"
        $results = Invoke-ErsPlanFailback -ErsInstance $ErsInstance -Name $PlanName -Site $ToSite `
            -IntervalSeconds $IntervalSeconds -MaxPolls $MaxPolls
        if (($results | Where-Object { $_.status -ne 'SUCCEEDED' }).Count -gt 0) {
            Write-Host 'Error: failback did not succeed for all plans.'
            return $false
        }
    } else {
        Write-ErsDry "Invoke-ErsPlanFailback -Name $($PlanName -join ',') -Site $ToSite"
    }

    if ($WithTags) {
        if (-not $DryRun) {
            Write-ErsStep 'Apply tags to source-side VMs (non-fatal on error)'
            Import-ErsTag -ErsSite $tgt -VmsFile $VmsFile -Source $FromSite -CreateMissing:$CreateMissingTags | Out-Null
        } else {
            Write-ErsDry "Import-ErsTag -ErsSite $ToSite -VmsFile $VmsFile -Source $FromSite -CreateMissing:$CreateMissingTags"
        }
    }

    if ($WithNetwork) {
        if (-not $DryRun) {
            Write-ErsStep 'Connect VM NICs on source'
            Connect-ErsVMNetwork -ErsSite $tgt -VmsFile $VmsFile | Out-Null
        } else {
            Write-ErsDry "Connect-ErsVMNetwork -ErsSite $ToSite -VmsFile $VmsFile"
        }
    }

    Write-ErsBanner 'MANAGED FAILBACK COMPLETE'
    return $true
}
