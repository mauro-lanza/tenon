# Operations

What a run does to this machine, and what it will and won't touch. Read this
before a large re-run or when onboarding a machine that already has software
installed outside Homebrew.

For *why* things behave this way, see [architecture.md](architecture.md). For
failures with known causes and recovery steps, see [findings.md](findings.md).

## Running it

```bash
# Reconcile now
tenon apply          # args pass through to ansible-pull; --check is refused, use `check`

# What would change, without changing it (the same check the 10:00 agent runs)
tenon check

# A fully converged machine reports:  changed=0  failed=0
```

Ask what the last run actually did, without re-running anything:

```bash
tenon status
```

```
Last run:  check — ok at 2026-08-20T10:00:04+0200
Drift:     2 task(s) would change:
  - Deploy layer template: settings.json  →  /Users/you/.config/zed/settings.json
  - Deploy the managed git config  →  /Users/you/.config/git/managed.gitconfig
Sync:      ok — last successful scheduled run 0 day(s) ago
```

The `Sync:` line is the one to read first. The scheduled modes exit 0 when the
repo is unreachable — a closed laptop is not a fault — which means a machine
that quietly stopped syncing weeks ago otherwise looks exactly like a healthy
one. Past `drift_correction_stale_after_days` (14 by default) it reports
`STALE`.

`tenon status --json` prints the same thing for machines. See "Run state" in
[architecture.md](architecture.md) for the shape and its guarantees, and
"Machine-readable interface" below for the supported fields. It also
carries `"schedule": {"upgrade": "09:00", "check": "10:00"}` (local times of the
engine's own agents), `null` where there is no scheduler (Linux) or the agents
are off.

Non-interactive use (a UI, a script):

```bash
printf '%s\n' "$PW" | tenon upgrade --yes --password-stdin   # macOS: casks that need root
printf '%s\n' "$PW" | tenon apply --password-stdin           # Linux: pacman, AUR, chsh
tenon upgrade --yes </dev/null                               # no password: casks needing root fail
```

`--password-stdin` reads one line as the sudo password, checks it **once**
(`sudo -S -k`, never retried: PAM lockout) and exits **65** with nothing run if
it is wrong. An empty line skips root steps, like pressing Enter. The flag is
rejected (64) where the platform asks for no password. `--yes` skips the
`Proceed?` confirmation and the terminal requirement; `upgrade` still refuses
without a terminal when it is absent. Neither flag makes a run partial.
Exit codes: see "Exit codes" below.

The capability registry and the selection in `machine.yml`:

```bash
tenon capabilities --json        # {"schema_version": 1, "capabilities": [{id, desc, layer, selected, active, offerable, platforms, requires?, packages?}]}
tenon capabilities select ID...  # edits selected_capabilities only; run `tenon apply` after
tenon capabilities deselect ID...
```

`layer` is the highest-priority layer declaring the id; `active` is selected or
adopted (`adopt_if_present` path exists); `platforms` is where it applies (see
"Capability platforms" in `architecture.md`) and `offerable` is whether this
machine's platform is one of them (`--platform Darwin|Linux` overrides it, for
tests). Unknown ids, and ids not offerable here, exit 64 on `select` and change
nothing. Deselecting never uninstalls: software and files stay, and show as
orphans in `tenon orphans`.

Ask what this system owns:

```bash
tenon manifest
```

```
Recorded:  2026-09-03T21:40:11+0200

Files (27):
  /Users/you/.zshrc                                   core
  /Users/you/.zsh/010-public-00-path.zsh              shell
  /Users/you/.config/git/ignore                       git
  …

Directories (11):
  /Users/you/.zsh
  …
```

Every path here was recorded by the run itself, not from a hand-kept list. If
the header says `INCOMPLETE`, the last run was narrowed by `--tags` or failed
part-way and saw only a fraction of the machine — read it as a sample, not an
inventory. A `Backup copies left behind` section lists `backup: true` residue,
which nothing removes automatically.

Ask what this machine has been doing:

```bash
tenon history 10
```

```
FINISHED                   MODE     RESULT    CHANGED   FAILED  DURATION
2026-09-03T09:00:31+0200   upgrade* ok              0        0     41.2s
2026-09-03T10:00:12+0200   check    ok              0        0     47.5s

* = partial run (narrowed by tags or arguments)
```

