#!/usr/bin/env python3
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
----------------------------------------------------------------------------
ERS system test suite
----------------------------------------------------------------------------
Runs against your real Pure1 deployment and registered vCenter site(s), using
system-test-config.json for which sites/groups/plans/VMs to use. No mocking —
this exercises the actual ERS SDK against your actual environment.

Three levels, increasing in what they touch:
  Level 1 — read-only: list policies/groups/plans/sites. Safe any time.
  Level 2 — real operations: group protection runs, plan test/cleanup/prod
            failover/failback, VM power/network/tags. plan_prod_failover
            and plan_failback are REAL, not simulated.
  Level 3 — full managed_failover/managed_failback workflows. Runs with
            dry_run=True by default even if you select level 3 — pass
            --no-dry-run to actually execute them.

Setup:
  1. cp system-test-config.example.json system-test-config.json
  2. Edit it: source_site, target_site, group_names, plan_names, vms_file
  3. Make sure ~/.ers/config and ~/.ers/credentials are set up (see SETUP.md)
     and that source_site/target_site are registered there as [site ...]
     sections.

examples:
  # See what would run, without running anything
  ers-system-test --level 1 2 3 --list

  # Level 1 only — safe, read-only, no confirmation needed
  ers-system-test --level 1

  # Level 2 — will prompt for confirmation before running (real operations)
  ers-system-test --level 2

  # Level 2, but skip the real prod failover/failback
  ers-system-test --level 2 --skip plan_prod_failover,plan_failback

  # Level 2, non-interactive (e.g. CI) — still prints what it's about to do
  ers-system-test --level 2 --yes

  # Level 3 workflows, dry-run only (default) — safe to run any time
  ers-system-test --level 3

  # Level 3, for real — requires --yes AND typing the site name to confirm
  ers-system-test --level 3 --no-dry-run --yes

  # Only run one specific test
  ers-system-test --level 2 --only power_off_vms
"""

import argparse
import sys

import ers
from system_tests import ALL_TESTS
from system_tests.config import load_test_config
from system_tests.runner import TestRunner


def main():
    parser = argparse.ArgumentParser(
        description="ERS system test suite — runs against a real environment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", metavar="FILE", default=None,
                         help="Path to system-test-config.json (default: ./system-test-config.json)")
    parser.add_argument("--profile", metavar="PROFILE",
                         help="Override the ~/.ers/config profile from the test config")
    parser.add_argument("--level", type=int, nargs="+", choices=[1, 2, 3], default=[1],
                         help="Which level(s) to run (default: 1)")
    parser.add_argument("--only", metavar="SUBSTRING",
                         help="Only run tests whose name contains this substring")
    parser.add_argument("--skip", metavar="NAME1,NAME2",
                         help="Comma-separated test names to exclude")
    parser.add_argument("--yes", action="store_true",
                         help="Skip the interactive confirmation prompt for level 2/3 "
                              "(the pre-flight summary is still printed)")
    parser.add_argument("--no-dry-run", action="store_true",
                         help="Let level 3 workflows actually execute, instead of dry_run=True")
    parser.add_argument("--list", action="store_true",
                         help="Print the tests that would run and exit, without running them")

    args = parser.parse_args()
    skip_names = set(n.strip() for n in args.skip.split(",")) if args.skip else set()

    selected = [t for t in ALL_TESTS if t.level in args.level]
    if args.only:
        selected = [t for t in selected if args.only in t.name]
    selected = [t for t in selected if t.name not in skip_names]

    if not selected:
        print("No tests match the given --level/--only/--skip filters.")
        sys.exit(1)

    if args.list:
        print("Tests that would run:\n")
        for t in selected:
            flag = "  [DANGEROUS — real production action]" if t.dangerous else ""
            print(f"  L{t.level}  {t.name}{flag}")
        sys.exit(0)

    cfg = load_test_config(args.config)
    if args.profile:
        cfg["profile"] = args.profile

    level3_live = any(t.level == 3 for t in selected) and args.no_dry_run

    # A dry-run level 3 test touches nothing (managed_failover/failback skip every
    # mutating call when dry_run=True) — so it shouldn't need the same confirmation
    # as level 2 or a *live* level 3 run.
    needs_confirmation = any(t.level == 2 for t in selected) or level3_live
    has_dangerous = any(t.dangerous and (t.level == 2 or (t.level == 3 and args.no_dry_run))
                         for t in selected)

    print(f"\n{'='*70}\n  ERS SYSTEM TEST — PRE-FLIGHT SUMMARY\n{'='*70}")
    print(f"  Profile        : {cfg['profile']}")
    print(f"  Source site    : {cfg['source_site']}")
    print(f"  Target site    : {cfg['target_site']}")
    print(f"  Failback site  : {cfg['failback_site']}")
    print(f"  Groups         : {', '.join(cfg['group_names'])}")
    print(f"  Plans          : {', '.join(cfg['plan_names'])}")
    print(f"  VMs file       : {cfg['vms_file']}")
    print(f"  Levels         : {sorted(set(t.level for t in selected))}")
    if any(t.level == 3 for t in selected):
        print(f"  Level 3 mode   : {'LIVE (--no-dry-run)' if args.no_dry_run else 'dry-run (safe)'}")
    print(f"\n  Tests to run:")
    for t in selected:
        flag = "  <-- DANGEROUS: real production action" if t.dangerous else ""
        live_flag = "  <-- will run for real" if (t.level == 3 and level3_live) else ""
        print(f"    L{t.level}  {t.name}{flag}{live_flag}")

    if needs_confirmation and not args.yes:
        print(f"\n  This will perform REAL operations against '{cfg['source_site']}' "
              f"and '{cfg['target_site']}'.")
        response = input(f"  Type the source site name ('{cfg['source_site']}') to continue: ")
        if response.strip() != cfg["source_site"]:
            print("  Confirmation did not match — aborting.")
            sys.exit(1)

    if has_dangerous and not args.yes:
        print(f"\n  You have selected DANGEROUS test(s) that run a REAL production "
              f"failover/failback (not simulated).")
        response = input(f"  Type the target site name ('{cfg['target_site']}') to confirm you "
                          f"want to proceed with these: ")
        if response.strip() != cfg["target_site"]:
            print("  Confirmation did not match — aborting.")
            sys.exit(1)

    e = ers.instance(profile=cfg["profile"])
    e.register_site(cfg["source_site"])
    e.register_site(cfg["target_site"])

    runner = TestRunner()
    for t in selected:
        if t.level == 3:
            runner.run(t, e, cfg, dry_run=not args.no_dry_run)
        else:
            runner.run(t, e, cfg)

    passed = runner.summary()
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
