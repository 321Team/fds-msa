#!/usr/bin/env python3
"""Preserve exact lock comparison evidence; never refresh locks or authorize delivery."""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import re
import stat
import sys

MAX_BYTES = 1024 * 1024


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def read_regular(path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise ValueError('input is not a bounded regular file')
    data = path.read_bytes()
    after = path.lstat()
    if len(data) > MAX_BYTES or (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('input changed while reading')
    return data


def collect(source_dir, work_dir, output_dir, metadata):
    for name, pattern in (('source_sha', r'[0-9a-f]{40}'),
                          ('supply_tool_sha', r'[0-9a-f]{40}'),
                          ('apko_archive_sha256', r'[0-9a-f]{64}'),
                          ('run_id', r'[1-9][0-9]*'), ('run_attempt', r'[1-9][0-9]*')):
        if not re.fullmatch(pattern, str(metadata.get(name, ''))):
            raise ValueError('invalid provenance: ' + name)
    if metadata.get('build_outcome') not in ('success', 'failure', 'cancelled'):
        raise ValueError('invalid build outcome')
    source_dir, work_dir, output_dir = map(Path, (source_dir, work_dir, output_dir))
    resolved_output = output_dir.resolve()
    if resolved_output == source_dir.resolve() or source_dir.resolve() in resolved_output.parents:
        raise ValueError('evidence directory must be outside source checkout')
    output_dir.mkdir(parents=True, exist_ok=False)
    report = {'schema_version': 1, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
              'provenance': dict(metadata), 'collector_sha256': sha256(Path(__file__).read_bytes()),
              'files': {}, 'pairs': {}, 'errors': [],
              'policy': {'lock_update': False, 'harbor_push': 'NOT_EXECUTED',
                         'kubernetes_deploy': 'NOT_EXECUTED', 'delivery_authorization': False}}
    raw = {}
    for kind in ('builder', 'runtime'):
        inputs = {
            kind + '.repo.lock.json': source_dir / ('ci/apko/wolfi-python313-' + kind + '.apko.lock.json'),
            kind + '.generated.lock.json': work_dir / (kind + '.generated.lock.json'),
            kind + '.apko.yaml': source_dir / ('ci/apko/wolfi-python313-' + kind + '.apko.yaml')}
        for name, path in inputs.items():
            try:
                data = read_regular(path)
                (output_dir / name).write_bytes(data)
                report['files'][name] = {'size_bytes': len(data), 'sha256': sha256(data)}
                if name.endswith('.json'):
                    parsed = json.loads(data.decode('utf-8'), object_pairs_hook=unique_object,
                                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite JSON')))
                    if not isinstance(parsed, dict):
                        raise ValueError('lock JSON must be an object')
                    raw[name] = data
            except (OSError, ValueError, UnicodeError):
                # No OS exception text, environment paths or credential-bearing content in logs.
                report['errors'].append({'file': name, 'reason': 'MISSING_UNREADABLE_CHANGED_OR_INVALID'})
        original, generated = kind + '.repo.lock.json', kind + '.generated.lock.json'
        if original in raw and generated in raw:
            equal = raw[original] == raw[generated]
            report['pairs'][kind] = {'byte_equal': equal}
            diff = ''.join(difflib.unified_diff(raw[original].decode('utf-8').splitlines(keepends=True),
                                              raw[generated].decode('utf-8').splitlines(keepends=True),
                                              fromfile=original, tofile=generated))
            (output_dir / (kind + '.diff')).write_bytes(diff.encode('utf-8'))
    if report['errors'] or len(report['pairs']) != 2:
        report['result'], code = 'INCOMPLETE', 2
    elif all(pair['byte_equal'] for pair in report['pairs'].values()):
        report['result'], code = 'MATCH', 0
    else:
        report['result'], code = 'DRIFT', 1
    report['exit_code'] = code
    (output_dir / 'RESULT.json').write_bytes((json.dumps(report, indent=2, sort_keys=True) + '\n').encode('utf-8'))
    lines = [sha256(p.read_bytes()) + '  ' + p.name for p in sorted(output_dir.iterdir()) if p.is_file()]
    (output_dir / 'SHA256SUMS').write_bytes(('\n'.join(lines) + '\n').encode('ascii'))
    return report, code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('source-dir', 'work-dir', 'output-dir', 'source-sha', 'supply-tool-sha',
                'apko-version', 'apko-archive-sha256', 'run-id', 'run-attempt', 'build-outcome'):
        parser.add_argument('--' + arg, required=True)
    args = vars(parser.parse_args())
    paths = {k: args.pop(k) for k in ('source_dir', 'work_dir', 'output_dir')}
    try:
        report, code = collect(**paths, metadata=args)
    except (OSError, ValueError):
        print(json.dumps({'result': 'INCOMPLETE', 'reason': 'PROVENANCE_OR_EVIDENCE_WRITE_FAILED'}))
        return 2
    print(json.dumps({'result': report['result'], 'pairs': report['pairs'], 'errors': report['errors'],
                      'source_sha': args['source_sha'], 'supply_tool_sha': args['supply_tool_sha']}))
    return code


if __name__ == '__main__':
    sys.exit(main())
