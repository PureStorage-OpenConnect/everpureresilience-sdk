# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

function New-ErsSiteVM {
    <#
    .SYNOPSIS Clones a VM from a template on a registered vCenter site (via PowerCLI).
    .EXAMPLE New-ErsSiteVM -ErsInstance $Ers -SiteName prod-site -Name vm-001 -Template rhel7-tpl -Datastore ds-001
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][ErsInstance]$ErsInstance,
        [Parameter(Mandatory)][string]$SiteName,
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Template,
        [Parameter(Mandatory)][string]$Datastore,
        [string]$Folder,
        [string]$ResourcePool,
        [switch]$PowerOn
    )

    $site = $ErsInstance.Sites[$SiteName]
    if (-not $site) { throw "Site '$SiteName' not registered. Run Register-ErsSite first." }

    $tplObj = Get-Template -Server $site.VIServer -Name $Template -ErrorAction SilentlyContinue
    if (-not $tplObj) { throw "Template '$Template' not found on '$SiteName'" }

    $dsObj = Get-Datastore -Server $site.VIServer -Name $Datastore -ErrorAction SilentlyContinue
    if (-not $dsObj) { throw "Datastore '$Datastore' not found on '$SiteName'" }

    $rpObj = $null
    if ($ResourcePool) {
        $rpObj = Get-ResourcePool -Server $site.VIServer -Name $ResourcePool -ErrorAction SilentlyContinue
    }

    $folderObj = $null
    if ($Folder) {
        $folderObj = Get-Folder -Server $site.VIServer -Type VM -Name $Folder -ErrorAction SilentlyContinue | Select-Object -First 1
    }

    $cloneArgs = @{ Name = $Name; Template = $tplObj; Datastore = $dsObj; Server = $site.VIServer }
    if ($rpObj)     { $cloneArgs.ResourcePool = $rpObj }
    if ($folderObj) { $cloneArgs.Location = $folderObj }

    $vm = New-VM @cloneArgs
    if ($PowerOn -and $vm) { Start-VM -VM $vm -Confirm:$false | Out-Null }

    Write-Host "Created VM '$Name' on '$SiteName' (datastore: $Datastore)"
    return $vm
}
