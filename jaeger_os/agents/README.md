# agents/ — per-agent workspaces

This directory is where each agent on this machine lives. Like
`/Users/<name>/` on macOS or `C:\Users\<name>\` on Windows — but for
agent personalities rather than human users.

```
agents/
├── lilith/          ← one agent: her persona, skills, prompts, files
├── eren/            ← another agent: his stuff
└── tars/            ← etc.
```

Each agent folder is **fully self-contained**: persona, custom skills,
prompt overlays, collab workspace files. Sharing an agent with someone
else is as simple as zipping up their folder.

## What goes inside an agent folder

```
agents/<name>/
├── persona.json       — who this agent is
├── skills/            — agent-specific custom skills
├── prompts/           — persona prompt overlays
└── files/             — agent ↔ human collab area (drafts, outputs)
```

This dir is **gitignored upstream** — when you `git pull` JROS, your
agents are never touched. JROS upgrades don't risk your customisation.

See `dev docs/architecture/system_runtime_user.md` for the full
three-layer model (System / Runtime / User).
