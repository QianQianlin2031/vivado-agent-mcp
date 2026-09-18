"""`python -m vivado_agent_mcp` entry point."""

from .server import run


def main() -> None:
    run()


if __name__ == "__main__":
    main()
