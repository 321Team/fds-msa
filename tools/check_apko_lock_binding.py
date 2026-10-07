#!/usr/bin/env python3
"""Fail unless each committed apko lock is bound to its committed YAML config.

Usage: check_apko_lock_binding.py CFG LOCK [CFG LOCK ...]

apko records the config path and ``sha256-<base64 digest>`` of the YAML bytes in
``config.name`` / ``config.checksum``. Building from a committed lock is only
reproducible for the reviewed source when that binding holds, so this check is
blocking. Whether the lock is still what the rolling upstream index resolves to
is a separate, non-blocking freshness observation.
"""
import base64
import hashlib
import json
from pathlib import Path
import sys

MAX_BYTES = 1024 * 1024


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def apko_checksum(data):
    return 'sha256-' + base64.b64encode(hashlib.sha256(data).digest()).decode('ascii')


def check(cfg_path, lock_path):
    cfg, lock = Path(cfg_path), Path(lock_path)
    for path in (cfg, lock):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError(f'{path}: not a bounded regular file')
    data = json.loads(lock.read_bytes(), object_pairs_hook=unique_object)
    config = data.get('config') if isinstance(data, dict) else None
    if not isinstance(config, dict):
        raise ValueError(f'{lock}: missing config object')
    if config.get('name') != cfg_path:
        raise ValueError(f'{lock}: config.name {config.get("name")!r} != {cfg_path!r}')
    expected = apko_checksum(cfg.read_bytes())
    if config.get('checksum') != expected:
        raise ValueError(f'{lock}: config.checksum does not match {cfg_path}')
    packages = data.get('contents', {}).get('packages')
    if not isinstance(packages, list) or not packages:
        raise ValueError(f'{lock}: no locked packages')
    return f'APKO_LOCK_CONFIG_BINDING=PASS {cfg_path} {expected} packages={len(packages)}'


def main(argv):
    if len(argv) < 2 or len(argv) % 2:
        print('usage: check_apko_lock_binding.py CFG LOCK [CFG LOCK ...]', file=sys.stderr)
        return 2
    try:
        for cfg, lock in zip(argv[0::2], argv[1::2]):
            print(check(cfg, lock))
    except (OSError, ValueError) as exc:
        print(f'APKO_LOCK_CONFIG_BINDING=FAIL {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
