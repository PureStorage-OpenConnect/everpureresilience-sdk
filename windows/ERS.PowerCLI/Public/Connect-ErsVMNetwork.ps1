# Copyright 2026 Everpure
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

function Get-ErsNetworkObject {
    <#
    .SYNOPSIS
        Resolves a network name to its portgroup against the given vCenter, checking
        standard portgroups first and falling back to distributed (VDS) portgroups.
        Returns $null if not found in either.
    .NOTES
        Replaces the old bare `Get-VirtualPortGroup -Name ...` call, which implicitly
        matched both standard and distributed portgroups and is now deprecated
        ("obsolete... may change in the future"). Being explicit here also avoids
        ambiguity if a standard and a distributed portgroup happen to share a name.

        Returns a wrapper object rather than the bare portgroup, because callers need
        to know *which kind* was matched: Set-NetworkAdapter/New-NetworkAdapter's
        -Portgroup parameter only accepts VDPortgroup (distributed) objects in this
        PowerCLI version — passing a standard VirtualPortGroup object into -Portgroup
        fails parameter-set resolution ("Parameter set cannot be resolved..."). Standard
        portgroups must still be applied via -NetworkName (a plain string), which is
        only deprecated for *distributed* portgroup names, not standard ones.
    #>
    param(
        [Parameter(Mandatory)]$VIServer,
        [Parameter(Mandatory)][string]$Name
    )

    $pg = Get-VirtualPortGroup -Server $VIServer -Name $Name -Standard -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($pg) {
        return [pscustomobject]@{ Name = $Name; Object = $pg; IsDistributed = $false }
    }

    $vdpg = Get-VDPortgroup -Server $VIServer -Name $Name -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($vdpg) {
        return [pscustomobject]@{ Name = $Name; Object = $vdpg; IsDistributed = $true }
    }

    return $null
}

