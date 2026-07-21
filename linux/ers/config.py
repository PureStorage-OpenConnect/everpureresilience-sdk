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
ers.config — loads ~/.ers/config (non-secret) and ~/.ers/credentials (secret).

~/.ers/config (profiles, like ~/.aws/config):

    [default]
    base_url      = https://api.pure1.purestorage.com
    deployment_id = your-deployment-id
    output        = txt

    [staging]
    base_url      = https://api.pure1.purestorage.com
    deployment_id = your-staging-deployment-id
    output        = json

~/.ers/credentials (secrets — Pure1 auth material + site credentials):

    [ers]
    app_id           = pure1:apikey:YOUR_APP_ID
    private_key_path = ~/.ers/ers-private-decrypt.pem
    # alternatives — skip JWT generation entirely:
    # bearer_token   = eyJ0...
    # jwt_file       = ~/.ers/ers.jwt

    [site vsphere prod-dc]
    host     = vcenter-source.example.com
    user     = administrator@vsphere.local
    pass     = yourpassword
    insecure = true

    [site vsphere dr-dc]
    host     = vcenter-target.example.com
    user     = administrator@vsphere.local
    pass     = yourpassword

    [site aws cloud-dc]
    aws_access_key_id     = AKIA...
    aws_secret_access_key = ...
    region                = us-west-2
"""

import configparser
import os
import stat
import sys

ERS_DIR             = os.path.expanduser("~/.ers")
DEFAULT_CONFIG_PATH = os.path.join(ERS_DIR, "config")
DEFAULT_CREDS_PATH  = os.path.join(ERS_DIR, "credentials")
STATE_DIR           = os.path.join(ERS_DIR, "state")

SITE_SECTION_PREFIX = "site "


def warn_if_not_600(path: str):
    """Warn (not fatal) if a secrets file is readable/writable by group or others."""
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        return
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        print(f"Warning: {path} has permissive permissions ({oct(mode)}). "
              f"Recommend: chmod 600 {path}", file=sys.stderr)


def _read_ini(path: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str  # preserve case in keys
    if os.path.exists(path):
        parser.read(path)
    return parser


def load_config(profile: str = "default", path: str = None) -> dict:
    """Load a profile section from ~/.ers/config. Missing file/profile -> {}."""
    path = path or DEFAULT_CONFIG_PATH
    parser = _read_ini(path)
    if profile not in parser:
        return {}
    return dict(parser[profile])


def load_credentials(path: str = None) -> configparser.ConfigParser:
    """Load the raw ~/.ers/credentials ConfigParser, warning on loose permissions."""
    path = path or DEFAULT_CREDS_PATH
    warn_if_not_600(path)
    return _read_ini(path)


def get_ers_credentials(creds: configparser.ConfigParser) -> dict:
    """Return the [ers] section (Pure1 auth material) as a dict."""
    if "ers" not in creds:
        return {}
    return dict(creds["ers"])


def get_site_credentials(creds: configparser.ConfigParser, name: str):
    """
    Find a `[site <type> <name>]` section by site name.
    Returns (site_type, creds_dict) or (None, None) if not found.
    """
    for section in creds.sections():
        if not section.startswith(SITE_SECTION_PREFIX):
            continue
        rest = section[len(SITE_SECTION_PREFIX):].strip()
        parts = rest.split(None, 1)
        if len(parts) != 2:
            continue
        ptype, pname = parts[0].strip(), parts[1].strip()
        if pname == name:
            return ptype, dict(creds[section])
    return None, None


def state_path(*parts) -> str:
    """Return a path under ~/.ers/state, creating the directory if needed."""
    os.makedirs(STATE_DIR, exist_ok=True)
    return os.path.join(STATE_DIR, *parts)
