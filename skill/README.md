# zemax-zos-api

Agent skill for the Zemax OpticStudio ZOS-API (Python via pythonnet). Targeted at OpticStudio v24.1. Installs at `~/skills/zemax-zos-api/`; Agent reads `SKILL.md` automatically. Everything here is agent-facing — there is no human tutorial. Read `SKILL.md` to see what's documented.

## Paper

This skill is described in the accompanying manuscript:
Z. S. Davidson, "Driving optical simulation with a coding agent: experience operating Zemax OpticStudio through the ZOS-API" (2026).

Tools under `scripts/`:
- `check_namespace.py` — verify ZOSAPI/System names in a .py or .md against the live API. `--audit` scans the whole skill.
- `chmseek_zos.py` — search the OpticStudio CHM for symbols/members.
- `probe_object_properties.py` — dump typed properties for NCE objects, LDE surface types, analyses, and tools.
