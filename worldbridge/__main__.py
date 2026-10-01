import sys

CLI_COMMANDS = ("info", "convert", "versions", "players", "trim", "-h", "--help")


def _is_cli(argv) -> bool:
    """A command (or help) after the optional --lang choice."""
    args = list(argv)
    while args and args[0].startswith("--lang"):
        args = args[2:] if args[0] == "--lang" else args[1:]
    return bool(args) and args[0] in CLI_COMMANDS


def run():
    is_cli = _is_cli(sys.argv[1:])
    from ._bootstrap import ensure

    ensure(gui=not is_cli)
    if is_cli:
        from .cli import main

        sys.exit(main())
    from .gui.app import main as gui_main

    sys.exit(gui_main())


if __name__ == "__main__":
    run()
