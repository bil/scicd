from setuptools import setup, find_packages

setup(
    name="scicd",
    version="0.0.1",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "luigi",
        "python-dotenv",
        "python-gitlab",
        "python-frontmatter",
        "PyYAML",
        "Jinja2",
        "cyclopts",
        "tomli",
        "rich",
        "requests",
        "pydantic",
    ],
    extras_require={"test": ["pytest>=9.0.0", "pytest-mock>=3.12.0", "pylint-pydantic"]},
    entry_points={
        "console_scripts": [
            "scicd=scicd.cli:app",
        ],
    },
    python_requires=">=3.9",
)
