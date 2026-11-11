#!/usr/bin/env python3
"""
Song-of-my-Ram Studio — Entry point.
Creative suite turning live Windows/system RAM into Music, Images, Passwords, Video, Text & 3D Models.
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from ram_studio.ui.app import launch_studio


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Song of my RAM Studio")
    parser.add_argument(
        "--admin",
        action="store_true",
        help="Demander l'élévation Administrateur au démarrage (Windows)",
    )
    args = parser.parse_args(argv)
    launch_studio(force_admin=args.admin)


if __name__ == "__main__":
    main()
