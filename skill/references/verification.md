# Verification: Did the Design Actually Do What I Wanted?

After every meaningful design change, an agent should produce verifiable evidence that the system is doing what was intended. Without this, silent failures (zero detector power, broken optimization, unexpected geometry) survive for many iterations and only surface when the human notices.

This file describes the general four-step verification pattern. Specific design types — sequential lens, NSC interference, illumination uniformity, polarization-sensitive coherent work — just plug different metric and plot blocks into the same skeleton.

## The four-step pattern

For any non-trivial design change:

1. **Validate** — `TheSystem.UpdateStatus()` returns `""`. No silent invalid-system surprise.
2. **Capture layout** — save a layout image to disk for human (or visual-LLM) inspection.
3. **Extract numeric metrics** — design-appropriate numbers, computed from analysis results.
4. **Save artifacts** — layout image + plots + `.zos` + a short text report, with a stable filename so a human can compare runs.

Skipping any of these is the most common reason an "automated optimization run" silently produces a useless design.

---

## Step 1: validate

```python
status = TheSystem.UpdateStatus()
if status:
    raise RuntimeError(f"System invalid before checking results: {status}")
```

See `patterns.md` § "System-validity check" for the full list of mutations to wrap.

---

## Step 2: capture a layout image

**Image export requires Interactive Extension mode.** Both `analysis.ToFile()` and the dedicated `Tools.Layouts.Open*Export` tools depend on the GUI's render context — in Standalone mode they silently no-op or write empty files. **The whole "produce a PNG/JPG of a layout" workflow needs the user to have OpticStudio running with `Programming → Interactive Extension` enabled, and the script to connect via `ConnectAsExtension`.** The pattern, the `PythonInteractiveApplication` connection class, and the agent ↔ user handoff prompt are in **`interactive-extension.md`** — read that first if you need any rendered artifact.

**Once you're connected via IE**, the working programmatic path is `TheSystem.Tools.Layouts.OpenNSC3DLayoutExport()` (and its sequential / shaded-model siblings). These are `ISystemTool`s with explicit camera, pixel-size, and ray-rendering controls. Full recipe + property table + `ImagesDir` write-restriction workaround are in **`analyses.md` § "NSC 3D Layout image export (programmatic, with view control)"** — copy the `save_3d_layout(...)` helper from there.

Quick orientation:

| Goal | Tool (all on `TheSystem.Tools.Layouts`) |
|---|---|
| NSC 3D layout (rays + objects, side / iso / top view) | `OpenNSC3DLayoutExport()` → `INSC3DLayoutExport` |
| NSC shaded-model (filled surfaces, wire-frame off) | `OpenNSCShadedModelExport()` → `INSCShadedModelExport` |
| Sequential 3D viewer | `Open3DViewerExport()` → `I3DViewerExport` |
| Sequential shaded model | `OpenShadedModelExport()` → `IShadedModelExport` |
| Sequential cross-section | `OpenCrossSectionExport()` → `ICrossSectionExport` |

All five share the pattern `Open → set SaveImageAsFile=True / OutputFileName / OutputPixelWidth / OutputPixelHeight / camera → check IsValidFileName → RunAndWaitForCompletion → Close`. **`OutputFileName` must be inside `TheApplication.ImagesDir`** or the tool silently no-ops with `IsValidFileName=False` — render to ImagesDir, then `shutil.copy2` to your real artifact folder.

