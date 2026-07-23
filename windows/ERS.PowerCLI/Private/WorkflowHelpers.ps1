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

# Private: shared output formatting for Invoke-ErsManagedFailover/Failback.

function Write-ErsBanner { param([string]$Title) Write-Host "`n$('=' * 60)`n  $Title`n$('=' * 60)" }
function Write-ErsStep   { param([string]$Label) Write-Host "`n-> $Label"; Write-Host ('-' * 60) }
function Write-ErsDry    { param([string]$Cmd)   Write-Host "  [DRY RUN] Would call: $Cmd" }
