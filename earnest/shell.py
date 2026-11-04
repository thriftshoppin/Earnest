"""Interactive command application and persistent, explicitly started jack."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import struct
import tempfile
import threading

from .audio import host

SCHEMA = 'earnest.jack.v1'
DEFAULT = {'schema': SCHEMA, 'input': None, 'output': None, 'room': None,
           'mode': 'loopback', 'dry_percent': 50, 'wet_percent': 50, 'ceiling_percent': 50}


def default_path():
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Earnest' / 'jack.json'


def _tokens(line):
    # Windows paths must retain backslashes. Quotes allow paths with spaces.
    parts = shlex.split(line, posix=False)
    return [part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in ('"', "'") else part for part in parts]


def _resolve(selector, choices):
    selector = str(selector).strip()
    if not selector: raise ValueError('select a device')
    exact = [d for d in choices if selector.casefold() in (d['id'].casefold(), d['name'].casefold())]
    matches = exact or [d for d in choices if selector.casefold() in d['name'].casefold()]
    if len(matches) != 1:
        raise ValueError('device not found' if not matches else 'device name matches more than one device; use its ID')
    return dict(matches[0])


def _other_earnest_hosts():
    if os.name != 'nt': return []
    result = subprocess.run(['tasklist', '/fo', 'csv', '/nh'], capture_output=True, text=True, check=False)
    if result.returncode: raise RuntimeError('could not check existing Earnest audio processes')
    names = {'earnestaudiohost.exe', 'earnestaudiohost-eq.exe', 'earnestaudiohost-live.exe'}
    return [row[0] for row in csv.reader(result.stdout.splitlines()) if row and row[0].casefold() in names]


class Jack:
    def __init__(self, path=None, app_root=None):
        self.path = Path(path) if path else default_path()
        self.app_root = Path(app_root) if app_root else Path(__file__).resolve().parents[1]
        self.process = None
        self.temp = None
        self.config = self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            if data.get('schema') != SCHEMA: raise ValueError('unsupported saved jack configuration')
            return {**DEFAULT, **data}
        # First use can recover the previous Frankenjack room and endpoint names.
        legacy = self.app_root / 'stagejack' / 'earnest-settings.ini'
        data = dict(DEFAULT)
        if legacy.is_file():
            settings = dict(line.split('=', 1) for line in legacy.read_text(encoding='utf-8-sig', errors='replace').splitlines() if '=' in line)
            data['input'] = {'id': None, 'name': settings.get('Input')} if settings.get('Input') else None
            data['output'] = {'id': None, 'name': settings.get('Output')} if settings.get('Output') else None
            data['room'] = settings.get('Room') or None
        if not data['room']:
            room = self.app_root / 'inbox' / 'rooms' / 'Union-Stairs.room.json'
            if room.is_file(): data['room'] = str(room.resolve())
        return data

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent, delete=False)
        try:
            with handle: json.dump(self.config, handle, indent=2); handle.write('\n')
            os.replace(handle.name, self.path)
        finally:
            if os.path.exists(handle.name): os.unlink(handle.name)

    def devices(self, mode=None):
        return host.capture_devices() if (mode or self.config['mode']) == 'capture' else host.devices()

    def set_device(self, kind, selector):
        choices = self.devices() if kind == 'input' else host.devices()
        self.config[kind] = _resolve(selector, choices)
        self.save()
        print('%s: %s' % (kind, self.config[kind]['name']))

    def set_room(self, value):
        path = Path(value).expanduser().resolve()
        if not path.is_file(): raise ValueError('room file not found: %s' % path)
        from .engine.room import RoomSpec
        RoomSpec.from_dict(json.loads(path.read_text(encoding='utf-8-sig')))
        self.config['room'] = str(path); self.save(); print('room: %s' % path)

    def set_mode(self, mode):
        if mode not in ('loopback', 'capture'): raise ValueError('mode must be loopback or capture')
        if self.config['mode'] != mode: self.config['input'] = None
        self.config['mode'] = mode; self.save(); print('input mode: ' + mode)

    def set_level(self, kind, value, force=False):
        try: percent = int(value)
        except ValueError as exc: raise ValueError('enter a whole number') from exc
        limit = 100 if kind == 'ceiling' else 250
        if not (1 if kind == 'ceiling' else 0) <= percent <= limit:
            raise ValueError('%s must be %s–%s' % (kind, 1 if kind == 'ceiling' else 0, limit))
        if percent > 100 and not force:
            raise ValueError('values above 100 require -f')
        self.config[kind + '_percent'] = percent; self.save()
        print('%s: %s%% (takes effect at next boot)' % (kind, percent))

    def running(self): return self.process is not None and self.process.poll() is None

    def prepare_room(self):
        """Build a reusable native-host profile when its inputs change."""
        room = self.config.get('room')
        if not room or not Path(room).is_file():
            raise ValueError('saved room not found; use set room')
        from .audio.convolution import compile_room
        import numpy
        digest = hashlib.sha256()
        digest.update(b'earnest-prepared-room-v1\0')
        digest.update(Path(room).read_bytes())
        digest.update(json.dumps({'dry': self.config['dry_percent'], 'wet': self.config['wet_percent'],
                                  'sample_rate': 48000, 'layout': 'stereo', 'numpy': numpy.__version__}, sort_keys=True).encode())
        package = Path(__file__).resolve().parent
        for source in sorted((package / 'engine').glob('*.py')) + [package / 'audio' / 'convolution.py']:
            digest.update(source.name.encode()); digest.update(source.read_bytes())
        directory = self.path.parent / 'profiles'
        directory.mkdir(parents=True, exist_ok=True)
        profile = directory / (digest.hexdigest() + '.erir')
        if profile.is_file():
            with profile.open('rb') as stream:
                header = stream.read(20)
            if len(header) == 20:
                magic, version, rate, channels, frames = struct.unpack('<4sIIII', header)
                if (magic, version, rate, channels) == (b'ERIR', 1, 48000, 2) and frames and profile.stat().st_size == 20 + channels * frames * 4:
                    print('Using prepared room profile: %s' % profile, flush=True)
                    return profile
        print('Preparing room profile; the audio route has not started yet...', flush=True)
        with tempfile.NamedTemporaryFile(dir=directory, suffix='.erir', delete=False) as handle:
            pending = Path(handle.name)
        try:
            compile_room(room, pending, dry=self.config['dry_percent']/100, wet=self.config['wet_percent']/100)
            os.replace(pending, profile)
        finally:
            pending.unlink(missing_ok=True)
        print('Room profile prepared: %s' % profile, flush=True)
        return profile

    def stop(self):
        if self.running():
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait(timeout=5)
            print('Jack stopped.')
        else: print('Jack is not running in this shell.')
        self.process = None
        if self.temp is not None: self.temp.cleanup(); self.temp = None

    def clear(self):
        if self.running(): self.stop()
        self.config = dict(DEFAULT); self.save()
        print('Jack configuration cleared. Use configure jack to set it up again.')

    def boot(self):
        if self.running(): raise ValueError('Jack is already running in this shell; use stop first')
        if self.temp is not None: self.temp.cleanup(); self.temp = None
        self.process = None
        others = _other_earnest_hosts()
        if others: raise ValueError('another Earnest audio host is running (%s); stop it first to avoid overlapping routes' % ', '.join(others))
        for field in ('input', 'output', 'room'):
            if not self.config.get(field): raise ValueError('jack %s is not configured; use configure jack' % field)
        input_dev = _resolve(self.config['input'].get('id') or self.config['input'].get('name'), self.devices())
        output_dev = _resolve(self.config['output'].get('id') or self.config['output'].get('name'), host.devices())
        if input_dev['id'].casefold() == output_dev['id'].casefold(): raise ValueError('input and output cannot be the same endpoint')
        if not Path(self.config['room']).is_file(): raise ValueError('saved room not found; use set room')
        profile = self.prepare_room()
        try:
            others = _other_earnest_hosts()
            if others: raise ValueError('another Earnest audio host started during setup; stop it before booting')
            exe = host.ensure_host()
            args = [str(exe), '--bridge', '--input', input_dev['id'], '--output', output_dev['id'],
                    '--ir-profile', str(profile), '--output-limit', str(self.config['ceiling_percent']/100)]
            if self.config['mode'] == 'capture': args.append('--capture-input')
            self.process = subprocess.Popen(args, cwd=exe.parent, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, encoding='utf-8', errors='replace', bufsize=1)
        except BaseException:
            raise
        self.config['input'], self.config['output'] = input_dev, output_dev
        try: self.save()
        except Exception:
            self.stop(); raise
        def read_status(process):
            for line in process.stdout:
                print('\n' + line.rstrip(), flush=True)
            code = process.wait()
            print('\nJack process exited (code %s).' % code, flush=True)
        threading.Thread(target=read_status, args=(self.process,), daemon=True).start()
        print('Jack starting. Wait for BRIDGE READY; use stop to end this route.', flush=True)

    def show(self):
        for key in ('input', 'output'):
            value = self.config.get(key)
            print('%s: %s' % (key, value['name'] if value else '(not set)'))
        print('room: %s' % (self.config.get('room') or '(not set)'))
        print('mode: %s | dry: %s%% | wet: %s%% | ceiling: %s%%' %
              (self.config['mode'], self.config['dry_percent'], self.config['wet_percent'], self.config['ceiling_percent']))
        print('jack: %s' % ('running' if self.running() else 'stopped'))

    def list_devices(self):
        for label, devices in [('Playback (output / loopback input)', host.devices()), ('Recording (capture input)', host.capture_devices())]:
            print('\n' + label + ':')
            for device in devices: print('  %s\n    %s' % (device['name'], device['id']))
            if not devices: print('  (none)')

    def configure(self, ask=input):
        self.list_devices()
        mode = ask('Input mode [loopback/capture] (Enter keeps %s): ' % self.config['mode']).strip().lower()
        if mode: self.set_mode(mode)
        source = ask('Input device name or ID (Enter keeps current): ').strip()
        if source: self.set_device('input', source)
        output = ask('Output device name or ID (Enter keeps current): ').strip()
        if output: self.set_device('output', output)
        room = ask('Room JSON path (Enter keeps current): ').strip().strip('"')
        if room: self.set_room(room)
        self.save(); self.show()


def help_text():
    print('''Core commands:
  configure jack        Set up the input, output and room
  devices / ls dev      List playback and recording devices
  set in NAME           Choose input by device name or ID
  set out NAME          Choose output by device name or ID
  set room "PATH"       Choose a room JSON file
  prep                  Prepare or reuse the selected room profile
  set mode MODE         loopback (playback) or capture (recording)
  set dry N [-f]        Direct level, 0–100%%; -f allows up to 250%%
  set wet N [-f]        Reflections level, 0–100%%; -f allows up to 250%%
  set ceiling N         Output ceiling, 1–100%%; applied at boot
  show                  Show saved configuration and route status
  refresh               Re-list devices and show the saved route
  boot                  Start the saved jack configuration
  stop                  Stop the jack started in this shell
  clear jack            Stop it and clear its saved configuration
  update check          Check the main repository revision
  update stage          Download and build the current repository revision
  update install        Exit and run the staged VM updater
  help                  Show this guide
  exit                  Stop this shell's jack and leave Earnest
Legacy commands still work: type their usual command and arguments here.'''.replace('%%','%'))


def run(jack=None, read=input):
    from .cli import main
    jack = jack or Jack()
    print('Earnest ready. Type help for commands; boot starts the saved jack.')
    try:
        while True:
            try:
                line = read('earnest> ').strip()
                if not line: continue
                args = _tokens(line); command = args[0].lower()
                if command in ('exit','quit','q') and len(args)==1: break
                if command in ('help','?') and len(args)==1: help_text()
                elif args in (['configure','jack'], ['config','jack'], ['configure']): jack.configure(read)
                elif args in (['devices'], ['ls','dev'], ['ls','devices']): jack.list_devices()
                elif args in (['show'], ['show','jack'], ['status']): jack.show()
                elif args == ['refresh']: jack.list_devices(); jack.show()
                elif args in (['prep'], ['prep','room']): jack.prepare_room()
                elif args == ['boot']: jack.boot()
                elif args == ['stop']: jack.stop()
                elif args == ['clear','jack']: jack.clear()
                elif command == 'update' and args in (['update'], ['update','check']):
                    from . import updater
                    info=updater.check(jack.app_root)
                    print('Installed shell: %s | repository shell: %s' % (info['shell_version'], info['remote_shell_version'] or 'unknown'))
                    print('Installed revision: %s%s' % (info['installed_revision'] or 'unknown', ' (local changes included)' if info['installed_dirty'] else ''))
                    print('Repository revision: %s' % info['remote_revision'])
                    print(('Base revision matches; local changes are included.' if info['installed_dirty'] else 'Same revision.') if info['same_revision'] else 'Repository differs or installed revision is unknown; use update stage to prepare it.')
                elif args == ['update','stage']:
                    from . import updater
                    info=updater.check(jack.app_root); staged=updater.stage(info['remote_revision'])
                    print('Update staged: %s. Use update install to apply.' % staged['directory'])
                elif args in (['update','install'], ['update','apply']):
                    from . import updater
                    updater.install(jack.app_root)
                    print('Updater started; closing the shell so it can replace files.')
                    break
                elif command == 'set' and len(args) >= 3:
                    kind=args[1].lower(); value=' '.join(args[2:])
                    if kind in ('in','input'): jack.set_device('input',value)
                    elif kind in ('out','output'): jack.set_device('output',value)
                    elif kind == 'room': jack.set_room(value)
                    elif kind == 'mode': jack.set_mode(value.lower())
                    elif kind in ('dry','wet','ceiling'):
                        force=len(args)==4 and args[3]=='-f'
                        if len(args) != (4 if force else 3) or (force and kind=='ceiling'):
                            raise ValueError('use set %s NUMBER%s' % (kind, ' [-f]' if kind!='ceiling' else ''))
                        jack.set_level(kind,args[2],force)
                    else: print('Unknown setting. Type help.')
                else:
                    try: main(args)
                    except SystemExit as exc:
                        if exc.code not in (0,None): print(exc.code if not isinstance(exc.code,int) else 'Command failed (%s).' % exc.code)
            except EOFError: break
            except KeyboardInterrupt: print('\nUse exit to leave or stop to stop the jack.')
            except (OSError, ValueError, KeyError, RuntimeError, host.AudioHostError) as exc: print('Error: %s' % exc)
    finally:
        if jack.running(): jack.stop()
    return 0