For pixel-exact custom rendering (camera angles the export tool doesn't expose, overlays of computed quantities on the geometry, etc.) **`Tools.OpenShadedModelVisualizationExport`** returns the scene as a triangle list (`IShadedModelTriangleList`: `NumberOfTriangles`, `GetVertex(idx, Vertex.First|Second|Third, ...)` → positions, normals, surface and object IDs). Render with matplotlib's 3D, plotly, or pyvista.

For CAD handoff (rather than a flat image), `Tools.OpenExportCAD` writes STEP / IGES / STL / OBJ / ... — see `optimization.md` § "Other system tools."

---

## Step 3: extract numeric metrics

The metrics depend on the design type. The table below lists what's worth checking for the most common families and which analyses produce them. All extraction details are in `analyses.md` (sequential / generic) and `data-extraction.md` (NSC).

| Design family | Pass-fail metrics | Analyses to use |
|---|---|---|
| **Sequential imaging lens** (camera, microscope, scope) | RMS spot radius per field; MTF at target spatial frequency; PV/RMS wavefront error | `StandardSpot` (`SpotData.GetRMSSpotSizeFor(field, wave)`); `FftMtf` or `GeometricMtf` (`DataSeries`); `Wavefront` (`DataGrid` for the OPD map) |
| **Sequential afocal / collimator** | Beam size + divergence at exit; wavefront flatness | `StandardSpot` at infinite conjugate; `Wavefront`; cardinal-points data |
| **NSC illumination / non-coherent** | Total flux on each detector; irradiance uniformity; falloff vs angle | `NCE.GetDetectorData(obj, 0, 0, 0)` (pixel=0 = total; -1 = max, not total); `New_Analysis(DetectorViewer)` for the irradiance grid (set `settings.Detector` per detector) |
| **NSC stray light** | Power on stray-light detectors; segment count after filtering | `OpenNSCRayTrace` with `SaveRays = True`; `OpenRayDatabaseReader` + filter strings |
| **NSC coherent / interference** | Total power; fringe period (FFT of \|Ex\|² center row); visibility (envelope-subtracted RMS); S0 fringe suppression | `GetAllCoherentDataSafe(obj, DDT.Real / Imaginary)`; Detector Viewer for incoherent S0 (see `data-extraction.md` § "Stokes workaround") |
| **Sequential laser propagation** (Gaussian beam through real lenses, spatial filter, fiber coupling) | Peak irradiance; pilot beam waist + Rayleigh range at end surface; M² (X, Y); fiber coupling efficiency; full Ex+Ey complex grid | `New_Analysis(AnalysisIDM.PhysicalOpticsPropagation)` (see `physical-optics.md`); `POPD` operands for closed-loop optimization on those values |
| **Polarization optics** (PBS, QWPs, gratings) | Polarization purity / DOLP; Stokes parameter maps; expected vs actual S3 (handedness) | Coherent Ex from API + Detector Viewer S0 → derive Iy / S1 / S2; `surf.GetCoatingPerformanceData()` for thin-film-coating R/T |
| **Optimized sequential design** | Initial vs final merit function value; per-operand contribution after run | `MFE.CalculateMeritFunction()` before/after; `OpenLocalOptimization` exposes `InitialMeritFunction` / `CurrentMeritFunction` |
| **Multi-config (zoom, thermal)** | Per-config focus shift; per-config metric (spot, MTF) | Loop `MCE.SetCurrentConfiguration(i)` and re-extract |

**Always state pass/fail thresholds explicitly** rather than just printing numbers — the agent should fail loudly when a result misses spec. Example:

```python
rms = spot_results.SpotData.GetRMSSpotSizeFor(field=1, wave=1)
TARGET_RMS_UM = 5.0
if rms * 1000 > TARGET_RMS_UM:
    raise AssertionError(f'RMS spot {rms*1000:.2f}um exceeds {TARGET_RMS_UM}um target at field 1')
```

This turns "the script ran" into "the design met spec," which is what verification actually means.

---

## Step 4: save artifacts

Save everything that lets a human (or you in a future iteration) reconstruct what happened:

```python
import os, json, datetime as dt
ts = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
out = os.path.join(r'C:\path\to\runs', f'run_{ts}')
os.makedirs(out, exist_ok=True)

# 1. The .zos itself — the canonical record
TheSystem.SaveAs(os.path.join(out, 'design.zos'))

# 2. Layout images (Step 2) — see analyses.md § "NSC 3D Layout image export"
#    for the save_3d_layout(TheSystem, ZOSAPI, TheApplication, output_path, ...) helper.
#    Sequential equivalents on Tools.Layouts: OpenShadedModelExport, Open3DViewerExport.
save_3d_layout(TheSystem, ZOSAPI, TheApplication, os.path.join(out, 'layout.JPG'))

# 3. Per-analysis matplotlib plots (line plots, 2D maps) — see analyses.md / data-extraction.md
# fig.savefig(os.path.join(out, 'mtf.png'), dpi=150)
# fig.savefig(os.path.join(out, 'detector.png'), dpi=150)

# 4. Numeric report
report = {
    'timestamp': ts,
    'system_status': TheSystem.GetCurrentStatus() or 'OK',
    'metrics': {
        'rms_spot_um_field1': rms_um,
        'mtf_at_50cymm': mtf_50,
        'detector_power_W': total_power,
        # ...
    },
    'thresholds': {
        'rms_spot_um_target': TARGET_RMS_UM,
        # ...
    },
    'pass': all_thresholds_met,
}
with open(os.path.join(out, 'report.json'), 'w') as f:
    json.dump(report, f, indent=2)
```

Suggested layout for a run directory:
```
runs/
  run_20260430_143012/
    design.zos
    layout.JPG          ← from Tools.Layouts.OpenNSC3DLayoutExport (see analyses.md)
    mtf.png             ← matplotlib from DataSeries
    detector.png        ← matplotlib from coherent extraction
    report.json         ← metrics + pass/fail
    notes.md            ← (optional) human commentary
```

When the agent reports "I optimized the design," the human can look at one folder and see: did it converge? does the layout look sane? does the MTF meet spec? — without rerunning anything.

---

## Worked skeleton: sequential imaging-system optimize-and-check

The most-asked design family (camera/microscope/scope objectives) plugs into the four-step pattern like this. Treat it as the boilerplate to copy and adapt; don't rewrite from scratch.

```python
import os, json, shutil, datetime as dt
import matplotlib.pyplot as plt
AIDM = ZOSAPI.Analysis.AnalysisIDM
out = os.path.join(r'C:\path\to\runs', dt.datetime.now().strftime('run_%Y%m%d_%H%M%S'))
os.makedirs(out, exist_ok=True)

# 1. Auto-build the merit function (don't hand-add operands — see optimization.md § "Wizards")
wiz = TheSystem.MFE.SEQOptimizationWizard2
wiz.Type      = ZOSAPI.Wizards.OptimizationTypes.RMS          # RMS | PTV
wiz.Criterion = ZOSAPI.Wizards.CriterionTypes.Wavefront       # Wavefront | Spot | Angular | Contrast
wiz.Reference = ZOSAPI.Wizards.ReferenceTypes.Centroid        # Centroid | ChiefRay | Unreferenced
wiz.UseGlassBoundaryValues = True; wiz.GlassMin = 3; wiz.GlassMax = 15; wiz.GlassEdgeThickness = 3
wiz.UseAirBoundaryValues   = True; wiz.AirMin   = 0.5; wiz.AirMax = 1000; wiz.AirEdgeThickness   = 0.5
wiz.Apply()

# 2. Optimize
opt = TheSystem.Tools.OpenLocalOptimization()
opt.Algorithm = ZOSAPI.Tools.Optimization.OptimizationAlgorithm.DampedLeastSquares
opt.Cycles    = ZOSAPI.Tools.Optimization.OptimizationCycles.Automatic
mf_initial = opt.InitialMeritFunction
opt.RunAndWaitForCompletion()
mf_final = opt.CurrentMeritFunction
opt.Close()

# 3. Validate (see SKILL principle 3 + patterns.md § "System-validity check")
status = TheSystem.UpdateStatus()
if status:
    raise RuntimeError(f"System invalid after optimization: {status}")

# 4. Capture layout image — use the export tool, NOT analysis.ToFile (which silently
#    no-ops in Standalone mode). See analyses.md § "NSC 3D Layout image export" for
#    the full save_3d_layout() helper, including the ImagesDir copy workaround.
#    Sequential equivalents live on Tools.Layouts: OpenShadedModelExport,
#    Open3DViewerExport, OpenCrossSectionExport.
shaded = TheSystem.Tools.Layouts.OpenShadedModelExport()
try:
    shaded.SaveImageAsFile = True
    shaded.OutputFileName  = os.path.join(TheApplication.ImagesDir, 'shaded.JPG')
    shaded.OutputPixelWidth, shaded.OutputPixelHeight = 1600, 1000
    if shaded.IsValidFileName and shaded.RunAndWaitForCompletion():
        shutil.copy2(shaded.OutputFileName, os.path.join(out, 'shaded.JPG'))
finally:
    shaded.Close()

# 5. Extract image-quality metrics. Pull NUMBERS via SpotData / DataSeries / DataGrid
#    and PLOT with matplotlib — analysis.ToFile is unreliable in Standalone mode for
#    rendered figures too. See analyses.md § "AnalysisIDM enum" for the full menu.

# Spot — numeric only (ScatterPoints + SpotData)
spot = TheSystem.Analyses.New_StandardSpot()
spot.ApplyAndWaitForCompletion()
spot_results = spot.GetResults()
rms_um = {f: spot_results.SpotData.GetRMSSpotSizeFor(f, 0) * 1000   # mm -> um
          for f in range(1, TheSystem.SystemData.Fields.NumberOfFields + 1)}
spot.Close()

# MTF — extract DataSeries and plot manually
mtf = TheSystem.Analyses.New_FftMtf()
mtf.GetSettings().MaximumFrequency = 100   # cycles/mm
mtf.ApplyAndWaitForCompletion()
mtf_results = mtf.GetResults()
fig, ax = plt.subplots()
for i in range(mtf_results.NumberOfDataSeries):
    s = mtf_results.GetDataSeries(i)
    x = list(s.XData.Data)
    y_raw = s.YData.Data
    y = zos.reshape(y_raw, y_raw.GetLength(0), y_raw.GetLength(1), True)
    for trace in y:
        ax.plot(x, trace)
ax.set_xlabel('cycles/mm'); ax.set_ylabel('Modulation'); ax.set_title('FFT MTF')
fig.savefig(os.path.join(out, 'mtf.png'), dpi=150); plt.close(fig)
mtf.Close()

# Field Curvature + Distortion — same DataSeries pattern (rarely run by humans, often missed by agents)
fc = TheSystem.Analyses.New_Analysis(AIDM.FieldCurvatureAndDistortion)
fc.ApplyAndWaitForCompletion()
# (extract series + matplotlib as above; or use results.GetTextFile(...) for the text dump)
fc.Close()

# 6. Pass/fail report
TARGET_RMS_UM = 5.0
all_pass = max(rms_um.values()) <= TARGET_RMS_UM
report = {
    'status':         TheSystem.GetCurrentStatus() or 'OK',
    'mf_initial':     mf_initial,
    'mf_final':       mf_final,
    'rms_um_per_field': rms_um,
    'rms_um_target':  TARGET_RMS_UM,
    'pass':           all_pass,
}
with open(os.path.join(out, 'report.json'), 'w') as f:
    json.dump(report, f, indent=2)
TheSystem.SaveAs(os.path.join(out, 'design.zos'))

if not all_pass:
    raise AssertionError(f"Spot RMS exceeds target: {rms_um}")
```

For a different design family (NSC illumination, two-beam interference, ...), keep steps 3, 4, 6 and the artifact-folder convention; replace steps 1, 2, 5 with the relevant analyses from the table above.

## When this pattern doesn't fit

A few designs need verification that doesn't map to the analyses framework:

- **Tolerancing studies** — the metric is a distribution (Monte Carlo), not a single number. Save `tol.MeanCriterion`, `MinCriterion`, `MaxCriterion`, and `WorstOffenders`. See `optimization.md` § "Tolerancing."
- **Thermal sweeps** — loop configurations, save metrics per config, plot vs temperature. See `multi-config.md` § "Multi-config alignment loop."
- **Polarization-sensitive and two-beam-interference coherent setups** — fringe verification doesn't have a built-in operand; extract via the Stokes workaround in `data-extraction.md` and validate period via FFT of the coherent intensity. The pattern is design-specific but the four-step skeleton (validate → image → metrics → artifacts) still holds; just plug the required FFT/visibility/S0 code into Step 3.
- **Beam quality at unusual planes** — for "what does the wavefront look like at this surface?" insert a dummy detector / dummy surface and re-trace; the surface itself is the metric.

In every case the principle is the same: **make the verification produce visible artifacts that fail loudly when something's off**, not silent zero-power runs that look successful because the script didn't crash.
