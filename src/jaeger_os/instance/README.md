# instance/ — where the agent's per-instance state lives

This dir holds the **skeleton** the wheel ships — empty
`default/{memory,logs,skills,credentials}/` placeholders. When the
setup wizard runs for the first time it fills in `identity.yaml`,
`config.yaml`, `manifest.json`, and `soul.md`.

After first run (on a dev checkout, when `JAEGER_INSTANCE_DIR` is
unset) you'll see:

```
instance/
└── default/                  ← created by the wizard
    ├── identity.yaml         ← agent name + role + personality (wizard-owned)
    ├── config.yaml           ← model path + display prefs (wizard-owned)
    ├── manifest.json         ← core_version pin
    ├── soul.md               ← free-form character/voice doc (wizard-owned)
    ├── permissions.json      ← "always allow" grants (runtime-written)
    ├── .lock                 ← exclusive lockfile (active while running)
    ├── run/                  ← daemon scratch — PID, socket, log
    ├── credentials/          ← 0600 API keys / tokens (off-limits to agent)
    ├── skills/               ← the AGENT's writable scratchpad
    │   └── <name>_v<N>/      ← skills the agent authors at runtime
    ├── memory/               ← facts.json, episodic.jsonl, schedules.jsonl
    └── logs/                 ← audit.log, latency.jsonl
```

Everything except the four `.gitkeep`s is gitignored — see
`.gitignore` in this directory.

## Why is the skeleton here?

Visibility. Even though the bundled `default/` no longer accumulates
runtime state (HYGIENE-1..5 in `docs/ROADMAP_0.2.0.md`), keeping the
directory shape in the source tree makes the layout obvious when
scanning the codebase and gives the wizard a stable target.

## Resolver order

Pick the on-disk path for an instance with `resolve_instance_dir()`
(in `core/instance/instance.py`). The priority is:

1. `JAEGER_INSTANCE_DIR=...` env var (always wins; use for tests,
   for multi-instance, and for dev work that targets
   `sandbox/jros-dev/` — see `scripts/dev_env.sh`).
2. `/var/lib/jaeger/<name>/` when running as root (system service mode).
3. `~/.jaeger/<name>/` when running from a pip install (i.e.
   `site-packages` / `dist-packages` is an ancestor of the package
   dir). The bundled `instance/default/` is a read-only skeleton in
   that case; never written to.
4. `jaeger_os/instance/<name>/` ← here. Used only for dev checkouts
   (including `pip install -e .` editable installs).

## Dev workflow

For in-repo work, point `JAEGER_INSTANCE_DIR` at the gitignored
sandbox so writes don't land in this tree:

```sh
source scripts/dev_env.sh     # exports JAEGER_INSTANCE_DIR=$REPO/sandbox/jros-dev
jaeger start
```

Or as a one-shot:

```sh
scripts/dev_env.sh jaeger bench run
```

## What's the contract with the agent?

The agent can ONLY write to **`<instance>/skills/`**. Everything else
under your instance directory is read-only to the agent (the v2 contract,
enforced by the sandboxed `file_write` tool).

The agent CANNOT touch anything outside its own instance directory —
not `jaeger_os/core/`, not `jaeger_os/skills/` (the core skills
shipped with the framework), not even other instances under
`jaeger_os/instance/`.

## What's the difference between `jaeger_os/skills/` and `jaeger_os/instance/<name>/skills/`?

- **`jaeger_os/skills/`** = **core skills** shipped with the framework.
  Read-only at runtime. Bundled with the install (`hello_v1/`, etc.).
- **`jaeger_os/instance/<name>/skills/`** = the agent's **writable
  scratchpad**. New skills the agent authors land here. On name collision,
  instance skills WIN over core skills (override-via-versioning).

## Cleaning up

Delete `instance/<name>/` to reset that instance. The wizard will recreate
it on next launch.
