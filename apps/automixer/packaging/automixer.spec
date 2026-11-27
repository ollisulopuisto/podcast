# PyInstaller spec. Bundled ffmpeg/ffprobe must be standalone arm64 binaries.
import os
import tomllib
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPEC).resolve().parents[3]
APP = ROOT / 'apps/automixer'
version = tomllib.loads((APP / 'pyproject.toml').read_text())['project']['version']
media = Path(os.environ['AUTOMIXER_MEDIA_DIR']).resolve()
identity = os.environ.get('APPLE_SIGNING_IDENTITY')
entitlements = str(APP / 'packaging/Automixer.entitlements')
datas, binaries, hiddenimports = [], [], []
for package in ('mlx', 'pedalboard', 'llvmlite'):
    data, binary, imports = collect_all(package)
    datas += data
    binaries += binary
    hiddenimports += imports
for package in ('automixer', 'speechmix', 'nhsx', 'watchdog.observers'):
    hiddenimports += collect_submodules(package)
hiddenimports += ['AppKit', 'Foundation', 'objc']
binaries += [(str(media / name), 'bin') for name in ('ffmpeg', 'ffprobe')]
a = Analysis([str(APP / 'packaging/launcher.py')],
             pathex=[str(APP / 'src'), str(ROOT / 'packages/speechmix/src'), str(ROOT / 'packages/nhsx/src')],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=['tkinter', 'IPython', 'matplotlib', 'pytest'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Automixer',
          console=True, argv_emulation=False, target_arch='arm64',
          codesign_identity=identity, entitlements_file=entitlements)
coll = COLLECT(exe, a.binaries, a.datas, name='Automixer')
app = BUNDLE(coll, name='Automixer.app', bundle_identifier='com.sulopuis.automixer',
             codesign_identity=identity, entitlements_file=entitlements,
             info_plist={'CFBundleName': 'Automixer', 'CFBundleDisplayName': 'Automixer',
                         'CFBundleVersion': version, 'CFBundleShortVersionString': version,
                         'NSHighResolutionCapable': True, 'LSMinimumSystemVersion': '13.0',
                         'CFBundleDocumentTypes': [{'CFBundleTypeName': 'Media file',
                           'CFBundleTypeRole': 'Viewer', 'LSHandlerRank': 'Alternate',
                           'LSItemContentTypes': ['public.audio', 'public.movie']}]})
