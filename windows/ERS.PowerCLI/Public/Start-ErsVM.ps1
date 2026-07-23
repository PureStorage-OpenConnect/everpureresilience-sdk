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

function Set-ErsVMPowerState {
    param(
        [Parameter(Mandatory)][ErsSite]$ErsSite,
        [string[]]$Name,
        [string]$VmsFile,
        [Parameter(Mandatory)][bool]$TurnOn
    )

    $names = if ($Name) { $Name } elseif ($VmsFile) { (Get-ErsVmListFile -Path $VmsFile).name } else { @() }
    if ($names.Count -eq 0) {
        throw 'No VM names given (pass -Name or -VmsFile).'
    }

    $success = @()
    foreach ($vmName in $names) {
        $vm = Get-VM -Server $ErsSite.VIServer -Name $vmName -ErrorAction SilentlyContinue
        if (-not $vm) {
            Write-Warning "VM not found: $vmName"
            continue
        }
        $targetState = if ($TurnOn) { 'PoweredOn' } else { 'PoweredOff' }
        if ($vm.PowerState -eq $targetState) {
            $success += $vmName
            continue
        }
        try {
            if ($TurnOn) {
                Start-VM -VM $vm -Confirm:$false -ErrorAction Stop | Out-Null
            } else {
                Stop-VM -VM $vm -Confirm:$false -ErrorAction Stop | Out-Null
            }
            $success += $vmName
        } catch {
            Write-Host "  Error powering $(if ($TurnOn) {'on'} else {'off'}) ${vmName}: $($_.Exception.Message)"
        }
    }

    Write-Host ($success -join ', ')
    return $success
}

function Start-ErsVM {
    <#
    .SYNOPSIS
        Powers on VMs on the given site. Idempotent — already-on VMs are
        left alone and still counted as success.
    .EXAMPLE
        Start-ErsVM -ErsSite $Ers.Sites['prod-dc'] -VmsFile vm-list.json
    .EXAMPLE
        Start-ErsVM -ErsSite $Ers.Sites['prod-dc'] -Name vm-1, vm-2
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][ErsSite]$ErsSite, [string[]]$Name, [string]$VmsFile)
    Set-ErsVMPowerState -ErsSite $ErsSite -Name $Name -VmsFile $VmsFile -TurnOn $true
}

function Stop-ErsVM {
    <#
    .SYNOPSIS
        Powers off VMs on the given site. Idempotent — already-off VMs
        are left alone and still counted as success.
    .EXAMPLE
        Stop-ErsVM -ErsSite $Ers.Sites['prod-dc'] -VmsFile vm-list.json
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][ErsSite]$ErsSite, [string[]]$Name, [string]$VmsFile)
    Set-ErsVMPowerState -ErsSite $ErsSite -Name $Name -VmsFile $VmsFile -TurnOn $false
}