Each entry records the path to that run's own log, so `history` answers *when*
something happened and `tenon log` answers *what*. History keeps
roughly the last 500 runs; logs are pruned on a separate schedule.

Clone repositories that are listed but missing:

```bash
tenon apply --tags repositories
```

## The engine's runtime is pinned

The engine does not run whatever `ansible` Homebrew has. It runs a Python and an
ansible-core pinned in `runtime.yml`, installed by `uv` into
`~/.local/share/tenon/runtime/`, plus mitogen. There is deliberately no
`ansible` on your `PATH`.

```bash
# Reconcile the runtime with runtime.yml (after bumping a version there)
tenon apply --tags runtime

# What the engine is actually running
~/.local/share/tenon/runtime/bin/ansible --version
```

`check` reports a runtime that has drifted from the pin as changed, naming both
versions — the probes carry `check_mode: false` precisely so it can.

**Upgrading the fleet** is a one-line change to `runtime.yml`. Machines converge
on it through the normal sync; there is no ordering of steps to arrange.

### When a run misbehaves, take mitogen out of the picture first

```bash
TENON_NO_MITOGEN=1 tenon apply
TENON_NO_MITOGEN=1 ./scripts/check.sh
```

Mitogen replaces Ansible's execution model, so it is the first thing to rule out
when something behaves oddly — and this is how a machine still repairs itself if
mitogen is ever the thing that is broken. It runs ~2x slower without it.

### Developing against the repo

Use a project venv, like any Python project. The pinned runtime is the engine's
private interpreter and is not meant to be a general-purpose `ansible`.
`scripts/check.sh` puts it on `PATH` for itself and refuses to run without it,
so the gate always tests what production runs.

## git config is included, not imposed

`~/.gitconfig` is **not** owned by this setup. It owns
`~/.config/git/tenon.gitconfig` and reaches `~/.gitconfig` only to
append one `include.path`. Anything you put in `~/.gitconfig` — signing keys,
credential helpers, your own `includeIf` blocks — is preserved.

The include is appended, so managed values are read **last** and still win over
entries above them. Full enforcement, no collateral damage.

### Per-directory identities

`git_conditional_identities` renders `includeIf` blocks — how a work layer
supplies a work address for its own remotes without touching the machine-wide
identity. The machine-wide `git_user_name`/`git_user_email` come from questions
instead (see "The machine tier" in [architecture.md](architecture.md)).

Two condition forms, both passed to git verbatim:

- `gitdir:<path>` — matches by location. **Git resolves symlinks first**, so the
  pattern must be the real path: on macOS `/private/tmp/...`, never `/tmp/...`.
  A pattern that looks right but points through a symlink silently never matches.
- `hasconfig:remote.*.url:<pattern>` — matches by remote URL (git ≥ 2.36), and
  is layout-independent. Use this when work and personal repositories share one
  directory, which is the normal case here.

Verify with `git -C <repo> config --get user.email` inside an affected
repository — the condition is evaluated per repo, so checking the config file
alone tells you nothing.

## How your manual changes are handled

### Enforced — reverted on the next run

| What you change | Behaviour |
|---|---|
| `~/.zshrc` | Replaced from the layer-provided `zshrc` (timestamped backup kept). Edit it in the layer. |
| `~/.zsh/*.zsh` managed snippets | Regenerated from the layers' `files/shell/*.zsh`. |
| `~/.config/git/tenon.gitconfig` | Re-rendered whole. Anything not declared in a layer is dropped. `~/.gitconfig` itself is only appended to. |
| `~/.config/git/ignore` | Replaced entirely from `git_global_gitignore_entries`. `core.excludesFile` is pointed at it explicitly. |
| `~/.zsh/configs/p10k.zsh` | Replaced from the layer-provided `p10k.zsh`. Sourced by name via `POWERLEVEL9K_CONFIG_FILE`, not by the snippet glob, and never garbage-collected. |
| macOS defaults | `osx_defaults` enforces the layer-declared value; System Settings changes are reverted. |
| NVM default alias | Mismatch is detected and `nvm alias default <declared>` re-run. |
| tfenv active version | Reverted to `runtimes_tfenv_terraform_version` (and never auto-upgraded). |
| Capability config files | Re-deployed from the providing layer whenever the capability is active. |
| `tenon`, the engine's own LaunchAgent plists | Regenerated, then the agents are reloaded. |
| Layer-declared scheduled agents | Plists regenerated and reloaded. An agent whose `requires_capability` is no longer active, or whose entry is removed, is booted out of launchd and its plist deleted — a stale plist would otherwise keep firing across reboots. |

