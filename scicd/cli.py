"""
CLI interface for scicd.
"""

import os
import sys

import fire
import scicd.build


def main():
    """
    Main entry point for the scicd CLI.
    """
    # Ensure current project directory is in path for loading user modules
    sys.path.insert(0, os.getcwd())
    fire.Fire({"build_gitlab": scicd.build.build_gitlab})


if __name__ == "__main__":
    main()
