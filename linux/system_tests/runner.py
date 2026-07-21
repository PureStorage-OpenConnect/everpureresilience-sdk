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
system_tests.runner — a small, dependency-free test harness. No pytest
required: this suite is meant to be run by customers against a live
environment, so it stays a single self-contained script.
"""

import time


class TestCase:
    def __init__(self, name: str, level: int, func, dangerous: bool = False):
        self.name = name
        self.level = level
        self.func = func
        self.dangerous = dangerous  # runs a real prod failover/failback


class TestResult:
    def __init__(self, name: str, level: int, status: str, message: str = "", duration: float = 0.0):
        self.name = name
        self.level = level
        self.status = status  # PASS, FAIL, ERROR, SKIP
        self.message = message
        self.duration = duration


class TestRunner:
    def __init__(self):
        self.results = []

    def run(self, case: TestCase, *args, **kwargs):
        print(f"\n-> [L{case.level}] {case.name}")
        print("-" * 60)
        start = time.time()
        try:
            case.func(*args, **kwargs)
            duration = time.time() - start
            self.results.append(TestResult(case.name, case.level, "PASS", "", duration))
            print(f"[PASS] {case.name} ({duration:.1f}s)")
        except AssertionError as e:
            duration = time.time() - start
            self.results.append(TestResult(case.name, case.level, "FAIL", str(e), duration))
            print(f"[FAIL] {case.name}: {e} ({duration:.1f}s)")
        except Exception as e:
            duration = time.time() - start
            self.results.append(TestResult(case.name, case.level, "ERROR", str(e), duration))
            print(f"[ERROR] {case.name}: {e} ({duration:.1f}s)")

    def skip(self, case: TestCase, reason: str):
        self.results.append(TestResult(case.name, case.level, "SKIP", reason))
        print(f"\n-> [L{case.level}] {case.name}\n[SKIP] {case.name}: {reason}")

    def summary(self) -> bool:
        """Print a summary table. Returns True if everything PASSed (SKIPs don't count against it)."""
        print(f"\n{'='*70}\n  SYSTEM TEST SUMMARY\n{'='*70}")
        print(f"  {'Level':<7} {'Test':<35} {'Status':<8} {'Time'}")
        print("  " + "-" * 66)
        for r in self.results:
            print(f"  {r.level:<7} {r.name:<35} {r.status:<8} {r.duration:.1f}s")
            if r.status in ("FAIL", "ERROR"):
                print(f"          {r.message}")

        counts = {}
        for r in self.results:
            counts[r.status] = counts.get(r.status, 0) + 1
        print("\n  " + ", ".join(f"{v} {k}" for k, v in counts.items()))

        return counts.get("FAIL", 0) == 0 and counts.get("ERROR", 0) == 0
