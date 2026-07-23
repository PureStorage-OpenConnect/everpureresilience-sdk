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

function Connect-ErsVMNetwork {
    <#
    .SYNOPSIS
        Reconnects VM NICs to the networks listed for each VM, for this
        site, using vm-list.json's `networks` object (keyed by registered
        site name — see Get-ErsVmListFile). If a VM has fewer existing
        NICs than networks configured for it, a new vmxnet3 adapter is
        created for each missing position via VCF.PowerCLI's
        New-NetworkAdapter, instead of silently doing nothing for it.

        Network names are resolved against the vCenter inventory (both
        standard and distributed portgroups — VCF.PowerCLI's
        -NetworkName parameter handles both transparently, no manual
        DVS-vs-standard branching needed).
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

    $networkCache = @{}  # network name -> resolved object (or $null)
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
        $changesToApply = @()  # deferred: @{ Kind='Edit'|'New'; Nic=...; NetworkName=... }

        for ($i = 0; $i -lt $maxCount; $i++) {
            $targetNetworkName = if ($i -lt $targetNetworks.Count) { $targetNetworks[$i] } else { $null }

            if ($i -lt $nics.Count) {
                $nic = $nics[$i]
                if ($targetNetworkName) {
                    if (-not $networkCache.ContainsKey($targetNetworkName)) {
                        $networkCache[$targetNetworkName] = Get-VirtualPortGroup -Server $ErsSite.VIServer `
                            -Name $targetNetworkName -ErrorAction SilentlyContinue | Select-Object -First 1
                    }
                    if (-not $networkCache[$targetNetworkName]) {
                        Write-Warning "network '$targetNetworkName' not found in vCenter inventory for $vmName"
                        $skipVm = $true
                        continue
                    }
                    $changesToApply += @{ Kind = 'Edit'; Nic = $nic; NetworkName = $targetNetworkName }
                } else {
                    $changesToApply += @{ Kind = 'Connect'; Nic = $nic }
                }
            } else {
                if (-not $targetNetworkName) { continue }
                if (-not $networkCache.ContainsKey($targetNetworkName)) {
                    $networkCache[$targetNetworkName] = Get-VirtualPortGroup -Server $ErsSite.VIServer `
                        -Name $targetNetworkName -ErrorAction SilentlyContinue | Select-Object -First 1
                }
                if (-not $networkCache[$targetNetworkName]) {
                    Write-Warning "network '$targetNetworkName' not found in vCenter inventory for $vmName"
                    $skipVm = $true
                    continue
                }
                Write-Host "  ${vmName}: no existing NIC at position $($i + 1) — creating a new vmxnet3 adapter on '$targetNetworkName'"
                $changesToApply += @{ Kind = 'New'; NetworkName = $targetNetworkName }
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
                        Set-NetworkAdapter -NetworkAdapter $change.Nic -NetworkName $change.NetworkName `
                            -Connected:$true -StartConnected:$true -Confirm:$false -ErrorAction Stop | Out-Null
                    }
                    'Connect' {
                        Set-NetworkAdapter -NetworkAdapter $change.Nic `
                            -Connected:$true -StartConnected:$true -Confirm:$false -ErrorAction Stop | Out-Null
                    }
                    'New' {
                        New-NetworkAdapter -VM $vm -NetworkName $change.NetworkName -Type Vmxnet3 `
                            -StartConnected:$true -Confirm:$false -ErrorAction Stop | Out-Null
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
