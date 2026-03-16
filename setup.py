"""
Setup script
"""

from setuptools import setup

setup(
    name="scicd",
    version="0.0.1",
    packages=["scicd"],
    entry_points={
        "console_scripts": [
            "scicd=scicd.cli:main",
        ],
    },
)
