"""Config and secrets loading. The only place tools read config/ and .env."""
import os
from pathlib import Path

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
ENV_FILE = ROOT / ".env"

# Values shorter than this are not treated as secrets by redact().
MIN_SECRET_LEN = 8


class ConfigError(Exception):
    pass


def load_yaml(name: str, config_dir: Path | None = None) -> dict:
    path = (config_dir or CONFIG_DIR) / name
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return data


def _env_file_values(env_file: Path | None) -> dict[str, str]:
    path = env_file or ENV_FILE
    if not path.is_file():
        return {}
    return {k: v for k, v in dotenv_values(path).items() if v}


def get_secret(name: str, default: str | None = None, env_file: Path | None = None) -> str:
    value = os.environ.get(name) or _env_file_values(env_file).get(name)
    if value:
        return value
    if default is not None:
        return default
    raise ConfigError(f"missing secret {name}: set it in .env")


def redact(text: str, env_file: Path | None = None) -> str:
    file_values = _env_file_values(env_file)
    secrets = set(file_values.values())
    secrets.update(os.environ[k] for k in file_values if os.environ.get(k))
    for secret in sorted((s for s in secrets if len(s) >= MIN_SECRET_LEN), key=len, reverse=True):
        text = text.replace(secret, "***")
    return text