### Additive — nothing of yours is removed

| What you change | Behaviour |
|---|---|
| Install extra Homebrew packages or editor extensions | Preserved. Only listed items are ensured present. |
| Uninstall a *managed* package or extension | Reinstalled on the next run. |

### Preserved — left untouched

| What you change | Behaviour |
|---|---|
| Extra files in `~/.zsh/` | Left on disk. Cleanup only removes paths recorded in `~/.zsh/.tenon-snippets` from a previous run. |
| `~/.config/tenon/machine.yml` edited by hand | Read as-is. Malformed YAML falls back to defaults with a warning. |
| Local changes in a listed repo | Never touched. Cloning uses `update: false` and only clones repos that are entirely absent. |

## Non-destructive guarantees

The `packages` role is `state: present` only — no prune, no `absent`. Applying
never uninstalls manually-installed apps or unmanaged Homebrew leaves. Removing
an item from a baseline list stops *enforcing* it; nothing is uninstalled.
Cleanup is always a deliberate manual step, never a side effect of a run.

### Asymmetry: config deploys are not garbage-collected

Shell snippets **are** cleaned up — the `shell` role records what it deployed and
removes anything that falls out of that set, so disabling a capability withdraws
its snippet.

Capability `config:` bundles are **not**. Deselecting a capability, or changing a
bundle's `dest`, leaves the previously deployed file in place.

This is deliberate. `~/.zsh/` is wholly engine-owned, so removing an
unrecognised file there is safe. Config bundles write to arbitrary paths the user
also owns and edits. A "remove what we no longer manage" pass over those paths
would turn a renamed `dest`, a mistyped capability id, or a layer that briefly
failed to load into silent deletion of real user config. An orphan is the cheaper
failure. After renaming a bundle's `dest`, delete the old file yourself.

Scheduled agents are the deliberate exception: `scheduled_agents` **does** remove
plists it no longer wants. The reasoning above does not hold for them — an
orphaned plist is not an inert stale file, it is a job that keeps running on
schedule across reboots. Leaving one behind means the machine keeps doing work it
was told to stop doing, which is worse than the deletion risk.

### An outside `brew uninstall` can take managed formulae with it

Homebrew autoremoves what it considers unneeded dependencies. Formulae installed
through the `community.general.homebrew` module are not always marked
install-on-request, so an unrelated `brew uninstall` can remove one of them.

Observed: `brew uninstall ansible` also removed `tree`, a baseline formula.

This is repaired rather than prevented. The next `check` reported it —

```
Drift: 1 task(s) would change:
  - Install formulae (and refresh Homebrew first)
```

— and one `apply` put it back. Worth knowing because the window is up to a day,
and because the reverse case is invisible: a formula this system *stops*
declaring is never removed, and nothing reports that either.

## Where runs log

Every run writes its own file, named for when it started and what it was:

    ~/Library/Logs/tenon/20260915-171312-check.log

```bash
tenon log          # the most recent run, last 100 lines
tenon log 500      # more of it
tenon log --list   # every run kept, newest first
```

Interactive runs are logged too. They still print to your terminal exactly as
before, and are kept as well — a run launched from the menu bar has no terminal
at all, so without this its output would be lost.

Successful runs are pruned after `drift_correction_log_retention_days` (30).
**Failed runs are never pruned** — the run that went wrong is the one you come
back to weeks later. Pruning only happens after a run that itself succeeded: a
machine that is failing should not be tidying away the evidence.

`tenon history` lists recent runs, and each entry records the path to
its own log.

### Layer-declared agents log separately

None of the above covers agents a layer declares. Those write one pair of files
per agent, named for the agent's label:

    ~/Library/Logs/<label>.stdout.log
    ~/Library/Logs/<label>.stderr.log

These are not rotated. A job that is noisy on every run will grow them without
bound, so prefer one that stays quiet when it has nothing to report.

