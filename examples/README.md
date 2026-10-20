# ZOS-API examples

Single-file Python ZOS-API scripts distilled from the three projects in the
accompanying manuscript. Each embeds the standard `PythonStandaloneApplication`
connection class, builds a system, runs a trace/analysis, prints key results, and
saves a `.zos` you can open in Zemax OpticStudio to inspect geometry and detectors.

They are meant for someone who already has OpticStudio and wants to try
agent-built ZOS-API scripts. Parameters are hard-coded at the top of each file.

| Script | Project | Demonstrates |
|--------|---------|--------------|
| `spoiled_corner_cube.py` | Spoiled corner-cube retroreflector | NSC three-mirror trihedron with a two-axis dihedral offset → six-lobe return with a central null; polarized `OpenNSCRayTrace`; detector-grid extraction. Saves `spoiled_corner_cube.zos` (+ optional heatmap PNG). |
| `coherent_incoherent_projector.py` | Coherent/incoherent projector | Faithful rebuild of `solis_plossl_achromat_full`: SOLIS die → ACL25416U-A/ACL2520U-A → tapered N-BK7 light pipe → AC508-075-A + ACT508-250-A relay → USAF-1951 slide at the SLM plane → two Plössls (AC508-300-A ×4) 4f relay + Fourier annulus → substrate. Real vendor lenses; hard-coded 455 nm BFLs. Reports transport efficiency + uniformity CV. |
| `microled_link.py` | Wide-and-slow microLED link | Reproduces `mvp5_multicore_50um_{lambertian,reallens}` — a 115-core hex multicore fiber (absorbing EMA matrix + clad + core nests), 9 cosine-power sources activated one at a time to fill a 9×9 channel matrix, launched either bare-Lambertian or through the real two-element TIR micro-collimator. Emits **two** `.zos` files and reports coupling + crosstalk (dB). |

## Verified results (in the `zemax-pg` env)

| Script | Result | Reference target |
|--------|--------|------------------|
| corner cube | central null = 0, six lobes | — |
| projector | transport 10.47%, CV 66.5% | 10.48%, 64.2% |
| microLED lambertian | coupling 0.125, crosstalk −15.3 dB | 0.124, −15.4 dB |
| microLED reallens | coupling 0.260, crosstalk −8.3 dB | 0.261, −8.2 dB |

## Requirements

- Windows with Zemax OpticStudio (developed against v24.1) and a ZOS-API license
- Python with `pythonnet` (`clr`) and `numpy` (env: `zemax-pg`); `matplotlib` optional
- The projector needs the **Thorlabs lens catalog** (for AC508-300-A) and the
  SCHOTT/HIKARI glass catalogs installed in OpticStudio
- `optics/` (bundled) holds the vendor lens NSC seeds, the TIR-collimator
  prescription, and `USAF-1951.bmp` (auto-copied into the Zemax ImaFiles folder)

## `optics/` contents

- `ACL25416U-A_NSC.zos`, `ACL2520U-A_NSC.zos`, `AC508-075-A_NSC.zos`,
  `ACT508-250-A_NSC.zos` (+ `.ZDA`) — Thorlabs illumination lenses as NSC seeds,
  cloned into the projector build. Download the originals from thorlabs.com and
  convert via `Tools.OpenConvertToNSCGroup` to regenerate them.
- `tir_collimator_prescription.json` — the locked two-element TIR micro-collimator
  used by the microLED `reallens` build.
- `USAF-1951.bmp` — resolution-target transparency for the projector's SLM plane
  (see Attribution below).

## Attribution

`optics/USAF-1951.bmp` was converted (SVG → BMP) from
[File:USAF-1951.svg](https://en.wikipedia.org/wiki/1951_USAF_resolution_test_chart#/media/File:USAF-1951.svg)
on Wikipedia, licensed under
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). The only change
is the rasterization to a bitmap for use as a Zemax Slide object; this derivative
is likewise distributed under CC BY-SA 3.0.

## Running

```
python spoiled_corner_cube.py
python coherent_incoherent_projector.py
python microled_link.py
```

Each launches a headless OpticStudio (standalone mode); no GUI setup needed.

## Notes and simplifications

- **Standalone** connection mode is used throughout for portability; the real
  projects also use Interactive Extension. See the `zemax-zos-api` skill's
  `interactive-extension.md`.
- The projector's tapered rod is **N-BK7** (as in the reference build, required to
  reproduce the 10.5% result); set `ROD_MATERIAL = "F_SILICA"` for a fused-silica
  pipe (needs the MISC catalog; slightly different throughput).
- Vendor lens back-focal-lengths are hard-coded from 455 nm measurements
  (`BFL_455`); the real project re-measures them at build time via a scratch
  sequential system.
- Ray counts are modest for speed. The projector CV is shot-noise-sensitive —
  raise `LED_ANALYSIS_RAYS` for a smoother map.
- Property values are set through `obj.get_ObjectData().__implementation__` and
  every build is checked with `TheSystem.UpdateStatus()` — the two habits that
  avoid the most common silent ZOS-API failures.
```
