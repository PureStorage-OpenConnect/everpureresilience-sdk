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

# Level 3 — the full Invoke-ErsManagedFailover/Failback workflows. Runs
# with -DryRun by default regardless of what Invoke-ErsSystemTest's
# -NoDryRun flag says elsewhere; $Config.dry_run controls this per-run,
# set by Invoke-ErsSystemTest. Tagged 'Dangerous' since a live
# (non-dry-run) run performs a real failover/failback.
# Mirrors system_tests/level3_workflows.py.

param($ErsInstance, $Config)

Describe 'Level 3 - Managed workflows' -Tag 'Level3', 'Dangerous' {

    It 'runs managed failover' {
        $ok = Invoke-ErsManagedFailover -ErsInstance $ErsInstance -VmsFile $Config.vms_file `
            -GroupName $Config.group_names -PlanName $Config.plan_names `
            -FromSite $Config.source_site -ToSite $Config.target_site `
            -WithNetwork:$Config.with_network -WithTags:$Config.with_tags `
            -CreateMissingTags:$Config.create_missing_tags -DryRun:$Config.dry_run `
            -IntervalSeconds $Config.interval -MaxPolls $Config.max_polls
        $ok | Should -BeTrue -Because 'managed failover reported failure'
    }

    It 'runs managed failback' {
        $ok = Invoke-ErsManagedFailback -ErsInstance $ErsInstance -VmsFile $Config.vms_file `
            -GroupName $Config.group_names -PlanName $Config.plan_names `
            -FromSite $Config.target_site -ToSite $Config.failback_site `
            -WithNetwork:$Config.with_network -WithTags:$Config.with_tags `
            -CreateMissingTags:$Config.create_missing_tags -DryRun:$Config.dry_run `
            -IntervalSeconds $Config.interval -MaxPolls $Config.max_polls
        $ok | Should -BeTrue -Because 'managed failback reported failure'
    }
}
