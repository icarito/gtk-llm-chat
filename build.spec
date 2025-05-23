# -*- mode: python ; coding: utf-8 -*-

from argparse import ArgumentParser
from platform import system
from PyInstaller.building.datastruct import TOC
import glob

libdir = '/usr/lib/x86_64-linux-gnu'
patterns = [
  'libadwaita-1.so*',
  'libgtk-4.so*',
  'libgdk-4.so*',
  'libpangocairo-1.0.so*',
]
binaries = []
for pat in patterns:
    for src in glob.glob(os.path.join(libdir, pat)):
        binaries.append((src, '.'))

typedir = '/usr/lib/x86_64-linux-gnu/girepository-1.0'
typelibs = []
for name in ('Adw-1.typelib',
        'Atk-1.0.typelib',
        'AyatanaAppIndicator3-0.1.typelib',
	'DBus-1.0.typelib',
	'DBusGLib-1.0.typelib',
        'GLib-2.0.typelib',
        'GModule-2.0.typelib',
        'GObject-2.0.typelib',
        'Gdk-3.0.typelib',
        'Gdk-4.0.typelib',
        'GdkPixbuf-2.0.typelib',
        'Gio-2.0.typelib'
        'Graphene-1.0.typelib',
        'Gsk-4.0.typelib',
        'Gtk-3.0.typelib',
        'Gtk-4.0.typelib',
        'HarfBuzz-0.0.typelib',
        'Pango-1.0.typelib',
        'PangoCairo-1.0.typelib',
        'cairo-1.0.typelib',
        'freetype2-2.0.typelib',
        'xlib-2.0.typelib'):
    for src in glob.glob(os.path.join(typedir, name)):
        typelibs.append((src, 'gi_typelibs'))

parser = ArgumentParser()
parser.add_argument("--binary", action="store_true")
options = parser.parse_args()

a = Analysis(
    ['gtk_llm_chat/main.py'],
    pathex=['gtk_llm_chat'],
    binaries=binaries,
    hookspath=['hooks'],
    hooksconfig={
        'gi': {
            'icons': ['Adwaita'],
            'themes': ['Adwaita'],
            'module-versions': {
                'Gtk': '4.0',
            }
        }
    },
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=2,
    datas=[
        ('po', 'po'),
        ('gtk_llm_chat/hicolor', 'gtk_llm_chat/hicolor'),
        ('windows/*.png', 'windows')
    ] + typelibs,
    hiddenimports=[
        'gettext',
        'llm',
        'llm.default_plugins',
        'llm.default_plugins.openai_models',
        'llm_groq',
        'llm_gemini',
        'llm_openrouter',
        'llm_perplexity',
        'llm_anthropic',
        'llm_deepseek',
        'llm_grok',
        'sqlite3',
        'ulid',
        'markdown_it',
        'gtk_llm_chat.chat_application',
        'gtk_llm_chat.db_operations',
        'gtk_llm_chat.chat_window',
        'gtk_llm_chat.widgets',
        'gtk_llm_chat.markdownview',
        'gtk_llm_chat.llm_client',
        'gtk_llm_chat.tray_applet',
        'gtk_llm_chat._version',
        'locale',
	'gi.repository.DBus',
    ]
)

pyz = PYZ(a.pure)

if system() == "Linux":
    if not options.binary:
        exe = EXE(
            pyz,
            a.scripts,
            [],
            exclude_binaries=True,
            name='gtk-llm-chat',
            debug=False,
            bootloader_ignore_signals=False,
            strip=True,
            upx=True,
            console=False,
            disable_windowed_traceback=False,
            argv_emulation=False,
            target_arch=None,
            codesign_identity=None,
            entitlements_file=None,
        )
        coll = COLLECT(
            exe,
            a.binaries,
            a.datas,
            strip=True,
            upx=True,
            upx_exclude=[],
            name='gtk-llm-chat',
        )
    else:
        exe = EXE(
            pyz,
            a.scripts,
            a.binaries,
            a.datas,
            [],
            name='gtk-llm-chat',
            debug=False,
            bootloader_ignore_signals=False,
            strip=True,
            upx=True,
            upx_exclude=[],
            runtime_tmpdir=None,
            console=False,
            disable_windowed_traceback=False,
            argv_emulation=False,
            target_arch=None,
            codesign_identity=None,
            entitlements_file=None,
        )
elif system() == "Darwin":
    if not options.binary:
        exe = EXE(
            pyz,
            a.scripts,
            [],
            exclude_binaries=True,
            name='gtk-llm-chat',
            icon='macos/org.fuentelibre.gtk_llm_Chat.icns',
            debug=False,
            bootloader_ignore_signals=False,
            strip=False,
            upx=True,
            console=False,
            disable_windowed_traceback=False,
            argv_emulation=False,
            target_arch=None,
            codesign_identity=None,
            entitlements_file=None,
        )
        coll = COLLECT(
            exe,
            a.binaries,
            a.datas,
            strip=False,
            upx=True,
            upx_exclude=[],
            name='gtk-llm-chat',
        )
        app = BUNDLE(
            coll,
            name='Gtk LLM Chat.app',
            icon='macos/org.fuentelibre.gtk_llm_Chat.icns',
            bundle_identifier=None,
            version=None,
            info_plist={
                'LSUIElement': True,  # Esta opción oculta el ícono en el Dock
            },
        )
    else:
        exe = EXE(
            pyz,
            a.scripts,
            a.binaries,
            a.datas,
            [],
            name='gtk-llm-chat',
            icon='macos/org.fuentelibre.gtk_llm_Chat.icns',
            debug=False,
            bootloader_ignore_signals=False,
            strip=False,
            upx=True,
            upx_exclude=[],
            runtime_tmpdir=None,
            console=False,
            disable_windowed_traceback=False,
            argv_emulation=False,
            target_arch=None,
            codesign_identity=None,
            entitlements_file=None,
            info_plist={
                'LSUIElement': True,  # Esta opción oculta el ícono en el Dock
            },
        )
elif system() == "Windows":
    if not options.binary:
        exe = EXE(
            pyz,
            a.scripts,
            [],
            exclude_binaries=True,
            name='gtk-llm-chat',
            icon='windows/org.fuentelibre.gtk_llm_Chat.ico',
            debug=False,
            bootloader_ignore_signals=False,
            strip=True,
            upx=True,
            console=False,
            disable_windowed_traceback=False,
            argv_emulation=False,
            target_arch=None,
            codesign_identity=None,
            entitlements_file=None,
        )
        coll = COLLECT(
            exe,
            a.binaries,
            a.datas,
            strip=True,
            upx=True,
            upx_exclude=[],
            name='gtk-llm-chat',
        )
    else:
        exe = EXE(
            pyz,
            a.scripts,
            a.binaries,
            a.datas,
            [],
            name='gtk-llm-chat',
            icon='windows/org.fuentelibre.gtk_llm_Chat.ico',
            debug=False,
            bootloader_ignore_signals=False,
            strip=True,
            upx=True,
            upx_exclude=[],
            runtime_tmpdir=None,
            console=False,
            disable_windowed_traceback=False,
            argv_emulation=False,
            target_arch=None,
            codesign_identity=None,
            entitlements_file=None,
        )