function Connect-ErsVMNetwork {
    <#
    .SYNOPSIS
        Reconnects VM NICs to the networks listed for each VM, for this
        site, using vm-list.json's `networks` object (keyed by registered
        site name — see Get-ErsVmListFile). If a VM has fewer existing
        NICs than networks configured for it, a new vmxnet3 adapter is
        created for each missing position via VCF.PowerCLI's
        New-NetworkAdapter, instead of silently doing nothing for it.

        Network names are resolved against the vCenter inventory by
        explicitly checking standard portgroups first, then distributed
        (VDS) portgroups (see Get-ErsNetworkObject). Distributed matches
        are applied to Set-NetworkAdapter/New-NetworkAdapter via
        -Portgroup (required, since -NetworkName no longer supports
        distributed portgroup names); standard matches are still applied
        via -NetworkName, since -Portgroup only accepts VDPortgroup
        objects in this PowerCLI version.
    .EXAMPLE
        Connect-ErsVMNetwork -ErsSite $Ers.Sites['dr-dc'] -VmsFile vm-list.json
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][ErsSite]$ErsSite, [string[]]$Name, [string]$VmsFile)

    if ($VmsFile) {
        $records = Get-ErsVmListFile -Path $VmsFile
        $networksByVm = Get-ErsVmNetworksForSite -VmRecords $records -SiteName $ErsSite.Name
        $names = $records.name
    } elseif ($Name) {
        $names = $Name
        $networksByVm = @{}
        foreach ($n in $Name) { $networksByVm[$n] = @() }
    } else {
        throw 'No VM names given (pass -Name or -VmsFile).'
    }

    $networkCache = @{}  # network name -> resolved portgroup object (or $null)
    $success = @()

    foreach ($vmName in $names) {
        $vm = Get-VM -Server $ErsSite.VIServer -Name $vmName -ErrorAction SilentlyContinue
        if (-not $vm) {
            Write-Warning "VM not found: $vmName"
            continue
        }

        $nics = @(Get-NetworkAdapter -VM $vm | Sort-Object Name)
        $targetNetworks = @($networksByVm[$vmName])
        $maxCount = [Math]::Max($nics.Count, $targetNetworks.Count)
        $skipVm = $false
        $changesToApply = @()  # deferred: @{ Kind='Edit'|'New'|'Connect'; Nic=...; NetworkInfo=... }

        for ($i = 0; $i -lt $maxCount; $i++) {
            $targetNetworkName = if ($i -lt $targetNetworks.Count) { $targetNetworks[$i] } else { $null }

            if ($i -lt $nics.Count) {
                $nic = $nics[$i]
                if ($targetNetworkName) {
                    if (-not $networkCache.ContainsKey($targetNetworkName)) {
                        $networkCache[$targetNetworkName] = Get-ErsNetworkObject -VIServer $ErsSite.VIServer -Name $targetNetworkName
                    }
                    if (-not $networkCache[$targetNetworkName]) {
                        Write-Warning "network '$targetNetworkName' not found in vCenter inventory for $vmName"
                        $skipVm = $true
                        continue
                    }
                    $changesToApply += @{ Kind = 'Edit'; Nic = $nic; NetworkInfo = $networkCache[$targetNetworkName] }
                } else {
                    $changesToApply += @{ Kind = 'Connect'; Nic = $nic }
                }
            } else {
                if (-not $targetNetworkName) { continue }
                if (-not $networkCache.ContainsKey($targetNetworkName)) {
                    $networkCache[$targetNetworkName] = Get-ErsNetworkObject -VIServer $ErsSite.VIServer -Name $targetNetworkName
                }
                if (-not $networkCache[$targetNetworkName]) {
                    Write-Warning "network '$targetNetworkName' not found in vCenter inventory for $vmName"
                    $skipVm = $true
                    continue
                }
                Write-Host "  ${vmName}: no existing NIC at position $($i + 1) — creating a new vmxnet3 adapter on '$targetNetworkName'"
                $changesToApply += @{ Kind = 'New'; NetworkInfo = $networkCache[$targetNetworkName] }
            }
        }

        if ($skipVm) {
            Write-Host "  Skipping $vmName entirely — one or more target networks couldn't be " +
                "resolved (partial reconfiguration would leave it in an inconsistent state)"
            continue
        }

        try {
            foreach ($change in $changesToApply) {
                switch ($change.Kind) {
                    'Edit' {
                        if ($change.NetworkInfo.IsDistributed) {
                            # Set-NetworkAdapter's -Portgroup parameter set does not include
                            # -Connected/-StartConnected (unlike New-NetworkAdapter's), so the
                            # portgroup change and the connection-state change must be two
                            # separate calls here.
                            Set-NetworkAdapter -NetworkAdapter $change.Nic -Portgroup $change.NetworkInfo.Object `
                                -Confirm:$false -ErrorAction Stop | Out-Null
                            Set-NetworkAdapter -NetworkAdapter $change.Nic `
                                -Connected:$true -StartConnected:$true -Confirm:$false -ErrorAction Stop | Out-Null
                        } else {
                            Set-NetworkAdapter -NetworkAdapter $change.Nic -NetworkName $change.NetworkInfo.Name `
                                -Connected:$true -StartConnected:$true -Confirm:$false -ErrorAction Stop | Out-Null
                        }
                    }
                    'Connect' {
                        Set-NetworkAdapter -NetworkAdapter $change.Nic `
                            -Connected:$true -StartConnected:$true -Confirm:$false -ErrorAction Stop | Out-Null
                    }
                    'New' {
                        if ($change.NetworkInfo.IsDistributed) {
                            New-NetworkAdapter -VM $vm -Portgroup $change.NetworkInfo.Object -Type Vmxnet3 `
                                -StartConnected:$true -Confirm:$false -ErrorAction Stop | Out-Null
                        } else {
                            New-NetworkAdapter -VM $vm -NetworkName $change.NetworkInfo.Name -Type Vmxnet3 `
                                -StartConnected:$true -Confirm:$false -ErrorAction Stop | Out-Null
                        }
                    }
                }
            }
            $success += $vmName
        } catch {
            Write-Host "  Error connecting network for ${vmName}: $($_.Exception.Message)"
        }
    }

    Write-Host ($success -join ', ')
    return $success
}