Check `stderr.log` first when an agent appears to do nothing. A LaunchAgent
inherits no login-shell environment, so the usual cause is a `PATH` problem — the
plist sets a fixed `PATH` covering Homebrew and the system, and a tool installed
anywhere else will not be found. `launchctl list | grep <label>` shows whether
the job is loaded and what it last exited with.

## Watching a run happen

```bash
tenon progress
```

```
check  [########............] 43%  88/202
  now: homebrew : Install casks without adoption
```

The point is runs you did **not** start — the 09:00 upgrade and the 10:00 check
are otherwise invisible while they happen, and "is it stuck or is it working"
had no answer short of reading the log afterwards.

It reports `starting` during the layer sync and `ansible-pull` fetch, before the
first task exists, and says so plainly if a run was interrupted rather than
animating a bar for a process that died.

## Machine-readable interface

Supported for other programs (versioned; a breaking change bumps `schema_version`).
Everything else in the state directory is internal.

`tenon status --json`:

| Field | Meaning |
|---|---|
| `schema_version` | `1` |
| `current_run` | `null` when idle, else the object below |
| `last_success`, `days_since_success`, `stale` | last successful scheduled run (`null`, `null`, `false` if none) |
| `days_since_upgrade_success` | days since the last scheduled upgrade, `null` if none |
| `orphans` | count of stored orphans (files, packages, installed packages of unselected capabilities as of the last complete run), `0` if none; never runs `brew list`, so a package removed by hand counts until the next run |
| `schedule` | `{"upgrade": "HH:MM", "check": "HH:MM"}`, or `null` |
| `last_run` | the `last-run.json` contents, `null` if none |

`current_run` is non-null only while `run.lock` is held by a live process:

```json
{"run_id": "12345-1795690037", "mode": "check", "pid": 12345,
 "started": "2026-11-26T11:47:17+0100", "log": "/Users/you/Library/Logs/tenon/20261126-114717-check.log",
 "phase": "running", "task": "homebrew : Install casks", "n": 88, "total": 202, "indeterminate": false}
```

`phase` is `launching` (before ansible starts: git, layer sync; `task` null,
`n` 0), `running`, or `stalled` (process alive, no progress for 300 seconds).
`total` is the largest task count among the last 5 completed non-partial runs of
the same mode, `null` without history; `indeterminate` is true when `total` is
null or `n` has passed it. In the instant between taking the lock and writing
`launching`, `run_id`, `mode`, `started` and `log` are `null`.

`tenon capabilities --json` carries `"schema_version": 1` beside `capabilities`.

`tenon orphans --json` lists what was once managed and is still present:

```json
{"schema_version": 1, "orphans": [
  {"id": "3f2a9c1b7d04", "kind": "file", "manager": null, "path": "/Users/you/.config/old/settings.json",
   "name": null, "layer": "tenon-layer-public", "capability": null, "since": "2026-11-20T09:00:12+0100",
   "safe": true, "reason": "unchanged since tenon wrote it"},
  {"id": "a81c05e2d9f6", "kind": "package", "manager": "cask", "path": null,
   "name": "appa", "layer": "tenon-layer-personal", "capability": "cap-a", "since": "2026-11-21T09:00:03+0100",
   "safe": false, "reason": "may have been installed before tenon"}]}
```

`id` is stable (a hash of kind, manager and path or name). `safe` is true only for
a file whose bytes still equal the checksum recorded when tenon wrote it; files
with no recorded checksum and all packages are never safe. `layer` and
`capability` are `null` where tenon cannot tell (baseline packages have no layer;
file orphans carry no capability). `tenon orphans` without `--json` prints the
same list. Packages are listed only while `brew list` still reports them installed.
Besides packages that dropped out of the desired set, a package declared only by a
capability that is neither selected nor adopted is listed (reason `declared by
unselected capability <id>; may have been installed outside tenon`), whenever it is
installed; `forget` keeps such an id hidden.

