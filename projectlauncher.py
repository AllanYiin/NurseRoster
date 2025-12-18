"""Compatibility entry point for tooling expecting projectlauncher.py at the repo root."""
from project_launcher import main


if __name__ == "__main__":
    raise SystemExit(main())
