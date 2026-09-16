"""Fail-closed export checks. Findings never contain matched secret values."""
import argparse
import ipaddress
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

PATTERNS = {
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'telegram-token': re.compile(r'\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}\b'),
    'provider-token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{24,})\b'),
    'personal-home-path': re.compile(r'/(?:Users|home)/[A-Za-z0-9_.-]+/'),
    'personal-email': re.compile(r'[\w.+-]+@(?:gmail|yahoo|hotmail|outlook|icloud|protonmail|mail|yandex)\.[a-z]+',re.I),
    'hardware-model': re.compile(r'\b(?:MacBook(?:Air|Pro)?|Macmini|MacPro|iMac(?:Pro)?)\d+,\d+\b'),
    'hardware-serial': re.compile(r'(?i)(?:serial\s*(?:number)?|hardware\s*uuid)\s*[:=]\s*["\']?[A-Z0-9-]{8,}'),
}
IPV4 = re.compile(r'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])')
DOCUMENTATION_NETS = tuple(ipaddress.ip_network(n) for n in ('192.0.2.0/24','198.51.100.0/24','203.0.113.0/24'))
FORBIDDEN_PARTS = {'.secrets','.remote-access','runtime','agent-state','logs','backups','.venv'}
FORBIDDEN_SUFFIXES = {'.db','.sqlite','.sqlite3','.log','.jsonl','.pem','.key','.torrent','.zip','.tgz','.dmg','.p12','.pfx'}


def forbidden_path(name):
    p=PurePosixPath(name)
    return (p.is_absolute() or '..' in p.parts or any(x in FORBIDDEN_PARTS for x in p.parts)
            or (p.name.startswith('.env') and p.name!='.env.example')
            or p.name in ('agent.json','transmission-rpc.json') or p.suffix in FORBIDDEN_SUFFIXES
            or bool(re.search(r'\.(?:db|sqlite)(?:-wal|-shm|-journal)$',p.name)))


# Reviewed public connectivity probes, not an operator's server addresses.
REVIEWED_ENDPOINTS = {
    path: {'1.1.1.1', '8.8.8.8'}
    for path in ('mac_agent/recovery.py', 'deployment-reference/mac_agent/recovery.py', 'scripts/check_public_tree.py')
}


def content_findings(text, path=None):
    rules=[rule for rule,pattern in PATTERNS.items() if pattern.search(text)]
    for match in IPV4.finditer(text):
        try:address=ipaddress.ip_address(match.group())
        except ValueError:continue
        if str(address) in REVIEWED_ENDPOINTS.get(path, set()):continue
        if not address.is_loopback and not any(address in net for net in DOCUMENTATION_NETS):
            rules.append('non-example-network-address');break
    return rules


def audit(root):
    root=Path(root)
    manifest=root/'PUBLIC_FILES.txt'
    if not manifest.is_file() or manifest.is_symlink():return ['manifest missing or unsafe']
    expected=set(manifest.read_text().splitlines())|{'PUBLIC_FILES.txt'}
    issues=[]; seen=set()
    for p in root.rglob('*'):
        relative=p.relative_to(root)
        if any(part in ('.git','__pycache__') for part in relative.parts):continue
        name=relative.as_posix()
        if p.is_symlink():
            issues.append(name+': symlink');continue
        if not p.is_file():continue
        seen.add(name)
        if forbidden_path(name):
            issues.append(name+': forbidden private/runtime path');continue
        if name not in expected:
            issues.append(name+': not in reviewed manifest');continue
        if p.stat().st_size>1024*1024:
            issues.append(name+': oversized');continue
        try:text=p.read_text(encoding='utf-8')
        except UnicodeError:
            issues.append(name+': binary');continue
        for rule in content_findings(text, name):issues.append(name+': '+rule)
    for missing in sorted(expected-seen):issues.append(missing+': missing')
    return sorted(issues)


def audit_history(root, ref='HEAD'):
    """Check every reachable snapshot plus commit messages and author metadata."""
    def git(*args):
        return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.DEVNULL)
    issues=[]
    try:
        commit=git('rev-parse','--verify',ref+'^{commit}').decode().strip()
        commits=git('rev-list',commit).decode().splitlines()
        for revision in commits:
            metadata=git('show','-s','--format=%an%x00%ae%x00%cn%x00%ce%x00%B',revision).decode()
            author,email,committer,committer_email,message=metadata.split('\x00',4)
            if any(name!='Home Media Assistant contributors' for name in (author,committer)):
                issues.append(revision[:12]+': unreviewed author identity')
            if any(not re.fullmatch(r'[A-Za-z0-9+_.-]+@users\.noreply\.github\.com',x) for x in (email,committer_email)):
                issues.append(revision[:12]+': non-noreply commit email')
            for rule in content_findings(message):issues.append(revision[:12]+': commit-message '+rule)
            with tempfile.TemporaryDirectory() as tmp:
                staging=Path(tmp)
                records=git('ls-tree','-rz',revision).split(b'\0')
                for record in records:
                    if not record:continue
                    info,name=record.split(b'\t',1);mode,kind,oid=info.split()
                    name=name.decode('utf-8')
                    path=PurePosixPath(name)
                    if mode not in (b'100644',b'100755') or kind!=b'blob' or path.is_absolute() or '..' in path.parts:
                        issues.append(revision[:12]+': unsafe tree entry');continue
                    if any(x in ('.git','__pycache__') for x in path.parts):
                        issues.append(revision[:12]+': forbidden tracked metadata/cache');continue
                    if int(git('cat-file','-s',oid.decode()))>1024*1024:
                        issues.append(revision[:12]+': oversized tree entry');continue
                    target=staging/name;target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(git('cat-file','blob',oid.decode()))
                issues.extend(revision[:12]+': '+finding for finding in audit(staging))
    except (subprocess.CalledProcessError,UnicodeError,ValueError,OSError):
        issues.append('history check failed; publication blocked')
    return sorted(set(issues))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--history',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    findings=audit(root)
    if args.history:findings+=audit_history(root)
    for finding in findings:print(finding)
    print('Public tree check: '+('FAIL' if findings else 'PASS'))
    sys.exit(bool(findings))
