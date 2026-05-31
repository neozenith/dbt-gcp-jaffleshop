"""cicd_cli — centralised dev/CI automation for the dbt jaffle-shop project.

Runnable as a module from the dbt project root:

    uv run -m cicd_cli --help                      # from within dbt-jaffleshop/
    uv run --directory dbt-jaffleshop -m cicd_cli  # from the repo root

It is designed to be invoked three ways with identical behaviour: by a developer
in their inner loop, by an agentic coding tool (it behaves like a plain CLI), and
by GitHub Actions. Every leaf command is a read-only gate that exits non-zero on
failure and supports ``--json`` for machine consumption.
"""

__version__ = "0.1.0"
