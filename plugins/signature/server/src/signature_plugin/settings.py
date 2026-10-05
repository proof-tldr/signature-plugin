"""Where Signature is, the key that opens the customer's domain, and where the plugin keeps its own files."""

import os
from dataclasses import dataclass
from pathlib import Path

import platformdirs


@dataclass(frozen=True)
class Settings:
    api_url: str
    api_key: str
    data_dir: Path


class NotConfigured(Exception):
    """The plugin was started without what it needs to reach Signature."""


def from_environment() -> Settings:
    api_url = os.environ.get('SIGNATURE_API_URL', '').strip()
    api_key = os.environ.get('SIGNATURE_API_KEY', '').strip()
    if not api_url:
        raise NotConfigured('The plugin does not know where Signature is: SIGNATURE_API_URL is not set.')
    if not api_key:
        raise NotConfigured('No Signature API key is set. Run /plugin configure signature@signature to enter it.')
    return Settings(api_url=api_url.rstrip('/'), api_key=api_key, data_dir=data_folder())


def data_folder() -> Path:
    """The plugin's own folder on this machine, created readable by this user only."""
    folder = Path(os.environ.get('SIGNATURE_DATA_DIR') or platformdirs.user_data_dir('signature-plugin'))
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    return folder
