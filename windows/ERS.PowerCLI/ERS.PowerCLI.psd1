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

@{
    RootModule        = 'ERS.PowerCLI.psm1'
    ModuleVersion      = '1.0.0'
    GUID               = 'b7e5c9a2-4f1d-4e3a-9c6b-2a8d7f1e5c3b'
    Author             = '[Your Organization]'
    CompanyName        = '[Your Organization]'
    Copyright          = '(c) 2026 [Your Organization]. Licensed under the Apache License, Version 2.0.'
    Description        = 'Everpure Resilience Service (ERS) SDK for PowerShell — Pure1 automation plus VCF.PowerCLI-backed vCenter site integration.'
    PowerShellVersion  = '7.0'
    RequiredModules    = @('VCF.PowerCLI')

    FunctionsToExport  = @(
        'New-ErsInstance'
        'Register-ErsSite'

        'Get-ErsPolicy'

        'Get-ErsGroup'
        'Enable-ErsGroup'
        'Disable-ErsGroup'
        'Invoke-ErsGroupRun'
        'Wait-ErsGroup'

        'Get-ErsPlan'
        'Invoke-ErsPlanFailover'
        'Invoke-ErsPlanCleanup'
        'Invoke-ErsPlanFailback'
        'Wait-ErsPlan'
        'Get-ErsPlanSnapshot'

        'Get-ErsSite'

        'Start-ErsVM'
        'Stop-ErsVM'
        'Connect-ErsVMNetwork'
        'Export-ErsTag'
        'Import-ErsTag'

        'Invoke-ErsManagedFailover'
        'Invoke-ErsManagedFailback'

        'Invoke-ErsSystemTest'
    )
    CmdletsToExport    = @()
    VariablesToExport  = @()
    AliasesToExport    = @()

    PrivateData = @{
        PSData = @{
            LicenseUri = 'https://www.apache.org/licenses/LICENSE-2.0'
        }
    }
}
