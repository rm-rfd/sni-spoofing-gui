import argparse
from src.core.runtime import runtime_state
from src.core.runtime.relay_server import run_headless


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SNI-Spoofing relay and control panel.")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run the relay without launching the control panel.",
    )
    parser.add_argument(
        "--config",
        help="Optional path to an alternate config.json file.",
    )
    return parser.parse_args()


def cli_main() -> int:
    args = parse_args()
    runtime_state.set_config_path_override(args.config)
    if args.headless:
        return run_headless(args.config)

    from src.gui.window import launch_gui

    launch_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
