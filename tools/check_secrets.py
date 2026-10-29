"""Audit working files or every reachable Git blob before publishing."""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PATTERNS=[
    ('private Google Calendar URL',re.compile(rb'https?://calendar\.google\.com/calendar/ical/[^\s"<>]+/private-[a-zA-Z0-9]+/[^\s"<>]+')),
    ('signed SHAD calendar URL',re.compile(rb'https?://lk\.dataschool\.yandex\.ru/users/[^\s"<>]+/classes\.ics')),
    ('GitHub token',re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b')),
    ('Google API key',re.compile(rb'\bAIza[A-Za-z0-9_-]{30,}\b')),
    ('personal Windows home path',re.compile(rb'[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|YOUR_NAME\b)[A-Za-z0-9_.-]+')),
]
EMAIL=re.compile(rb'(?<![A-Za-z0-9_.+:/-])[A-Za-z0-9_.+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})')
SAFE_EMAIL_DOMAINS={b'example.com',b'example.org',b'users.noreply.github.com'}
PRIVATE_NAMES={'config.json','status.json','shad-deadlines.json','shad-sync-status.json',
               'shad-background.json','shad-connected.flag','launch.log','error.log'}


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


def problems(path,data):
    parts=PurePosixPath(path).parts
    name=parts[-1] if parts else ''
    findings=[]
    if name in PRIVATE_NAMES or any(part.endswith('browser-profile') for part in parts):
        findings.append('private runtime file')
    if name.startswith('cache-') or name.endswith('.ics') and path!='examples/demo.ics':
        findings.append('unexpected calendar cache')
    if b'\0' in data:
        return findings
    for label,pattern in PATTERNS:
        if pattern.search(data):
            findings.append(label)
    if any(match[1].lower() not in SAFE_EMAIL_DOMAINS for match in EMAIL.finditer(data)):
        findings.append('personal email address')
    return findings


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--history',action='store_true',help='Inspect every blob in every reachable commit')
    args=parser.parse_args()
    failures=[]
    scanned=set()
    if args.history:
        commits=git('rev-list','--all').decode().splitlines()
        for commit in commits:
            for entry in git('ls-tree','-rz','--full-tree',commit).split(b'\0'):
                if not entry:
                    continue
                metadata,path=entry.split(b'\t',1)
                mode,kind,oid=metadata.split()
                if kind!=b'blob' or (oid,path) in scanned:
                    continue
                scanned.add((oid,path))
                label=path.decode('utf-8')
                for reason in problems(label,git('cat-file','blob',oid.decode())):
                    failures.append((label,reason))
        identities=git('log','--all','--format=%ae%n%ce') if commits else b''
        if any(match[1].lower() not in SAFE_EMAIL_DOMAINS for match in EMAIL.finditer(identities)):
            failures.append(('commit metadata','personal author email'))
    else:
        for raw in git('ls-files','-co','--exclude-standard','-z').split(b'\0'):
            if not raw:
                continue
            path=raw.decode('utf-8')
            file=ROOT/path
            if file.is_file():
                scanned.add(path)
                for reason in problems(path,file.read_bytes()):
                    failures.append((path,reason))
    for path,reason in sorted(set(failures)):
        print(f'{path}: {reason}')  # Never echo a matched secret.
    print(f'Checked {len(scanned)} file versions; findings: {len(set(failures))}')
    return bool(failures)


if __name__=='__main__':
    sys.exit(main())
