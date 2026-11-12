#!/usr/bin/env python3
"""T-G1: reject old runtime names; account for each justified historical literal."""
import argparse
from collections import Counter
from fnmatch import fnmatchcase
import json
from pathlib import Path
import re
import subprocess
import sys


ROOTS = ('backend/', 'frontend/', 'integrations/', 'scripts/', '.github/')
ROOT_FILES = {'VERSION', 'package.json', 'package-lock.json', 'pyproject.toml',
              'docker-compose.yml', 'Dockerfile', '.env.example', '.gitignore'}
SOURCE_CONFIG_EXTENSIONS = {
    '.py', '.pyi', '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.mts', '.cts',
    '.json', '.jsonc', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.sh', '.bash', '.zsh', '.fish', '.ps1', '.bat', '.cmd', '.sql',
    '.css', '.scss', '.sass', '.less', '.html', '.htm', '.svg', '.xml',
    '.vue', '.svelte', '.astro', '.go', '.rs', '.c', '.h', '.cpp', '.hpp',
    '.java', '.rb', '.php', '.lock', '.env',
}
CONFIG_BASENAMES = {
    'Dockerfile', 'Containerfile', 'Makefile', 'GNUmakefile', 'Justfile',
    '.gitignore', '.gitattributes', '.editorconfig', '.npmrc', '.nvmrc',
    '.prettierrc', '.eslintrc', '.babelrc', '.stylelintrc', '.browserslistrc',
    '.npmignore', '.dockerignore', '.tool-versions', '.env', 'CLAUDE.md', 'AGENTS.md', 'SKILL.md',
}
CONFIG_PREFIXES = ('.env.', '.prettierrc.', '.eslintrc.', '.babelrc.',
                   '.stylelintrc.', 'Dockerfile.', 'Containerfile.')
# The inventory's six-term primary search, plus short-name/protocol surfaces.
PRIMARY = re.compile(r'Claude Deck|claude-deck|claude_deck|CLAUDE_DECK|claude_registry|\.claude-registry', re.I)
SUPPLEMENTAL = re.compile(r'\bDeck\b|\bdeck_[a-z0-9_]+|deck-agent-mail-(?:actor-key|actor-token)|--deck-url')
CATEGORIES = {'conversion_only', 'frozen_constant', 'deny_only', 'negative_fixture', 'history'}
# Exclusions are classes of non-runtime artifacts, never arbitrary production globs.
EXCLUSIONS = {
    ('negative_fixture', 'backend/tests/**'),
    ('negative_fixture', 'frontend/tests/**'),
    ('negative_fixture', 'frontend/e2e/**'),
    ('negative_fixture', 'integrations/pi-agent-mail/tests/**'),
    ('history', 'docs/plans/**'),
    ('history', 'docs/superpowers/**'),
    ('history', 'CHANGELOG.md'),
    ('guard_definition', 'scripts/ci/old_names.py'),
    ('guard_definition', 'scripts/ci/old_name_exceptions.json'),
}


def scan(root, policy):
    errors = []
    if policy.get('schema_version') != 1:
        return ['Invalid exception policy schema']
    exclusions = policy.get('exclusions', [])
    for entry in exclusions:
        if ((entry.get('category'), entry.get('path')) not in EXCLUSIONS
                or not entry.get('reason')):
            errors.append('Invalid exclusion: ' + str(entry.get('path')))
    rules = policy.get('literal_exceptions', [])
    identities = set()
    for rule in rules:
        identity = (rule.get('path'), rule.get('line'))
        if (identity in identities or rule.get('category') not in CATEGORIES
                or not rule.get('reason') or not isinstance(rule.get('count'), int)
                or rule['count'] < 1 or not rule.get('line')
                or any(char in rule.get('path', '') for char in '*?[')):
            errors.append('Invalid literal exception: ' + str(rule.get('path')))
        identities.add(identity)
    if errors:
        return errors
    named = {(rule['path'], rule['line']): rule for rule in rules}
    counts = Counter()
    raw = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--stage', '-z'])
    entries = []
    for record in raw.decode().split('\0'):
        if record:
            metadata, relative = record.split('\t', 1)
            mode, _, stage = metadata.split()
            if stage != '0':
                errors.append(relative + ': unresolved index entry')
                continue
            entries.append((relative, mode))
    for relative, mode in sorted(entries):
        if any(fnmatchcase(relative, entry['path']) for entry in exclusions):
            continue
        path = root / relative
        try:
            content = path.read_text()
        except UnicodeDecodeError:
            continue  # Inventory primary search is text-only (-I).
        except OSError:
            errors.append(relative + ': tracked source is unreadable')
            continue
        if not (relative.startswith(ROOTS) or relative in ROOT_FILES
                or path.name in CONFIG_BASENAMES or path.name.startswith(CONFIG_PREFIXES)
                or path.suffix.lower() in SOURCE_CONFIG_EXTENSIONS
                or mode == '100755' or content.startswith('#!')):
            continue
        for number, line in enumerate(content.splitlines(), 1):
            identity = (relative, line.strip())
            if identity in named:
                counts[identity] += 1
            elif PRIMARY.search(line) or SUPPLEMENTAL.search(line):
                # Do not echo source text or configuration values.
                errors.append(f'{relative}:{number}: unclassified old name')
    for identity, rule in named.items():
        if counts[identity] != rule['count']:
            errors.append(f'{rule["path"]}: exception count {counts[identity]} != {rule["count"]}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--policy', type=Path)
    args = parser.parse_args()
    try:
        policy = json.loads((args.policy or args.root / 'scripts/ci/old_name_exceptions.json').read_text())
        errors = scan(args.root.resolve(), policy)
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print('Old-name policy/source error: ' + type(exc).__name__)
        return 1
    for error in errors:
        print(error)
    if not errors:
        print('Rename old-name guard passed; every exception is named and accounted for.')
    return int(bool(errors))


if __name__ == '__main__':
    sys.exit(main())
