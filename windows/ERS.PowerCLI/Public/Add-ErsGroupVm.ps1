# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Add-ErsGroupVm {
    <#
    .SYNOPSIS Enrolls VMs into an application group.
    .EXAMPLE Add-ErsGroupVm -ErsInstance $Ers -VmName vm1, vm2 -GroupName group1
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$VmName,
        [Parameter(Mandatory)][string]$GroupName,
        [ValidateSet('FA_OFFLOAD','VADP')][string]$ProtectionWorkflow = 'FA_OFFLOAD'
    )

    $groupResolved = Resolve-ErsGroups -ErsInstance $ErsInstance -Names @($GroupName)
    if ($groupResolved.Matched.Count -eq 0) { throw "Group '$GroupName' not found" }
    $group = $groupResolved.Matched[0]

    $sourceSiteId = $group.source_site.id
    $inventory = Get-ErsVmInventory -ErsInstance $ErsInstance -SiteId $sourceSiteId

    $body = @()
    foreach ($name in $VmName) {
        $vm = $inventory | Where-Object { $_.name -eq $name } | Select-Object -First 1
        if (-not $vm) {
            Write-Warning "VM '$name' not found in inventory"
            continue
        }
        $body += @{ virtual_machine_id = $vm.id; protection_workflow = $ProtectionWorkflow }
        Write-Host "Added VM '$name' to group '$GroupName' (protection_workflow=$ProtectionWorkflow)"
    }

    if ($body.Count -gt 0) {
        Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method POST `
            -Path (Get-ErsEnrolledVmsPath) `
            -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; application_group_id = $group.id } `
            -Body $body | Out-Null
    }
}
