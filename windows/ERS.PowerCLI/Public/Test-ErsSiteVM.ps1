# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function Test-ErsSiteVM {
    <#
    .SYNOPSIS Returns which of the given VM names exist on a vCenter site.
    .EXAMPLE $existing = Test-ErsSiteVM -ErsInstance $Ers -SiteName prod-site -Name vm-001, vm-002
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$SiteName,
        [Parameter(Mandatory)][string[]]$Name
    )

    $site = $ErsInstance.Sites[$SiteName]
    if (-not $site) { throw "Site '$SiteName' not registered." }

    $existing = @()
    foreach ($vmName in $Name) {
        $vm = Get-VM -Server $site.VIServer -Name $vmName -ErrorAction SilentlyContinue
        if ($vm) { $existing += $vmName }
    }
    return $existing
}
