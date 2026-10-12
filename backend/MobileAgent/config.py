"""Explicit runtime credentials; no private defaults or environment-file loader."""
import os
import re
from urllib.parse import urlsplit


def validate_config_value(value, name):
    """Reject missing/example values without including their contents in errors."""
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError("Missing required configuration: " + name)
    normalized = value.strip().lower()
    placeholder = re.search(r"replace[ _-]*with|your[ _-]|change[ _-]*me|placeholder", normalized)
    if "://" in normalized:
        try:
            hostname = urlsplit(normalized).hostname or ""
        except ValueError:
            raise RuntimeError("Invalid configuration: " + name) from None
        placeholder = placeholder or hostname.endswith(".invalid") or hostname in {
            "example.com", "example.org", "example.net",
        }
    if placeholder or normalized.startswith("<") and normalized.endswith(">"):
        raise RuntimeError("Replace placeholder configuration: " + name)
    return value


def require_env(name):
    return validate_config_value(os.environ.get(name), name)


def resolve_api_token(explicit_token, env_name):
    if explicit_token is None:
        return require_env(env_name)
    return validate_config_value(explicit_token, env_name)
