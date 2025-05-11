from PyInstaller.utils.hooks import collect_entry_point
from PyInstaller.utils.hooks import copy_metadata

datas, hiddenimports = collect_entry_point('llm.register_models')

# Is this really necessary? :think:
datas += copy_metadata('llm-groq')
datas += copy_metadata('llm-gemini')
datas += copy_metadata('llm-grok')
datas += copy_metadata('llm-deepseek')
datas += copy_metadata('llm-perplexity')
datas += copy_metadata('llm-anthropic')
datas += copy_metadata('llm-openrouter')
