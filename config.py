import os
import json
import tempfile

CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.gcad')
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.json')

DEFAULT_CONFIG = {
    'repo_url': '',
    'local_path': '',
    'remote_name': 'origin',
    'branch': '',
    'theme': 'system',
}


def get_config_path():
    return CONFIG_PATH


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # JSON configuration must be an object.  Reject arrays and other
        # valid JSON values before attempting to read named settings.
        if not isinstance(data, dict):
            return None

        cfg = dict(DEFAULT_CONFIG)
        for key, default in DEFAULT_CONFIG.items():
            value = data.get(key, default)
            cfg[key] = value if isinstance(value, str) else default
        if cfg['theme'] not in ('light', 'dark', 'system'):
            cfg['theme'] = 'system'
        return cfg
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return None


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    # A failed write must not corrupt a previously working configuration.
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=CONFIG_DIR, delete=False) as f:
            temporary_path = f.name
            json.dump(config, f, indent=2)
        os.replace(temporary_path, CONFIG_PATH)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def config_exists():
    return os.path.exists(CONFIG_PATH)
