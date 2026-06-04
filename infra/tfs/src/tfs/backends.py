"""Parsing + discovery of the per-stack GCS backend config files
(stacks/<stack>/backends/<env>.config)."""

from pathlib import Path


def find_backend_config(infra_root: Path) -> list[Path]:
    return sorted((infra_root / "stacks").glob("**/backends/*.config"))


def parse_backend_config(path: Path) -> dict[str, str]:
    """Parse a terraform `key = "value"` backend config into a dict."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"')
    return out
