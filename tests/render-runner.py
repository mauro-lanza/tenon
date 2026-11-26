#!/usr/bin/env python3
"""Render the runner template the way Ansible does, against one platform profile.

    render-runner.py PLATFORM SCRATCH_DIR OUT [LAYER_CACHE]

Used by tests/runner.sh (the host's platform) and check.sh (every platform), so
each platform's real output is what gets tested, not a de-templated skeleton.
Run with Ansible's interpreter, which has jinja2 and PyYAML.
"""
import os
import shlex
import sys

import jinja2
import yaml

platform, t, out = sys.argv[1], sys.argv[2], sys.argv[3]
layer_cache = sys.argv[4] if len(sys.argv) > 4 else ""
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(root, "roles/core/vars/platform", platform + ".yml")) as f:
    profile = yaml.safe_load(f)["tenon_platform"]

# Ansible renders templates with trim_blocks, and provides `quote`.
env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True, trim_blocks=True)
env.filters["expanduser"] = os.path.expanduser
env.filters["quote"] = shlex.quote
env.filters["bool"] = bool
v = dict(
    tenon_repo_url="git@example.invalid:o/r.git", tenon_repo_branch="main",
    tenon_machine_file=t + "/none.yml", tenon_layer_cache=layer_cache,
    tenon_log_dir=t + "/logs", tenon_state_dir=t + "/state",
    tenon_config_dir=t + "/config", tenon_backup_repo_dir=t + "/backups",
    tenon_runtime_bin=t + "/bin", tenon_runtime_tools=t + "/tools",
    tenon_python_version="3.14", tenon_pull_dir=t + "/pull",
    tenon_bin_dir=t + "/bin", tenon_schema_version=2,
    drift_correction_log_retention_days=30, drift_correction_stale_after_days=14,
    drift_correction_connectivity_timeout=1, tenon_repositories_override_file=t + "/repositories.yml",
    drift_correction_enabled=True, drift_correction_schedule_hour=10, drift_correction_schedule_minute=0,
    drift_correction_upgrade_schedule_hour=9, drift_correction_upgrade_schedule_minute=5,
    repositories_base_dir=t + "/repos",
    tenon_platform=profile,
)
with open(os.path.join(root, "roles/drift_correction/templates/tenon.j2")) as f:
    rendered = env.from_string(f.read()).render(**v)
with open(out, "w") as f:
    f.write(rendered)
os.chmod(out, 0o755)
