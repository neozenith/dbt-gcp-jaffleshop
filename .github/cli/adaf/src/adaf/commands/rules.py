"""``adaf rules`` — inspect and validate the rule catalogue (the SSoT).

Read-only display commands follow the house output discipline: the human view goes
to stderr via ``logging``; ``--json`` puts the machine payload (and nothing else) on
stdout. ``validate`` is the gate — it exits non-zero when the catalogue violates its
meta-schema, and is the programmatic half of the "one list, everything derived"
invariant (its CI form is a workflow step).
"""

import json
import logging
from argparse import Namespace

from adaf.rules import all_rules, get_rule, load_catalog, validate_catalog
from adaf.suppression import disable_help

log = logging.getLogger(__name__)

# Columns for the `rules list` table, in display order.
_COLS = ("code", "role", "detection", "dama", "title")


def _matches(rule: dict, args: Namespace) -> bool:
    """Apply the optional --role/--detection/--dama filters (AND semantics)."""
    if args.role and rule["role"] != args.role:
        return False
    if args.detection and rule["detection"] != args.detection:
        return False
    if args.dama and args.dama not in rule["dama"]:
        return False
    return True


def cmd_list(args: Namespace) -> int:
    selected = [r for r in all_rules() if _matches(r, args)]
    if args.as_json:
        print(json.dumps(selected, indent=2))
        return 0
    if not selected:
        log.info("no rules match the given filters")
        return 0
    rows = [{c: (", ".join(r[c]) if c == "dama" else str(r[c])) for c in _COLS} for r in selected]
    widths = {c: max(len(c), *(len(row[c]) for row in rows)) for c in _COLS}
    header = "  ".join(c.upper().ljust(widths[c]) for c in _COLS)
    log.info("%s", header)
    log.info("%s", "  ".join("-" * widths[c] for c in _COLS))
    for row in rows:
        log.info("%s", "  ".join(row[c].ljust(widths[c]) for c in _COLS))
    log.info("\n%d of %d rule(s)", len(selected), len(all_rules()))
    return 0


def cmd_show(args: Namespace) -> int:
    rule = get_rule(args.code)
    if rule is None:
        codes = ", ".join(r["code"] for r in all_rules())
        log.error("unknown rule code %r. Known codes: %s", args.code, codes)
        return 2
    if args.as_json:
        print(json.dumps(rule, indent=2))
        return 0
    log.info("%s — %s", rule["code"], rule["title"])
    log.info("  role        : %s%s", rule["role"], f" / {rule['sub_role']}" if rule.get("sub_role") else "")
    log.info("  DAMA-UK6    : %s", ", ".join(rule["dama"]))
    log.info("  Wang–Strong : %s", ", ".join(rule["wang_strong"]) or "(none)")
    log.info("  detection   : %s", rule["detection"])
    log.info("  boundary    : %s", ", ".join(rule["boundary_class"]))
    log.info("  cost class  : %s", rule["cost_class"])
    log.info("  summary     : %s", rule["summary"])
    log.info("  first reach : %s", rule["framework_first"])
    log.info("  applies when: %s", rule["applies_when"])
    log.info("  vignette    : %s", rule["doc"])
    return 0


def cmd_explain(args: Namespace) -> int:
    """Show a rule AND the exact ways to suppress it — the tooling teaching its own escape hatch."""
    rule = get_rule(args.code)
    if rule is None:
        codes = ", ".join(r["code"] for r in all_rules())
        log.error("unknown rule code %r. Known codes: %s", args.code, codes)
        return 2
    cmd_show(args)
    log.info("")
    for line in disable_help(rule["code"]):
        log.info("%s", line)
    return 0


def cmd_validate(args: Namespace) -> int:
    errors = validate_catalog()
    version = load_catalog().get("version", "?")
    count = len(all_rules())
    if errors:
        log.error("catalogue v%s INVALID — %d error(s):", version, len(errors))
        for e in errors:
            log.error("  • %s", e)
        return 1
    log.info("✅ catalogue v%s valid — %d rule(s) conform to the meta-schema", version, count)
    return 0
