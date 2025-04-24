# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['gtk_llm_chat/main.py'],
    pathex=['gtk_llm_chat'],
    binaries=[],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=2,  # Optimized bytecode
    datas=[
        ('po', 'po'),
    ],
    hiddenimports=[
        'gi',
        'gi.repository',
        'gi.repository.Gtk',
        'gi.repository.Adw',
        'gi.repository.Gio',
        'gi.repository.Gdk',
        'gi.repository.GLib',
        'gettext',
        'llm',
	'llm.default_plugins',
	'llm.default_plugins.openai_models',
	'llm_groq',
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
	'altgraph',
    ]
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='main',
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
    upx=True,  # Use UPX here too
    upx_exclude=[],
    name='main'
)
