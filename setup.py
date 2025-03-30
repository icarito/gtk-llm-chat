import setuptools
import toml


def get_version():
    with open("pyproject.toml", "r") as f:
        data = toml.load(f)
        version = data["project"]["version"]

        # Write version to _version.py
        version_file = "gtk_llm_chat/_version.py"
        with open(version_file, "w") as f:
            f.write(f'__version__ = "{version}"\n')

        return version


setuptools.setup(
    name="gtk-llm-chat",  # Replace with your own project name
    version=get_version(),
    packages=setuptools.find_packages(),
    install_requires=[
        "PyGObject>=3.42.0",
        "markdown-it-py",
        "llm"
    ],
    entry_points={
        'llm': [
            'gui = gtk_llm_chat.llm_gui',
        ],
        'console_scripts': [
            'gtk-llm-chat = gtk_llm_chat.main:main',
            'gtk-llm-applet = gtk_llm_chat.gtk_llm_applet:main',
        ],
    },
    data_files=[
        ("share/applications", [
            "desktop/gtk-llm-chat.desktop",
            "desktop/gtk-llm-applet.desktop"])
    ]
)
