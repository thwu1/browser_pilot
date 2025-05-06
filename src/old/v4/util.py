import fcntl
import os
from pathlib import Path

import yaml


def get_worker_id():
    lockfile = "worker_id.lock"
    if not os.path.exists(lockfile):
        # Create the file and initialize with 0
        with open(lockfile, "w") as f:
            f.write("0")

    with open(lockfile, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        content = f.read().strip()
        if content == "":
            worker_id = 0
        else:
            worker_id = int(content)
        # Write back the incremented worker id
        f.seek(0)
        f.truncate()
        f.write(str(worker_id + 1))
        f.flush()
        # Lock is released when file is closed
    return worker_id


def config_loader(config_path=None):
    """
    Load configuration from a YAML file with simple path resolution.
    """
    # 1. Use provided path or environment variable
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH")

    # 2. Try to use path relative to the browser_pilot repository root
    if config_path is None:
        # Find the browser_pilot directory by going up from this file
        current_dir = Path(__file__).resolve().parent
        # Go up to the src's parent (which should be browser_pilot)
        repo_root = current_dir.parent

        # Look in standard locations
        possible_paths = [
            repo_root / "scripts" / "config.yaml",
            repo_root / "config.yaml",
        ]

        for path in possible_paths:
            if path.exists():
                config_path = str(path)
                break

    # 3. Check if we found a valid path
    if config_path is None or not os.path.isfile(config_path):
        raise FileNotFoundError(
            f"Config file not found. Please create a config.yaml file in the scripts directory "
            f"or set the CONFIG_PATH environment variable."
        )

    # 4. Load the config
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    config["__config_path__"] = config_path
    validate_config(config)
    return config


def validate_config(config: dict):
    assert "monitor" in config, "monitor section is required"
    assert "proxy" in config, "proxy section is required"
    assert "server" in config, "server section is required"


if __name__ == "__main__":
    config = config_loader()
    print(f"Loaded config from: {config.get('__config_path__', 'unknown location')}")
    print(config)
