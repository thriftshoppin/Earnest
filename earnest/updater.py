"""Check and stage VM updates from immutable Earnest GitHub revisions."""
from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
import uuid

from .version import SHELL_VERSION

REPO_API = 'https://api.github.com/repos/thriftshoppin/Earnest/commits/master'
RAW = 'https://raw.githubusercontent.com/thriftshoppin/Earnest/{}/earnest/version.py'
ARCHIVE = 'https://codeload.github.com/thriftshoppin/Earnest/zip/{}'
SHA = re.compile(r'^[0-9a-f]{40}$')
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXPANDED = 512 * 1024 * 1024


def updates_dir():
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Earnest' / 'updates'


def _read_url(url, limit=1024 * 1024):
    request=urllib.request.Request(url, headers={'User-Agent':'Earnest-shell/'+SHELL_VERSION, 'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data=response.read(limit+1)
    if len(data)>limit: raise ValueError('update response exceeds size limit')
    return data


def check(app_root=None):
    root=Path(app_root) if app_root else Path(__file__).resolve().parents[1]
    metadata=root/'earnest-build.json'
    installed=json.loads(metadata.read_text(encoding='utf-8-sig')) if metadata.is_file() else {}
    result=json.loads(_read_url(REPO_API).decode('utf-8'))
    revision=result.get('sha','').lower()
    if not SHA.fullmatch(revision): raise ValueError('GitHub returned an invalid revision')
    try:
        version_source=_read_url(RAW.format(revision), 65536).decode('utf-8')
        match=re.search(r'^SHELL_VERSION\s*=\s*["\']([0-9A-Za-z.+-]+)["\']\s*$',version_source,re.M)
        remote_version=match.group(1) if match else None
    except (OSError, UnicodeError):
        remote_version=None
    local=installed.get('revision')
    if not isinstance(local,str) or not SHA.fullmatch(local.lower()): local=None
    return {'schema':'earnest.update-check.v1', 'shell_version':SHELL_VERSION,
            'installed_revision':local, 'installed_dirty':bool(installed.get('dirty',False)),
            'remote_revision':revision, 'remote_shell_version':remote_version,
            'same_revision': local.lower()==revision if local else None}


def _unpack(archive, destination):
    root_names=set(); total=0
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            name=entry.filename
            p=PurePosixPath(name)
            if '\\' in name or ':' in name or p.is_absolute() or any(part in ('.','..') for part in p.parts) or not p.parts:
                raise ValueError('unsafe update archive path')
            if stat.S_ISLNK(entry.external_attr >> 16): raise ValueError('symbolic links are not accepted in updates')
            root_names.add(p.parts[0]); total+=entry.file_size
            if total > MAX_EXPANDED: raise ValueError('update archive is too large')
        if len(root_names)!=1: raise ValueError('update archive must contain one source root')
        z.extractall(destination)
    return Path(destination)/next(iter(root_names))


def stage(revision):
    if not isinstance(revision,str) or not SHA.fullmatch(revision): raise ValueError('invalid revision')
    root=updates_dir(); root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='earnest-update-src-') as tmp:
        temp=Path(tmp); archive=temp/'source.zip'
        print('Downloading source for %s...' % revision[:12],flush=True)
        archive.write_bytes(_read_url(ARCHIVE.format(revision),MAX_ARCHIVE))
        source=_unpack(archive,temp/'source')
        build=source/'lab'/'vm'/'Build-VMUpdate.ps1'
        if not build.is_file(): raise ValueError('repository revision does not contain the VM update builder')
        output=root/('staged-'+revision[:12]+'-'+uuid.uuid4().hex[:8])
        env=os.environ.copy();env['EARNEST_BUILD_REVISION']=revision
        print('Building the update. This may take a moment...',flush=True)
        result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(build),'-OutputDirectory',str(output)],cwd=source,env=env,check=False)
        if result.returncode: raise RuntimeError('update build failed (exit %s)' % result.returncode)
        launcher=output/'Update-Earnest-VM.cmd'
        if not launcher.is_file() or not (output/'manifest.json').is_file(): raise RuntimeError('update builder did not produce a complete package')
        state={'schema':'earnest.staged-update.v1','revision':revision,'directory':str(output.resolve())}
        (root/'staged.json').write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8')
        return state


def install(app_root=None):
    if os.name!='nt': raise ValueError('the VM updater currently requires Windows')
    app=Path(app_root) if app_root else Path(__file__).resolve().parents[1]
    if not (app.parent/'python'/'python.exe').is_file(): raise ValueError('this update command requires an installed Earnest VM lab')
    root=updates_dir().resolve(); state_path=root/'staged.json'
    if not state_path.is_file(): raise ValueError('no staged update; run update stage first')
    state=json.loads(state_path.read_text(encoding='utf-8-sig'))
    if state.get('schema')!='earnest.staged-update.v1' or not SHA.fullmatch(state.get('revision','')): raise ValueError('invalid staged update record')
    folder=Path(state['directory']).resolve()
    if not folder.is_relative_to(root): raise ValueError('staged update is outside the update directory')
    launcher=folder/'Update-Earnest-VM.cmd'
    if not launcher.is_file() or not (folder/'manifest.json').is_file(): raise ValueError('staged update is incomplete')
    helper=root/'apply-after-exit.ps1'
    helper.write_text('''param([int]$WaitPid,[string]$Launcher,[string]$InstallDir)
$ErrorActionPreference = 'Stop'
try {
  Write-Host 'Waiting for Earnest to close before updating...'
  if (Get-Process -Id $WaitPid -ErrorAction SilentlyContinue) { Wait-Process -Id $WaitPid -Timeout 60 -ErrorAction Stop }
  $env:EARNEST_LAB_INSTALL_DIR=$InstallDir
  & $Launcher
} catch { Write-Host ("UPDATE FAILED: " + $_.Exception.Message) -ForegroundColor Red; Read-Host 'Press Enter to close' }
''',encoding='utf-8')
    command=['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(helper),'-WaitPid',str(os.getpid()),'-Launcher',str(launcher),'-InstallDir',str(app.parent)]
    subprocess.Popen(command,creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0),close_fds=True)
    return state
