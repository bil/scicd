from setuptools import setup, find_packages

setup(
    name="scicd",
    version="0.0.1",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "luigi>=3.8.0",
        "python-dotenv>=1.1.0",
        "python-gitlab>=6.0.0",
        "python-frontmatter>=1.1.0",
        "PyYAML>=6.0",
        "Jinja2>=3.1.2",
        "cyclopts>=4.10.0",
        "tomli>=2.0.1",
        "rich>=13.7.1",
    ],
    entry_points={
        "console_scripts": [
            "scicd=scicd.cli:app",
        ],
    },
    python_requires=">=3.10",
)
