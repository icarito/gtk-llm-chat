from PyInstaller.utils.hooks import collect_entry_point

# Recolecta TODOs los plugins registrados en 'llm.register_models'
datas, hiddenimports = collect_entry_point('llm.register_models')
