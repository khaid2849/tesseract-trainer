"""Shallow sparse checkout of only the needed paths of a large repo (no GitHub API, so no rate limit)."""
import logging
import os
import subprocess

from .common import write_manifest

log = logging.getLogger('git')


def run(cmd, cwd=None):
    log.debug('$ %s', ' '.join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def ls_remote(repo):
    out = subprocess.run(['git', 'ls-remote', repo, 'HEAD'], capture_output=True, text=True, timeout=60)
    return out.returncode == 0 and bool(out.stdout.strip())


def checkout(paths, source):
    target = paths.raw_dir(source['id'])
    if not os.path.isdir(os.path.join(target, '.git')):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        run(['git', 'clone', '--depth', '1', '--filter=blob:none', '--no-checkout', '--quiet', source['repo'], target])
    run(['git', 'sparse-checkout', 'init', '--no-cone'], cwd=target)
    run(['git', 'sparse-checkout', 'set', '--no-cone', *[f'/{p}' for p in source['sparse']]], cwd=target)
    run(['git', 'checkout', '--quiet'], cwd=target)
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=target, capture_output=True, text=True).stdout.strip()
    write_manifest(paths, source, source['repo'], target, extra={'commit': commit, 'sparse': source['sparse']})
    log.info('%s: checkout %s (%s)', source['id'], commit[:10], ', '.join(source['sparse']))
    return target
