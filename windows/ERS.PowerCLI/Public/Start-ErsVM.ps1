# Copyright 2026 Everpure
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

function Start-ErsVM {
    <#
    .SYNOPSIS
        Powers on VMs on the given site. Idempotent — already-on VMs are
        left alone and still counted as success.
    .EXAMPLE
        Start-ErsVM -ErsSite $Ers.Sites['prod-dc'] -VmsFile vm-list.json
    .EXAMPLE
        Start-ErsVM -ErsSite $Ers.Sites['prod-dc'] -Name vm-1, vm-2
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)][ErsSite]$ErsSite, [string[]]$Name, [string]$VmsFile)
    Set-ErsVMPowerState -ErsSite $ErsSite -Name $Name -VmsFile $VmsFile -TurnOn $true
}
