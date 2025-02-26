from setuptools import setup, find_packages

setup(
    name="gtk-llm-chat",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        'PyGObject',
        'markdown-it-py',
    ],
    entry_points={
        'console_scripts': [
            'gtk-llm-chat=gtk_llm_chat.main:main',
        ],
    },
) 