from PyInstaller.utils.hooks import collect_entry_point
from PyInstaller.utils.hooks import copy_metadata

datas, hiddenimports = collect_entry_point('llm.register_models')
datas += copy_metadata('llm')

