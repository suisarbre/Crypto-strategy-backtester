
# main.py
# Unified Entry Point for Lorentzian Bot
# Routes all commands to the CLI interface

from interface import cli

if __name__ in {"__main__", "__mp_main__"}:
    cli.main()