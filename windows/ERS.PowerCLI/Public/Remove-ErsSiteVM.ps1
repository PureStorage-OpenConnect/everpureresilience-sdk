# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Remove-ErsSiteVM {
    <#
    .SYNOPSIS Deletes VMs from a registered vCenter site.
    .EXAMPLE Remove-ErsSiteVM -ErsInstance $Ers -SiteName prod-site -Name vm-001, vm-002
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$SiteName,
        [Parameter(Mandatory)][string[]]$Name
    )

    $site = $ErsInstance.Sites[$SiteName]
    if (-not $site) { throw "Site '$SiteName' not registered." }

    foreach ($vmName in $Name) {
        $vm = Get-VM -Server $site.VIServer -Name $vmName -ErrorAction SilentlyContinue
        if (-not $vm) { Write-Warning "VM '$vmName' not found on '$SiteName'"; continue }
        if ($vm.PowerState -eq 'PoweredOn') {
            Stop-VM -VM $vm -Confirm:$false -Kill | Out-Null
        }
        Remove-VM -VM $vm -DeletePermanently -Confirm:$false | Out-Null
        Write-Host "Deleted VM '$vmName' from '$SiteName'"
    }
}
