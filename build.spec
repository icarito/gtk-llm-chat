# -*- mode: python ; coding: utf-8 -*-

from argparse import ArgumentParser
from platform import system
from PyInstaller.building.datastruct import TOC
<<<<<<< HEAD
=======
import os
>>>>>>> 062775f (Attempt  to fix harfbuzz error on mac)

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
                'Gtk': '4.0',
		'HarfBuzz': '0.0'
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
        'gtk_llm_chat._version',
        'locale',
    ]
)

# --- Inicio del código de filtrado ---
<<<<<<< HEAD
# Filtrar libharfbuzz.0.dylib de Pillow de los binarios recolectados
filtered_binaries = TOC()
if hasattr(a, 'binaries') and isinstance(a.binaries, TOC):
    for name, path, type_ in a.binaries:
        # Comprobar si la ruta de origen contiene 'PIL' o 'Pillow' y el nombre del archivo es de HarfBuzz
        # El nombre del archivo en el bundle podría ser simplemente 'libharfbuzz.0.dylib'
        # o podría estar en una subcarpeta como 'PIL/__dot_dylibs/libharfbuzz.0.dylib'
        # El path de origen es más fiable para identificar si viene de Pillow.
        is_pillow_harfbuzz = False
        if isinstance(path, str) and ('/PIL/' in path or '/Pillow/' in path or path.endswith('.dylibs/libharfbuzz.0.dylib')):
            if 'libharfbuzz' in name.lower():
                is_pillow_harfbuzz = True
        
=======
# Excluir la HarfBuzz de Pillow y añadir la de Homebrew (GTK) si existe en macOS
filtered_binaries = TOC()
harfbuzz_path = '/opt/homebrew/lib/libharfbuzz.0.dylib'  # Apple Silicon
def _harfbuzz_exists(path):
    try:
        return os.path.exists(path)
    except Exception:
        return False
if not _harfbuzz_exists(harfbuzz_path):
    harfbuzz_path = '/usr/local/lib/libharfbuzz.0.dylib'  # Intel
extra_harfbuzz = None
if system() == "Darwin" and _harfbuzz_exists(harfbuzz_path):
    extra_harfbuzz = (os.path.basename(harfbuzz_path), harfbuzz_path, 'BINARY')

if hasattr(a, 'binaries') and isinstance(a.binaries, TOC):
    for name, path, type_ in a.binaries:
        # Excluir cualquier HarfBuzz que venga de Pillow
        is_pillow_harfbuzz = False
        if 'libharfbuzz' in name.lower() and isinstance(path, str) and ('/PIL/' in path or '/Pillow/' in path or path.endswith('.dylibs/libharfbuzz.0.dylib')):
            is_pillow_harfbuzz = True
>>>>>>> 062775f (Attempt  to fix harfbuzz error on mac)
        if is_pillow_harfbuzz:
            print(f"INFO: build.spec: Excluding Pillow's HarfBuzz: name='{name}', path='{path}'")
        else:
            filtered_binaries.append((name, path, type_))
<<<<<<< HEAD
    a.binaries = filtered_binaries
else:
    print("WARNING: build.spec: a.binaries no es una instancia de TOC o no existe, no se pudo filtrar HarfBuzz de Pillow.")

=======
    # Añadir la HarfBuzz de Homebrew si existe y no está ya incluida
    if extra_harfbuzz and not any(name == extra_harfbuzz[0] for name, _, _ in filtered_binaries):
        filtered_binaries.append(extra_harfbuzz)
        print(f"INFO: build.spec: Including Homebrew HarfBuzz: {extra_harfbuzz[1]}")
    a.binaries = filtered_binaries
else:
    print("WARNING: build.spec: a.binaries no es una instancia de TOC o no existe, no se pudo filtrar HarfBuzz de Pillow.")
>>>>>>> 062775f (Attempt  to fix harfbuzz error on mac)
# --- Fin del código de filtrado ---

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
        applet_exe = EXE(
            applet_pyz,
            applet.scripts,
            [],
            exclude_binaries=True,
            name='gtk-llm-applet',
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
            applet.binaries,
            applet.datas,
            strip=False,
            upx=True,
            upx_exclude=[],
            name='gtk-llm-chat',
        )
        app = BUNDLE(
            coll,
            name='gtk-llm-chat.app',
            icon='macos/org.fuentelibre.gtk_llm_Chat.icns',
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
            debug=True,
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
