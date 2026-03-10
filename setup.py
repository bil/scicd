"""
Setup script
"""

from setuptools import setup

setup(
    name="scicd",
    version="0.0.3",
    packages=["scicd", "scicd.resources"],
    include_package_data=True,
    package_data={
        "scicd.resources": ["*.yaml"],
    },
    install_requires=[
        "fire",
        "python-dotenv",
        "python-frontmatter",
        "jinja2",
        "pyyaml",
        "requests",
        "python-gitlab",
        "google-cloud-pubsub",
        "joblib",
    ],
    entry_points={
        "console_scripts": [
            "scicd=scicd.cli:main",
        ],
    },
)
