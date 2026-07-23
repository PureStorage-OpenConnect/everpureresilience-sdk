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

# Private: every shared "constant" in the module, as a function rather
# than a $script: variable. Cross-file $script: variable sharing showed
# at least one confirmed case of failing when invoked through Pester's
# test-execution model, despite working when queried directly against
# the module's scope — the exact mechanism wasn't fully pinned down.
# Functions have been reliable in every context tested (including from
# Pester), so this sidesteps the whole class of failure rather than
# chasing the precise cause further. Centralized here in one file so
# every constant is defined the same, safe way.

function Get-ErsDir             { Join-Path $HOME '.ers' }
function Get-ErsConfigPath      { Join-Path (Get-ErsDir) 'config' }
function Get-ErsCredentialsPath { Join-Path (Get-ErsDir) 'credentials' }
function Get-ErsStateDirPath    { Join-Path (Get-ErsDir) 'state' }

function Get-ErsTerminalStates { @('SUCCEEDED', 'FAILED', 'CANCELLED', 'COMPLETED') }

function Get-ErsSupportedVmListSchemaVersions { @(2) }

function Get-ErsLastRunOpsFileName { 'last_run_ops.json' }
function Get-ErsTagExportFileName  { '.last_tags_export.json' }

function Get-ErsPlanStateFileName { 'last_plan_ops.json' }
function Get-ErsPlanOpsFileName   { 'last_plan_run_ops.json' }

function Get-ErsFailoverPath  { '/pure-protect/api/1.latest/recovery-plans/failover/operations' }
function Get-ErsCleanupPath   { '/pure-protect/api/1.latest/recovery-plans/cleanup/operations' }
function Get-ErsFbSyncPath    { '/pure-protect/api/1.latest/recovery-plans/failback/synchronization/operations' }
function Get-ErsFbCutoverPath { '/pure-protect/api/1.latest/recovery-plans/failback/cutover/operations' }
function Get-ErsFbPromotePath { '/pure-protect/api/1.latest/recovery-plans/failback/promotion/operations' }
function Get-ErsSnapshotsPath { '/pure-protect/api/1.latest/recovery-plans/snapshot-sets' }

# POST body "plan_type" — the real API's enum for the failover operation body
function Get-ErsPlanTypeMap { @{ test = 'TEST'; prod = 'PRODUCTION' } }
# GET polling query "failover_type" — a different, abbreviated vocabulary
function Get-ErsFailoverQueryTypeMap { @{ test = 'TEST'; prod = 'PROD' } }

function Get-ErsPlanPrerequisites {
    @{
        test_failover = @{ Requires = $null;           MustSucceed = $false }
        prod_failover = @{ Requires = $null;           MustSucceed = $false }
        cleanup       = @{ Requires = 'test_failover'; MustSucceed = $false }
        failback      = @{ Requires = 'prod_failover'; MustSucceed = $true }
    }
}
