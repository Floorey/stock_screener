# Project agent skills

Skills in this repository are authored **here**, under `.claude/skills/<skill-name>/`, and
mirrored into the folders that other agents discover. The `SKILL.md` format — YAML
frontmatter with `name` and `description`, a markdown body, optional `references/`,
`scripts/` and `assets/` subfolders — is shared across Claude Code, Google Antigravity and
Gemini CLI, so one authored copy serves all three.

## Skills here

| Skill | What it is |
|---|---|
| `high-frequency-trading` | Reference knowledge on HFT, algorithmic trading and equity market microstructure, distilled from Gomber, Arndt, Lutat & Uhle (2011) plus a file tracking what changed since. |
| `pdf-analyzer` | How this repo's `pdf_analyzer.py` extraction pipeline works — the `pages_data` contract, the metric patterns, the documented extraction failure modes, and a characterization harness for verifying changes. |

## Where each agent looks

| Agent | Project-level path | Global path |
|---|---|---|
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Google Antigravity | `.agents/skills/` (older builds: `.agent/skills/`) | `~/.gemini/antigravity/skills/` |
| Gemini CLI | `.gemini/skills/` | `~/.gemini/skills/` |

Antigravity also reads the `.agents/` directory generally, which is where this repo's
`AGENTS.md` already lives.

## Keeping the copies in sync

Edit only the copy under `.claude/skills/`, then:

```bash
python sync_agent_skills.py           # copy into .agents/skills/ and .gemini/skills/
python sync_agent_skills.py --check   # verify the copies match; exits 1 on drift
```

The script copies rather than symlinks, since git symlinks do not survive a Windows
checkout without developer mode enabled.

## Installing a skill globally

To use one of these outside this repository, copy the skill folder into the relevant global
path from the table above. The folder is self-contained — no build step, no dependencies.
