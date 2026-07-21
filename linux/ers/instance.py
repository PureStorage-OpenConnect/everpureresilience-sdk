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
ers.instance — ErsInstance: the root object.

    import ers
    ErsInstance = ers.instance()                       # reads ~/.ers/config + credentials
    ErsInstance.register_site("prod-dc")            # host/user/pass from credentials
    ErsInstance.register_site("dr-dc", si)          # or wrap a live SmartConnect() session

    ErsInstance.group.list()
    ErsInstance.plan.failover("prod", "PLAN-1")
    ErsInstance.workflow.managed_failover(
        vms_file="vm-list.txt", group_names=["G1"], plan_names=["P1"],
        from_site="prod-dc", to_site="dr-dc", with_tags=True)
"""

import sys

from . import auth, config as ers_config
from .http import ApiClient
from .formatting import Output
from .resources import GroupResource, PlanResource, SiteResource, PolicyResource
from .workflow import Workflow
from .sites import SITE_TYPES, INSTANCE_DETECTORS


class ErsInstance:
    def __init__(self, base_url: str = None, deployment_id: str = None, output: str = None,
                 profile: str = "default", app_id: str = None, priv_key: str = None,
                 bearer_token: str = None, jwt_file: str = None,
                 config_path: str = None, credentials_path: str = None):
        """
        Resolution order for base_url/deployment_id/output: explicit kwargs
        override ~/.ers/config's [profile] section.
        Resolution order for auth: explicit bearer_token/jwt_file/app_id+priv_key
        kwargs override ~/.ers/credentials' [ers] section.
        """
        cfg   = ers_config.load_config(profile, config_path)
        creds = ers_config.load_credentials(credentials_path)
        ers_creds = ers_config.get_ers_credentials(creds)

        self.base_url      = base_url or cfg.get("base_url")
        self.deployment_id = deployment_id or cfg.get("deployment_id")
        out_fmt            = (output or cfg.get("output") or "txt").lower()

        if not self.base_url or not self.deployment_id:
            print("Error: base_url and deployment_id are required "
                  "(pass explicitly or set in ~/.ers/config).")
            sys.exit(1)
        if out_fmt not in ("txt", "json"):
            print(f"Error: output must be 'txt' or 'json', got '{out_fmt}'")
            sys.exit(1)

        # auth kwargs override credentials file
        merged_auth = dict(ers_creds)
        if bearer_token:
            merged_auth["bearer_token"] = bearer_token
        if jwt_file:
            merged_auth["jwt_file"] = jwt_file
        if app_id:
            merged_auth["app_id"] = app_id
        if priv_key:
            merged_auth["private_key_path"] = priv_key

        token = auth.resolve_bearer_token({"base_url": self.base_url}, merged_auth)

        self.output = Output(out_fmt)
        self.api    = ApiClient(self.base_url, token)
        self._creds = creds  # raw ConfigParser, for site lookups

        # resource namespaces
        self.group  = GroupResource(self)
        self.plan   = PlanResource(self)
        self.site   = SiteResource(self)
        self.policy = PolicyResource(self)
        self.workflow = Workflow(self)

        # registered sites, keyed by name
        self.sites = {}

    # ----------------------------------------------------------------
    # Site registration
    # ----------------------------------------------------------------

    def register_site(self, name: str, instance=None):
        """
        register_site("prod-dc")        -- look up host/user/pass in
                                                ~/.ers/credentials [site <type> prod-dc]
        register_site("dr-dc", si)      -- wrap an already-connected
                                                site instance (type auto-detected)
        """
        if instance is not None:
            for detector, cls in INSTANCE_DETECTORS:
                if detector(instance):
                    site = cls(name, si=instance)
                    self.sites[name] = site
                    return site
            print(f"Error: could not detect site type for the instance passed "
                  f"to register_site('{name}', ...). Supported types: "
                  f"{', '.join(SITE_TYPES)}")
            sys.exit(1)

        ptype, pcreds = ers_config.get_site_credentials(self._creds, name)
        if ptype is None:
            print(f"Error: no [site <type> {name}] section found in "
                  f"~/.ers/credentials, and no instance was passed.")
            sys.exit(1)
        if ptype not in SITE_TYPES:
            print(f"Error: unknown site type '{ptype}' for '{name}'. "
                  f"Supported types: {', '.join(SITE_TYPES)}")
            sys.exit(1)

        cls = SITE_TYPES[ptype]
        if ptype == "vsphere":
            site = cls(name, host=pcreds.get("host"), user=pcreds.get("user"),
                            password=pcreds.get("pass"),
                            insecure=pcreds.get("insecure", "true").lower() != "false",
                            port=int(pcreds.get("port", 443)))
        else:
            site = cls(name, **pcreds)

        self.sites[name] = site
        return site

    def flush(self):
        """Flush accumulated JSON output (call once at the end of a script)."""
        self.output.flush_json()
