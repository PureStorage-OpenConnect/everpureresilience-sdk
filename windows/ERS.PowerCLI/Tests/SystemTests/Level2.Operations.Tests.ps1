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

# Level 2 — real operations against your Pure1 deployment and registered
# vCenter site(s): group protection runs, plan failover/cleanup/failback,
# VM power, network reconnection, and tag export/apply. These change real
# state. Tests tagged 'Dangerous' run an ACTUAL production
# failover/failback, not a simulation — Invoke-ErsSystemTest excludes
# these by default; pass -IncludeDangerous to run them.
# Mirrors system_tests/level2_operations.py.

param($ErsInstance, $Config)

Describe 'Level 2 - Real operations' -Tag 'Level2' {

    It 'runs group protection and waits for success' {
        Invoke-ErsGroupRun -ErsInstance $ErsInstance -Name $Config.group_names | Out-Null
        $states = Wait-ErsGroup -ErsInstance $ErsInstance -Name $Config.group_names `
            -IntervalSeconds $Config.interval -MaxPolls $Config.max_polls
        $failed = $states.Keys | Where-Object { $states[$_] -ne 'SUCCEEDED' }
        $failed | Should -BeNullOrEmpty -Because "group run(s) did not succeed: $($failed -join ', ')"
    }

    It 'runs test failover successfully' {
        $results = Invoke-ErsPlanFailover -ErsInstance $ErsInstance -Kind Test -Name $Config.plan_names `
            -IntervalSeconds $Config.interval -MaxPolls $Config.max_polls
        $failed = $results | Where-Object { $_.status -ne 'SUCCEEDED' }
        $failed | Should -BeNullOrEmpty -Because "test failover did not succeed for: $($failed.plan -join ', ')"
    }

    It 'cleans up after test failover' {
        $results = Invoke-ErsPlanCleanup -ErsInstance $ErsInstance -Name $Config.plan_names `
            -IntervalSeconds $Config.interval -MaxPolls $Config.max_polls
        $failed = $results | Where-Object { $_.status -ne 'SUCCEEDED' }
        $failed | Should -BeNullOrEmpty -Because "cleanup did not succeed for: $($failed.plan -join ', ')"
    }

    It 'runs production failover successfully' -Tag 'Dangerous' {
        $results = Invoke-ErsPlanFailover -ErsInstance $ErsInstance -Kind Prod -Name $Config.plan_names `
            -IntervalSeconds $Config.interval -MaxPolls $Config.max_polls
        $failed = $results | Where-Object { $_.status -ne 'SUCCEEDED' }
        $failed | Should -BeNullOrEmpty -Because "production failover did not succeed for: $($failed.plan -join ', ')"
    }

    It 'runs failback successfully' -Tag 'Dangerous' {
        $results = Invoke-ErsPlanFailback -ErsInstance $ErsInstance -Name $Config.plan_names -Site $Config.failback_site `
            -IntervalSeconds $Config.interval -MaxPolls $Config.max_polls
        $failed = $results | Where-Object { $_.status -ne 'SUCCEEDED' }
        $failed | Should -BeNullOrEmpty -Because "failback did not succeed for: $($failed.plan -join ', ')"
    }

    It 'powers off VMs on the source site' {
        $site = $ErsInstance.Sites[$Config.source_site]
        $result = Stop-ErsVM -ErsSite $site -VmsFile $Config.vms_file
        $result | Should -Not -BeNullOrEmpty -Because 'no VMs reported success'
    }

    It 'powers on VMs on the source site' {
        $site = $ErsInstance.Sites[$Config.source_site]
        $result = Start-ErsVM -ErsSite $site -VmsFile $Config.vms_file
        $result | Should -Not -BeNullOrEmpty -Because 'no VMs reported success'
    }

    It 'reconnects VM networks on the target site' {
        $site = $ErsInstance.Sites[$Config.target_site]
        $result = Connect-ErsVMNetwork -ErsSite $site -VmsFile $Config.vms_file
        $result | Should -Not -BeNullOrEmpty -Because 'no VMs reported success'
    }

    It 'exports tags from source and imports them to target' {
        $srcSite = $ErsInstance.Sites[$Config.source_site]
        $tgtSite = $ErsInstance.Sites[$Config.target_site]
        { Export-ErsTag -ErsSite $srcSite -VmsFile $Config.vms_file } | Should -Not -Throw
        { Import-ErsTag -ErsSite $tgtSite -VmsFile $Config.vms_file -Source $Config.source_site `
            -CreateMissing:$Config.create_missing_tags } | Should -Not -Throw
    }
}
