from PyInstaller.utils.hooks import collect_entry_point, collect_submodules
from PyInstaller.utils.hooks import copy_metadata

datas, hiddenimports = collect_entry_point('llm.register_models')
datas += copy_metadata('llm')

# Recoger explícitamente todos los submódulos de default_plugins
hiddenimports += collect_submodules('llm.default_plugins')

