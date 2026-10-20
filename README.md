[![DOI](https://zenodo.org/badge/1427064734.svg)](https://doi.org/10.5281/zenodo.23502844)

# OpticStudio Agent Skills

Agent-facing guidance, helper scripts, and examples for controlling Zemax OpticStudio from Python through the ZOS-API. The skill was developed against OpticStudio 24.1.

This repository accompanies the NRL Memorandum Report *Driving Optical Simulation with a Coding Agent: Experience Operating Zemax OpticStudio Through the ZOS-API* (NRL/6920/MR--2026/3).

## Contents

- [`skill/`](skill/) — the `zemax-zos-api` agent skill and supporting references.
- [`examples/`](examples/) — Python case studies and released supporting assets.
- [`zos-agent.pdf`](zos-agent.pdf) — the accompanying memorandum report.

## Installation

Install the contents of [`skill/`](skill/) as a skill named `zemax-zos-api`, preserving its `references/` and `scripts/` directories. The exact skills directory depends on the coding agent.

Running the examples requires Windows, Zemax OpticStudio with a ZOS-API license, and Python with `pythonnet` and `numpy`. See [`examples/README.md`](examples/README.md) for details.

## Citation

Citation metadata is provided in [`CITATION.cff`](CITATION.cff).

## License

The software is available under the terms in [`license.txt`](license.txt). The USAF-1951 bitmap has separate attribution and licensing described in [`examples/README.md`](examples/README.md).

Distribution Statement A. Approved for public release: distribution is unlimited.
