#!/usr/bin/env python3
"""Fail when upstream drift is observed and the committed locks are too old.

Usage: check_apko_lock_age.py [--max-days N] [--now EPOCH] LOCK [LOCK ...]

Freshness drift is a warning, not a gate, but DEC-P1-IMG-01 caps how long it may
stay unresolved (3 days). The workflow calls this only after it has observed
drift. The age is measured from the author time of the last commit that touched
any of the given lock files, i.e. when the lock refresh was generated and
committed; merge commits keep that time. A shallow clone would report the
checkout commit instead, so it is rejected.
"""
import subprocess
import sys
import time

DEFAULT_MAX_DAYS = 3


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True, text=True).stdout.strip()


def lock_epoch(locks):
    if git('rev-parse', '--is-shallow-repository') != 'false':
        raise ValueError('shallow clone: lock commit time is unknown (use fetch-depth: 0)')
    stamp = git('log', '-1', '--format=%at', '--', *locks)
    if not stamp.isdigit():
        raise ValueError(f'no commit touches {" ".join(locks)}')
    return int(stamp)


def main(argv):
    max_days, now, locks = DEFAULT_MAX_DAYS, None, []
    args = iter(argv)
    try:
        for arg in args:
            if arg == '--max-days':
                max_days = int(next(args))
            elif arg == '--now':
                now = int(next(args))
            else:
                locks.append(arg)
    except (StopIteration, ValueError):
        locks = []
    if not locks or max_days < 1:
        print('usage: check_apko_lock_age.py [--max-days N] [--now EPOCH] LOCK [LOCK ...]', file=sys.stderr)
        return 2
    try:
        committed = lock_epoch(locks)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f'APKO_LOCK_DRIFT_AGE=FAIL {exc}', file=sys.stderr)
        return 1
    age = (int(time.time()) if now is None else now) - committed
    limit = max_days * 86400
    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(committed))
    if age > limit:
        print(f'APKO_LOCK_DRIFT_AGE=OVER_LIMIT lock_committed={stamp} age_hours={age // 3600} '
              f'limit_days={max_days}', file=sys.stderr)
        return 1
    print(f'APKO_LOCK_DRIFT_AGE=WITHIN_LIMIT lock_committed={stamp} age_hours={age // 3600} '
          f'limit_days={max_days}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