`tenon orphans remove [--force] [--json] [--password-stdin] ID...` and
`tenon orphans forget [--json] ID...` print `{"results": [{"id", "ok", "message"}]}`
under `--json`, one entry per id. Both write `<log dir>/YYYYmmdd-HHMMSS-orphans.log` (the command, each item, brew's full output, the results); a failed item's `message` carries the last 10 lines of brew output. They take `run.lock` (busy: 75). An unknown id
exits 64 and nothing is done. `remove` re-verifies each orphan first:

- a file is moved to `~/.local/share/tenon/backups/trash/<YYYYmmdd-HHMMSS>/<its path>`
  (restore it by moving it back); a file that is not `safe` is skipped unless
  `--force`; directories are never removed;
- a package runs `brew uninstall --formula NAME` or `brew uninstall --cask NAME`,
  never `--force`, `--zap` or autoremove; a refusal (for example a dependent) is
  reported on that item. `--password-stdin` (macOS) gives casks that need root the
  password, as for `upgrade`: 65 if it is wrong, nothing runs.

`forget` drops the entries and touches nothing. Removed and forgotten orphans leave
the list. Exit 1 if any item was skipped or failed.

Files in `~/.local/state/tenon/` (see [architecture.md](architecture.md)):

- `progress.jsonl`: the live run, truncated by every run. Every line has
  `schema_version` (1) and an `event`: `launching` and `start` (`mode`,
  `run_id`, `started`, `log`; `start` also `partial`, `total_estimate`), `task`
  (`n`, `task`, `role`, `handler`), `end` (`result`, `tasks`, `changed`,
  `failed`, `finished`). A file with no `end` and no live lock is an interrupted
  run. Use `status --json` to know whether a run is live.
- `history.jsonl`: one line per run, oldest trimmed past 500. Fields: `schema_version`
  (1), `finished`, `mode`, `partial`, `result` (`ok`|`failed`), `duration_seconds`,
  `changed`, `failed`, `ok`, `tasks`, `log`, `run_id`.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | success; also a scheduled run skipped because another run holds the lock or the repo is unreachable |
| 1 | failure (a failed run returns ansible-pull's code; an unreachable repo, a missing terminal, a missing path; `orphans remove` skipped or failed an item) |
| 64 | usage error: bad arguments, unknown capability or orphan id, `apply --check`, a flag the platform does not use |
| 65 | `--password-stdin` got a wrong sudo password; nothing ran |
| 75 | `apply`, `check`, `upgrade` or `orphans remove|forget` refused because another run holds `run.lock` (stderr names its pid) |

### Log directory

`~/Library/Logs/tenon/` on macOS, `~/.local/state/tenon/logs/` on Linux; files
are `<YYYYmmdd-HHMMSS>-<mode>.log`. `current_run.log` and each history line give
the exact path.

## Credentials

`tenon status` reports a missing sign-in like any other drift:

```
Drift:     1 task(s) would change:
  - Check for each declared credential  →  opencode-corp
```

Run `tenon apply` **from a terminal** to be prompted through it. The
09:00 and 10:00 agents will never attempt it — the flows are interactive and a
LaunchAgent has no terminal to answer them — so an unattended run reports it and
moves on. It goes quiet by itself once you have signed in.

## Adopting manually-installed apps

The `packages` role only uses `install_options: adopt` for casks explicitly
listed in `packages_cask_adopt`. Adoption is **not** safe for every cask — see
"Casks with protected payloads" in [findings.md](findings.md) before adding one.

## Migrating a tool off a manual installer

Tools installed via vendor scripts leave a footprint (a `~/.tool` dir plus PATH
and completion lines in `.zshrc`). To bring one under management:

1. Add it as a capability in a layer's `capabilities.yml`, then add that
   capability's `id` to `selected_capabilities` in
   `~/.config/tenon/machine.yml`. Selection is by capability id, not by
   package name.
2. Apply, so Homebrew installs the managed copy.
3. Remove the manual install dir and its `.zshrc` lines.

## PATH priority: managed vs. manual tools

Layers own PATH (typically a `files/shell/*.zsh` snippet), not the orchestrator.
If a layer puts `~/.local/bin` ahead of `/opt/homebrew/bin`, a manually-installed
binary there will **shadow** the Homebrew-managed one. After bringing such a tool
under management, remove the manual copy so the brew version wins.

## Backing up and restoring a machine

`machine.yml` is this machine's entire declaration — its layers, every answer,
every capability selection. One file because it is one decision: the capability
ids mean nothing without the layers that define them. `bootstrap.sh --answers <file>` replays one
non-interactively, and `check.sh` asserts a written `machine.yml` is a valid
answers file, so **a backup is a restorable machine**.

```bash
tenon machine init   # choose the private repo and name this machine
tenon machine push   # back up the current machine.yml
tenon machine list   # machines backed up in the repo
tenon machine pull work-macbook
```

One file per machine under `machines/<name>.yml`, so a laptop and a desktop keep
separate declarations instead of fighting over one. The machine name is prompted
at `init` — the hostname is a serial number on a corporate Mac, which is exactly
why it is not silently used as the default.

`pull` writes a **file**; it never touches the live `machine.yml`. Review it, then:

```bash
bootstrap.sh --answers ./work-macbook-machine.yml
```

so a restore from the wrong machine is a deleted file rather than a reconfigured
laptop.

The repo is **private** and holds git identity and a per-machine software
inventory. Do not make it public, and do not use a secret gist for it — a secret
gist is unlisted, not access-controlled, and anyone with the URL can read it.

It is also **not a content layer**. Layers are force-synced (fetch + hard reset)
by `tenon-layers`, which would destroy commits here waiting to push. It
is cloned separately to `~/.local/share/tenon/backups`.

### Restoring onto a fresh Mac

`bootstrap.sh` offers this before it asks about layers. If the machine has no
declaration yet and a backup repo is configured, it lists the backed-up machines
and lets you pick one:

```
This machine has no declaration yet, and backups exist:
    1) work-macbook
    2) home-desktop
    0) start fresh
```

The chosen declaration is fetched and fed through the ordinary `--answers` path,
so it is validated against the layers' merged registry like any other answers
file — a capability id that no longer exists is reported rather than silently
applied.

The prompt is skipped when it would be wrong: a non-interactive run, an explicit
`--answers`, an already-declared machine, or no backup repo configured. It is
also never fatal — an unreachable backup repo warns and setup continues.

## Removing tenon

There is no uninstall command, and nothing it installed is removed for you
(see "Non-destructive guarantees"). To stop and remove the engine itself:

```bash
for l in check upgrade; do
  launchctl bootout "gui/$(id -u)/com.tenon.$l" 2>/dev/null
  rm -f ~/Library/LaunchAgents/com.tenon.$l.plist
done
rm -rf ~/.local/share/tenon ~/.local/state/tenon \
       ~/Library/Logs/tenon ~/.ansible/pull/tenon
rm -f ~/.local/bin/tenon*
# Keep ~/.config/tenon/machine.yml if you may come back: it is the
# declaration. Layer-declared agents (e.g. com.tenon.*) are in the manifest.
```

Managed files (`~/.zshrc`, `~/.zsh/`, `~/.config/git/`) stay on disk; list them with
`tenon manifest` before deleting the state directory.

## Migrating from computer-setup

One-time steps for a machine set up before the rename to tenon. Delete this section once every machine has moved.

```bash
# macOS: stop the old agents (also any layer-declared ones listed in the manifest)
for p in ~/Library/LaunchAgents/com.computer-setup.*.plist; do
  launchctl bootout "gui/$(id -u)/$(basename "$p" .plist)" 2>/dev/null
  rm -f "$p"
done
rm -f ~/Library/LaunchAgents/.computer-setup-agents

rm -f ~/.local/bin/computer-setup*
rm -rf ~/.ansible/pull/computer-setup
mv ~/.config/computer-setup ~/.config/tenon
mv ~/.local/share/computer-setup ~/.local/share/tenon
mv ~/.local/state/computer-setup ~/.local/state/tenon
mv ~/Library/Logs/computer-setup ~/Library/Logs/tenon   # macOS only
for d in ~/.local/share/tenon/layers/computer-setup-layer-*; do
  mv "$d" "${d/computer-setup-layer-/tenon-layer-}"
done
```

Then edit `~/.config/tenon/machine.yml`: rename each layer `computer-setup-layer-*` to `tenon-layer-*` and update its URL. Run bootstrap from the new URL (or `tenon apply --tags runtime` if the CLI is already installed), then `tenon apply`, and delete the orphans it reports.

## Running your own fork

`BOOTSTRAP_OWNER=<github-user-or-org> bash bootstrap.sh` clones the engine from
`<owner>/tenon` instead, and the choice is passed to the play so the
scheduled agents follow the same repo. `BOOTSTRAP_BRANCH=<branch|tag|sha>` pins
the engine to a ref the same way.
