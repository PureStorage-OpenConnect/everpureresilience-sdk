# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Remove-ErsGroupVm {
    <#
    .SYNOPSIS Unenrolls VMs from an application group.
    .EXAMPLE Remove-ErsGroupVm -ErsInstance $Ers -VmName vm1, vm2 -GroupName group1
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string[]]$VmName,
        [Parameter(Mandatory)][string]$GroupName,
        [switch]$Wildcard
    )

    $groupResolved = Resolve-ErsGroups -ErsInstance $ErsInstance -Names @($GroupName)
    if ($groupResolved.Matched.Count -eq 0) { throw "Group '$GroupName' not found" }
    $group = $groupResolved.Matched[0]

    if ($Wildcard) {
        $enrolled = Get-ErsEnrolledVms -ErsInstance $ErsInstance -GroupId $group.id -WildcardPattern $VmName[0]
    } else {
        $enrolled = Get-ErsEnrolledVms -ErsInstance $ErsInstance -GroupId $group.id -VmNames $VmName
    }

    $pattern = if ($Wildcard) { $VmName[0] } else { $null }
    $toRemove = @()
    foreach ($item in $enrolled) {
        $vmName_ = $item.primary_virtual_machine.name
        if (-not $vmName_) { continue }
        if ($Wildcard) {
            if ($vmName_ -like $pattern) { $toRemove += $item }
        } else {
            if ($vmName_ -in $VmName) { $toRemove += $item }
        }
    }

    if ($toRemove.Count -eq 0) {
        Write-Warning "No matching enrolled VMs found — nothing to remove."
        return
    }

    $ids = ($toRemove | ForEach-Object { $_.id }) -join ','
    Invoke-ErsApiRequest -ErsInstance $ErsInstance -Method DELETE `
        -Path (Get-ErsEnrolledVmsPath) `
        -QueryParams @{ deployment_id = $ErsInstance.DeploymentId; application_group_id = $group.id; ids = $ids } | Out-Null

    foreach ($r in $toRemove) {
        Write-Host "Removed VM '$($r.primary_virtual_machine.name)' from group '$GroupName'"
    }
}
