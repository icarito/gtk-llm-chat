
# -*- mode: python ; coding: utf-8 -*-

from argparse import ArgumentParser
from platform import system

parser = ArgumentParser()
parser.add_argument("--binary", action="store_true")
options = parser.parse_args()

a = Analysis(
    ['gtk_llm_chat/main.py'],
    pathex=['gtk_llm_chat'],
    binaries=[],
    hookspath=['hooks'],
    hooksconfig={
        'gi': {
            'icons': ['Adwaita'],
            'themes': ['Adwaita'],
            'module-versions': {
                'Gtk': '4.0'
            }
        }
    },
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=2,
    datas=[
        ('po', 'po'),
	('gtk_llm_chat/hicolor', 'gtk_llm_chat/hicolor')
    ],
    hiddenimports=[
        'gettext',
        'llm',
        'llm.default_plugins',
        'llm.default_plugins.openai_models',
        'llm_groq',
        'llm_gemini',
        'llm_openrouter',
        'llm_perplexity',
        'sqlite3',
        'ulid',
        'markdown_it',
        'gtk_llm_chat.chat_application',
        'gtk_llm_chat.db_operations',
        'gtk_llm_chat.chat_window',
        'gtk_llm_chat.widgets',
        'gtk_llm_chat.markdownview',
        'gtk_llm_chat.llm_client',
        'gtk_llm_chat._version',
        'locale',
    ]
)
pyz = PYZ(a.pure)

applet = Analysis(
    ['gtk_llm_chat/gtk_llm_applet.py'],
    pathex=['gtk_llm_chat'],
    binaries=[],
    hookspath=['hooks'],
    hooksconfig={
        'gi': {
            'icons': ['Adwaita'],
            'themes': ['Adwaita'],
            'module-versions': {
                'Gtk': '3.0'
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
    ],
    hiddenimports=[
        'gettext',
        'sqlite3',
        'ulid',
        'gtk_llm_chat.db_operations',
        'locale',
    ]
)
applet_pyz = PYZ(applet.pure)

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
            strip=False,
            upx=True,
            console=False,
            disable_windowed_traceback=False,
            argv_emulation=False,
            target_arch=None,
            codesign_identity=None,
            entitlements_file=None,
        )
        applet_exe = EXE(
            applet_pyz,
            applet.scripts,
            [],
            exclude_binaries=True,
            name='gtk-llm-applet',
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
            applet.binaries,
            applet.datas,
            strip=False,
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
        )
elif system() == "Darwin":
    if not options.binary:
        exe = EXE(
            pyz,
            a.scripts,
            [],
            exclude_binaries=True,
            name='hello-world-gtk',
            icon='macos/org.example.HelloWorldGTK.icns',
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
            name='hello-world-gtk',
        )
        app = BUNDLE(
            coll,
            name='Hello World.app',
            icon='macos/org.example.HelloWorldGTK.icns',
            bundle_identifier=None,
            version=None,
        )
    else:
        exe = EXE(
            pyz,
            a.scripts,
            a.binaries,
            a.datas,
            [],
            name='hello-world-gtk',
            icon='macos/org.example.HelloWorldGTK.icns',
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
            strip=False,
            upx=True,
            console=False,
            disable_windowed_traceback=False,
            argv_emulation=False,
            target_arch=None,
            codesign_identity=None,
            entitlements_file=None,
        )
        applet_exe = EXE(
            applet_pyz,
            applet.scripts,
            [],
            exclude_binaries=True,
            name='gtk-llm-applet',
            icon='windows/org.fuentelibre.gtk_llm_Chat.ico',
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
            applet_exe,
            applet.binaries,
            applet.datas,
            strip=False,
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
        )
