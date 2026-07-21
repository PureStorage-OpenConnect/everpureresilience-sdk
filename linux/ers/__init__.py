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
ers — Everpure Resilience Service SDK.

    import ers
    ErsInstance = ers.instance()   # or ers.instance(profile="staging")
"""

from .instance import ErsInstance

__all__ = ["instance", "ErsInstance"]


def instance(**kwargs) -> ErsInstance:
    """Factory matching the ers.instance(...) calling convention."""
    return ErsInstance(**kwargs)
