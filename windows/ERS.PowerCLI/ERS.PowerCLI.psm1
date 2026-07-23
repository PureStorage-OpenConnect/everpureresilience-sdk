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

# ERS.PowerCLI — root module.
# Loads classes first (other files depend on them), then private helpers,
# then public cmdlets. Only Public/*.ps1 functions are exported — see
# ERS.PowerCLI.psd1's FunctionsToExport for the authoritative list.

$moduleRoot = $PSScriptRoot

foreach ($folder in @('Classes', 'Private', 'Public')) {
    $path = Join-Path $moduleRoot $folder
    if (Test-Path $path) {
        $files = Get-ChildItem -Path $path -Filter '*.ps1' | Sort-Object Name
        foreach ($file in $files) {
            . $file.FullName
        }
    }
}

Export-ModuleMember -Function @(
    'New-ErsInstance', 'Register-ErsSite',
    'Get-ErsPolicy',
    'Get-ErsGroup', 'Enable-ErsGroup', 'Disable-ErsGroup', 'Invoke-ErsGroupRun', 'Wait-ErsGroup',
    'Get-ErsPlan', 'Invoke-ErsPlanFailover', 'Invoke-ErsPlanCleanup', 'Invoke-ErsPlanFailback',
    'Wait-ErsPlan', 'Get-ErsPlanSnapshot',
    'Get-ErsSite',
    'Start-ErsVM', 'Stop-ErsVM', 'Connect-ErsVMNetwork', 'Export-ErsTag', 'Import-ErsTag',
    'Invoke-ErsManagedFailover', 'Invoke-ErsManagedFailback',
    'Invoke-ErsSystemTest'
)
