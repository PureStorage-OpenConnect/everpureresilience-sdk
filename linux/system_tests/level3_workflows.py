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

"""
system_tests.level3_workflows — the full managed_failover/managed_failback
workflows end to end. These are dangerous=True: with dry_run=False (the
CLI's --no-dry-run flag) they run a real failover/failback of your
environment, same as level 2's plan_prod_failover/plan_failback, just
orchestrated as a single workflow including VM power/network/tags.

dry_run defaults to True at this level regardless of what the CLI's
--no-dry-run flag says elsewhere, unless the runner explicitly passes it
through — see ers-system-test.py.
"""

from .runner import TestCase


def test_managed_failover(e, cfg, dry_run: bool = True):
    ok = e.workflow.managed_failover(
        vms_file=cfg["vms_file"], group_names=cfg["group_names"], plan_names=cfg["plan_names"],
        from_site=cfg["source_site"], to_site=cfg["target_site"],
        with_network=cfg["with_network"], with_tags=cfg["with_tags"],
        create_missing_tags=cfg["create_missing_tags"], dry_run=dry_run,
        interval=cfg["interval"], max_polls=cfg["max_polls"],
    )
    assert ok, "managed_failover() reported failure"


def test_managed_failback(e, cfg, dry_run: bool = True):
    ok = e.workflow.managed_failback(
        vms_file=cfg["vms_file"], group_names=cfg["group_names"], plan_names=cfg["plan_names"],
        from_site=cfg["target_site"], to_site=cfg["failback_site"],
        with_network=cfg["with_network"], with_tags=cfg["with_tags"],
        create_missing_tags=cfg["create_missing_tags"], dry_run=dry_run,
        interval=cfg["interval"], max_polls=cfg["max_polls"],
    )
    assert ok, "managed_failback() reported failure"


TESTS = [
    TestCase("managed_failover", 3, test_managed_failover, dangerous=True),
    TestCase("managed_failback", 3, test_managed_failback, dangerous=True),
]
