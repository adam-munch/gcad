import os
import json

CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.gcad')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.json')

DEFAULT_CONFIG = {
    'repo_url': '',
    'local_path': '',
    'remote_name': 'origin',
    'branch': '',
}


def get_config_path():
    return CONFIG_PATH


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, 'r') as f:
            data = json.load(f)
        # JSON configuration must be an object.  Reject arrays and other
        # valid JSON values before attempting to read named settings.
        if not isinstance(data, dict):
            return None

        cfg = dict(DEFAULT_CONFIG)
        for key, default in DEFAULT_CONFIG.items():
            value = data.get(key, default)
            cfg[key] = value if isinstance(value, str) else default
        return cfg
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)


def config_exists():
    return os.path.exists(CONFIG_PATH)
