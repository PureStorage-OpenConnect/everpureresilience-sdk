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

# Level 1 — read-only: confirms the SDK can reach Pure1 and that the
# group/plan names in your test config actually exist. Nothing here
# changes any state. Safe to run any time, no confirmation required.
# Mirrors system_tests/level1_list.py.

param($ErsInstance, $Config)

Describe 'Level 1 - Read-only checks' -Tag 'Level1' {

    It 'lists policies' {
        { Get-ErsPolicy -ErsInstance $ErsInstance } | Should -Not -Throw
    }

    It 'lists sites' {
        { Get-ErsSite -ErsInstance $ErsInstance } | Should -Not -Throw
    }

    It 'finds configured groups in Pure1' {
        $items = Get-ErsGroup -ErsInstance $ErsInstance -Name $Config.group_names -Details
        $found = @($items.name)
        $missing = @($Config.group_names) | Where-Object { $_ -notin $found }
        $missing | Should -BeNullOrEmpty -Because "groups not found: $($missing -join ', ')"
    }

    It 'finds configured plans in Pure1' {
        $items = Get-ErsPlan -ErsInstance $ErsInstance -Name $Config.plan_names -Details
        $found = @($items.name)
        $missing = @($Config.plan_names) | Where-Object { $_ -notin $found }
        $missing | Should -BeNullOrEmpty -Because "plans not found: $($missing -join ', ')"
    }

    It 'lists snapshots for configured plans (informational only)' {
        { Get-ErsPlanSnapshot -ErsInstance $ErsInstance -Name $Config.plan_names } | Should -Not -Throw
    }
}
