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

from .base import Site
from .vsphere import VSphereSite, is_vsphere_instance

#: site_type string (as used in `[site <type> <name>]`) -> class
SITE_TYPES = {
    "vsphere": VSphereSite,
}

#: ordered list of (detector, class) for register_site(name, instance) dispatch
INSTANCE_DETECTORS = [
    (is_vsphere_instance, VSphereSite),
]

__all__ = ["Site", "VSphereSite", "SITE_TYPES", "INSTANCE_DETECTORS"]
