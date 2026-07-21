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

"""ers.sites.base — Site ABC. Extend for aws/azure/flasharray/etc."""

from abc import ABC


class Site(ABC):
    """Base class for all infrastructure sites registered on an ErsInstance."""

    #: set by subclasses — used for register_site() type dispatch
    site_type = None

    def __init__(self, name: str):
        self.name = name
