"""Typed exceptions for tfs. main() catches these (and anything else) at the top
level, logs `❌ <message>`, and exits non-zero — so handlers can raise freely."""


class TerraformBackendConfigError(Exception):
    """A backends/*.config file violates the state-layout convention."""


class TFStackCLIInputError(Exception):
    """The caller passed an unusable argument (bad stack, missing value, …)."""


class TFStackGCPConfigurationError(Exception):
    """gcloud is missing, or the active credentials can't see the target project."""


class InfraRootNotFoundError(Exception):
    """Could not locate the infra root (a dir with config.yml + stacks/)."""
