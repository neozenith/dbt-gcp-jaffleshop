"""Shared terraform command-builder tests (tfs._terraform).

The builders are the single source both `tfs plan` and the diagram renderer use,
so a regression here is what inventory finding D1 was about — pin them.
"""

from __future__ import annotations

from tfs import _terraform as tf


def test_init_cmd():
    assert tf.init_cmd("webapp", "dev") == (
        "terraform -chdir=stacks/webapp init -backend-config=./backends/dev.config -reconfigure"
    )


def test_plan_cmd_default_locks_and_no_out():
    cmd = tf.plan_cmd("webapp", "dev", "")
    assert cmd == "terraform -chdir=stacks/webapp plan -no-color -input=false -var environment=dev"
    assert "-lock=false" not in cmd
    assert "-out=" not in cmd


def test_plan_cmd_with_var_file():
    cmd = tf.plan_cmd("webapp", "prod", "-var-file=prod.tfvars")
    assert cmd.endswith("-var environment=prod -var-file=prod.tfvars")


def test_plan_cmd_diagram_variant_unlocked_with_out():
    """The diagram renderer's ONLY divergence from `tfs plan`: -lock=false + -out=."""
    cmd = tf.plan_cmd("webapp", "dev", "", lock=False, out="tmp/diagram.tfplan")
    assert "-lock=false" in cmd
    assert "-out=tmp/diagram.tfplan" in cmd
    # still the same base plan as tfs plan otherwise
    assert "plan -no-color -input=false" in cmd
    assert "-var environment=dev" in cmd


def test_apply_cmd_auto_approves():
    cmd = tf.apply_cmd("webapp", "test", "-var-file=test.tfvars")
    assert cmd.startswith("terraform -chdir=stacks/webapp apply -no-color -input=false")
    assert cmd.endswith("-auto-approve")
    assert "-var environment=test" in cmd


def test_show_json_cmd():
    assert tf.show_json_cmd("webapp", "tmp/p.tfplan") == "terraform -chdir=stacks/webapp show -json tmp/p.tfplan"


def test_tfvars_flag(tmp_path):
    assert tf.tfvars_flag(tmp_path, "dev") == ""
    (tmp_path / "dev.tfvars").write_text("x = 1\n")
    assert tf.tfvars_flag(tmp_path, "dev") == "-var-file=dev.tfvars"
