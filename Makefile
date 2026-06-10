.PHONY: clean guides-build guides-serve

clean:
	rm -rfv tmp/
	rm -rfv .venv/

# --- Guides site (MkDocs) -----------------------------------------------------
# Renders docs/guides/testing_taxonomy/ as a Material static site. Published in CI
# as a sibling of the dbt docs under <pages-url>/guides/ (see .github/workflows/dbt-docs.yml).
guides-build:
	uv run --directory docs/site mkdocs build

guides-serve:
	uv run --directory docs/site mkdocs serve
