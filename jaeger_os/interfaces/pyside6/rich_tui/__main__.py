"""Entry point: ``python -m jaeger_os.interfaces.pyside6.rich_tui``.

Mirrors ``jaeger rich-tui`` (which goes through ``daemon.cli.dispatch``).
Direct ``python -m`` form is handy for hacking on the rich-tui without
going through the installed entry script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .app import run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jaeger rich-tui", add_help=False)
    p.add_argument("--instance", default=None,
                   help="instance name (default: JAEGER_INSTANCE_NAME or 'default')")
    p.add_argument("--session", default="rich-tui",
                   help="session key for chat.send (default: 'rich-tui')")
    p.add_argument("-h", "--help", action="store_true")
    args = p.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger rich-tui [--instance NAME] [--session KEY]\n"
            "\n"
            "  Daemon-attached Rich UI. The 0.1.0 in-process TUI lives\n"
            "  at `jaeger tui` and is unaffected.\n"
            "\n"
            "  Requires a running daemon — start one with `jaeger start`\n"
            "  before launching rich-tui.\n",
            file=sys.stderr,
        )
        return 0

    from jaeger_os.core.instance.instance import (
        default_instance_name, resolve_instance_dir,
    )
    name = args.instance or default_instance_name()
    root = Path(resolve_instance_dir(name))
    sock_path = root / "run" / "jaeger.sock"
    return run(sock_path=sock_path, session_key=args.session)


if __name__ == "__main__":
    sys.exit(main())
