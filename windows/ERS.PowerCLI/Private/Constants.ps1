# Copyright 2026 Everpure™
# Licensed under the Apache License, Version 2.0

# Private: every shared "constant" in the module, as a function rather
# than a $script: variable. Functions resolve correctly in all contexts
# including Pester. Centralized here in one file.

function Get-ErsModuleVersion { '2.8.0' }

function Get-ErsDir             { Join-Path $HOME '.ers' }
function Get-ErsConfigPath      { Join-Path (Get-ErsDir) 'config' }
function Get-ErsCredentialsPath { Join-Path (Get-ErsDir) 'credentials' }
function Get-ErsStateDirPath    { Join-Path (Get-ErsDir) 'state' }

function Get-ErsTerminalStates { @('SUCCEEDED', 'FAILED', 'CANCELLED', 'COMPLETED') }

function Get-ErsSupportedVmListSchemaVersions { @(2) }

function Get-ErsLastRunOpsFileName { 'last_run_ops.json' }
function Get-ErsTagExportFileName  { 'last_tags_export.json' }

function Get-ErsPlanStateFileName { 'last_plan_ops.json' }
function Get-ErsPlanOpsFileName   { 'last_plan_run_ops.json' }

# API paths
function Get-ErsPoliciesPath    { '/pure-protect/api/1.latest/service-level-policies' }
function Get-ErsGroupsPath      { '/pure-protect/api/1.latest/application-groups' }
function Get-ErsProtectPath     { '/pure-protect/api/1.latest/application-groups/protection/operations' }
function Get-ErsPlansPath       { '/pure-protect/api/1.latest/recovery-plans' }
function Get-ErsSitesPath       { '/pure-protect/api/1.latest/sites' }
function Get-ErsVmInventoryPath { '/pure-protect/api/1.latest/inventory/vmware/virtual-machines' }
function Get-ErsEnrolledVmsPath { '/pure-protect/api/1.latest/enrolled-virtual-machines' }
function Get-ErsFailoverPath    { '/pure-protect/api/1.latest/recovery-plans/failover/operations' }
function Get-ErsCleanupPath     { '/pure-protect/api/1.latest/recovery-plans/cleanup/operations' }
function Get-ErsFbSyncPath      { '/pure-protect/api/1.latest/recovery-plans/failback/synchronization/operations' }
function Get-ErsFbCutoverPath   { '/pure-protect/api/1.latest/recovery-plans/failback/cutover/operations' }
function Get-ErsFbPromotePath   { '/pure-protect/api/1.latest/recovery-plans/failback/promotion/operations' }
function Get-ErsSnapshotsPath   { '/pure-protect/api/1.latest/recovery-plans/snapshot-sets' }

# POST body "plan_type" — FULL word: TEST / PRODUCTION
function Get-ErsPlanTypeMap { @{ test = 'TEST'; prod = 'PRODUCTION' } }
# GET polling "failover_type" — ABBREVIATED: TEST / PROD
function Get-ErsFailoverQueryTypeMap { @{ test = 'TEST'; prod = 'PROD' } }

function Get-ErsPlanPrerequisites {
    @{
        test_failover = @{ Requires = $null;           MustSucceed = $false }
        prod_failover = @{ Requires = $null;           MustSucceed = $false }
        cleanup       = @{ Requires = 'test_failover'; MustSucceed = $false }
        failback      = @{ Requires = 'prod_failover'; MustSucceed = $true }
    }
}
