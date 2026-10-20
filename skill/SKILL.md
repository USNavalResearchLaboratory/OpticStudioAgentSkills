---
name: zemax-zos-api
description: Use whenever writing Python that connects to Zemax OpticStudio via the ZOS-API (pythonnet/clr, ZOSAPI namespace, NSC or sequential modeling). Trigger on imports of `ZOSAPI`, `clr`, or `winreg` for Zemax; on mentions of NSC/non-sequential design, ray tracing, DetectorRectangle, SourceDiode, RectangularVolume, CylinderVolume, StandardSurface, MIRROR material, Jx/Jy polarization, coherent E-field extraction, or birefringent materials. Trigger even when the user describes the design without naming the API — if the underlying tool is Zemax OpticStudio scripted from Python, this skill applies. Don't skip it just because the request looks simple; the API has subtle pythonnet pitfalls that silently misconfigure objects.
disable-model-invocation: true
---

# Zemax ZOS-API

Python control of Zemax OpticStudio runs through pythonnet (the `clr` module), which loads .NET assemblies and bridges them to Python. The ZOS-API is rich but the bridge has sharp edges: assignments to wrong property names succeed silently, plain Python floats get ignored in some setters, and ParN cell numbering doesn't match the GUI column order. Most "the script ran but nothing works" bugs in Zemax automation trace back to one of these.

This skill encodes the patterns that reliably work, derived from extensive runtime probing of v24.1.

## Sequential vs. Non-Sequential — pick the right side first

OpticStudio has two design modes that share the API but use different editors and conventions:

- **Sequential (LDE)** — light passes through a defined sequence of surfaces in order. Use for traditional lens design: imaging objectives, telescopes, microscopes, spectrometers. Start with `references/sequential-design.md`.
- **Non-Sequential (NCE)** — arbitrary 3D arrangement of objects; light is traced wherever rays go. Use for fold mirrors, multiple beam paths, scattering, illumination, polarization-sensitive or interference setups, anything that isn't a clean stack of surfaces. Start with `references/nsc-objects.md` and `references/conventions.md`.

A single `IOpticalSystem` is one or the other (set via `CreateNewSystem(SystemType.Sequential|NonSequential)` or via `MakeSequential()`/`MakeNonSequential()` — the latter is lossy). Some workflows mix both via `OpenConvertToNSCGroup` (see `references/optimization.md`).

Multi-config, optimization, and the analyses framework work identically in both modes.

## Four load-bearing principles

Internalize these before writing any ZOS-API script. Every pattern in this skill follows from them.

### 1. Always use `obj.get_ObjectData().__implementation__` — never bare `ParN` cells for object dimensions

```python
data = obj.get_ObjectData().__implementation__
data.XMinusWidth = 1.5         # SourceDiode beam half-width (NOT XHalfWidth!)
data.MaxAperture = 25.0        # StandardSurface aperture (default is only 1mm)
```

**Why:** `obj.ObjectData` returns the generic `IObject` interface, which only exposes ~10 generic methods. The typed properties (`XMinusWidth`, `MaxAperture`, etc.) live on the concrete .NET class, accessible via `__implementation__`. Without the cast, attempts to set those properties either raise `AttributeError` or, worse, silently create Python attributes that have no effect on the Zemax model.

**Why not ParN cells:** The ParN order differs between object types and rarely matches the GUI column order. CylinderVolume has Par1=`FrontR`, Par2=`ZLength`, Par3=`BackR` — assuming Par2=`BackR` puts the thickness in the wrong slot and silently builds a 12.5mm-thick "waveplate" instead of a 13µm one. The exception is **DetectorRectangle**: its ObjectData properties don't always persist to the saved `.zos` file, so use both `__implementation__` AND cell-based setters as belt-and-suspenders for it.

If you don't know an object's typed properties, run `scripts/probe_object_properties.py` before guessing names. See `references/patterns.md` for the discovery workflow.

### 2. Polarization needs `RandomPolarization = False` and `System.Double()` wrapping

```python
import System
src.SourcesData.RandomPolarization = False         # default is True — overrides Jx/Jy if left
src.SourcesData.set_Jx(System.Double(1.0))         # plain 1.0 is silently ignored
src.SourcesData.set_Jy(System.Double(1.0))
src.SourcesData.set_XPhase(System.Double(0.0))
src.SourcesData.set_YPhase(System.Double(-90.0))   # -90 = LCP, +90 = RCP
```

**Why:** `RandomPolarization=True` (the default) makes the source emit unpolarized light regardless of what you set Jx/Jy to. Forgetting this leaves sources unpolarized after every config attempt. The `System.Double()` wrap is required because pythonnet 3.0+ no longer auto-converts Python floats for these specific .NET method overloads — plain floats get silently dropped.

### 3. Validate after every untrusted edit with `TheSystem.UpdateStatus()`

```python
status = TheSystem.UpdateStatus()       # returns a string
if status:                               # empty string == no errors
    raise RuntimeError(f"System invalid: {status}")
```

**Why:** the Zemax GUI prompts the user when an edit produces an invalid system (missing glass on a surface, undefined aperture, bad sequential ordering, conflicting solves, etc.); the API does not. The edit just sticks, the trace runs, and the detector reads zero — no exception, no warning. `UpdateStatus()` returns an empty string when everything is OK and a diagnostic string otherwise. Wrapping suspicious edits with this check turns silent failures into useful exceptions. `GetCurrentStatus()` returns the same string without forcing re-evaluation.

The most common missing-glass case: stock-lens insertion via `Tools.OpenLensCatalogs` pulls glasses from vendor catalogs (e.g. Edmund AC508-075-A → E-BAF11 → HIKARI) that aren't loaded by default. The catalog-introspection methods (`MaterialCatalogs.GetCatalogsInUse()`, `GetAvailableCatalogs()`, `IsCatalogInUse()`, `AddCatalog()`) let you pre-empt this; `UpdateStatus()` catches it after the fact. See `references/sequential-design.md` and `references/patterns.md` § "System-validity check."

### 4. Mirror `TiltAboutY` empirical sign convention: `+45°` reflects `+Z` to `-X`

```
TiltAboutY = +45°  →  +Z beam reflects to -X
TiltAboutY = -45°  →  +Z beam reflects to +X
```

**Why:** This contradicts the naive right-hand-rule expectation (which would put +X). It's been verified empirically in v24.1. When designing mirror geometry, always sketch the beam path and check signs against this rule, not against intuition. Reflection formulas for arbitrary tilts are in `references/conventions.md`.

## Skill layout — read these as needed

The reference files are loaded into context only when you `Read` them. Pull whichever you need.

**Setup, every script:**
- **`references/boilerplate.md`** — Canonical `PythonStandaloneApplication` class for connection setup. Read first when starting a new script. Cleanup rule, `reshape`/`transpose` helpers for converting `System.Double[,]` arrays to numpy.
- **`references/system-and-application.md`** — `TheApplication` and `TheSystem` namespaces in detail. **All four connection modes** (Standalone, Interactive Extension, User Extension, User Analysis) including the Interactive Extension `UpdateMode` trap. Catalog directories (`GlassDir`, `LensDir`, `CoatingDir`, etc.). License/version checks. File operations on `TheSystem`. **Plus a "Two InsertLensSeq traps" section** documenting two runtime-verified failures of the stock-lens insertion: (1) the leading-shoulder surface comes out with `Thickness = ∞` (caller must explicitly set to `0.0` or every downstream surface goes to Z = ∞ — silent layout/POP failure); (2) the `reverseSurfGeom=True` flag is silently ignored in v24.1 (catalog tool returns identical radii regardless) — includes a `build_reversed_lens` workaround that reads forward-inserted surfaces and rebuilds with negated radii and shifted materials. Read this when configuring connection, browsing catalogs, or inserting any stock lens.
- **`references/interactive-extension.md`** — When and how to use **Interactive Extension** mode (the only mode where image export works). Includes the **agent ↔ user handoff** prompt (you ask the user to enable Programming → Interactive Extension; they reply when done; you connect via `ConnectAsExtension(0)`), the parallel `PythonInteractiveApplication` connection class (which crucially **does NOT call `CloseApplication()` on exit** so the user's GUI stays alive), the standalone-vs-IE feature matrix, and a "do most work in standalone, switch to IE only for the artifact pass" hybrid pattern. Read whenever you need a layout PNG/JPG, a rendered MTF figure, or any other image artifact.
- **`references/pythonnet-gotchas.md`** — The five recurring .NET ↔ Python interop traps in detail. Read when you hit a "values don't seem to apply" bug.

**Building a system:**
- **`references/sequential-design.md`** — LDE basics, surface types, System Explorer (Aperture/Fields/Wavelengths/Environment/Polarization), surface apertures, solves on cells. Read when designing a sequential lens. **Plus a "Coordinate Break pairs: the sequential analog of NSC grouping" recipe** — sequential mode's equivalent of NSC's Null Object + RefObject pattern. Bracket a lens with a pre-CB / post-CB pair; set the pre-CB `TiltAboutY = 180°` to flip the lens in place (cleaner than rebuilding it manually, and preserves aspheric / coating / semi-diameter data). The standard workaround for the broken `InsertLensSeq(reverseSurfGeom=True)` flag. Includes an `insert_flipped_lens` helper. **Plus a "Black Box Lens surfaces (.ZBB files)" recipe** for loading proprietary vendor playback designs — use `SurfaceType.BlackBoxLens` with **two non-obvious bugs documented**: (1) `ISurfaceTypeSettings.Filename` throws NRE for BlackBox — the working setter is `surf.get_SurfaceData().__implementation__.BlackBoxLensFilename` after `ChangeType`; (2) the surface `Comment` field is load-bearing (Zemax persists the BB filename through it) — overwriting Comment with descriptive text breaks the next `LoadFile`. Files live in `<ZemaxDataDir>\BlackBoxes\`. Covers the 8 CHM-documented constraints (no glass on the BB surface, fixed thickness/aperture from the file, no internal stops, mirror-parity gotchas with `OpenAddFoldMirror`, no POP/thermal support, multi-config requires one BB per config, `.ZEC` encrypted coatings must accompany). NSC has no native BlackBox object — use `OpenConvertToNSCGroup` to embed a sequential BB-containing system as an NSC group. Export is GUI-only; the API can only consume existing `.ZBB` files. **Plus a "Converting a .zmx vendor file to an NSC seed" recipe** — when a vendor part isn't in `OpenLensCatalogs` but ships a `.zmx` prescription (common for Thorlabs, custom optics), use `Tools.OpenConvertToNSCGroup()` to bring the real surface data into NSC. Documents all `IConvertToNSCGroup` properties and warns that `MakeNonSequential()` is lossy (it exists but just flips the editor mode without porting surface data).
- **`references/nsc-objects.md`** — ObjectData property tables for the common NSC object types (SourceDiode, SourceGaussian, DetectorRectangle, StandardSurface, RectangularVolume, CylinderVolume). **Plus a "Freeform / asphere / illumination objects" section** (probe-verified property names for EvenAsphereLens, StandardLens, AnnularAsphericLens, CPC, AsphericSurface, DetectorPolar, SourceRadial) for collimator/concentrator/far-field work, with the enum-spelling traps (EvenAsphere**Lens** vs Annular**Aspheric**Lens; the `Facted`/`Frensel` API typos). **Plus a `Slide` entry** — BMP/JPG/PNG transparency for imaging tests (USAF target, scenes); filename rides in the load-bearing `Comment` field, file in `ImagesDir`. Read when adding any NSC object.
- **`references/conventions.md`** — Mirror tilt math, coating rules, RectangularVolume face numbering for tilted plates, birefringent material loading, NSCRayTrace settings. **Plus an "NSC placement: RefObject, InsideOf, and nesting rules" section** covering the coordinate-cascade trap (moving one object shifts every downstream object with `RefObject` chained to it — common "moved a lens, detector went dark" failure), the `InsideOf` refractive-index-parent rule (sources embedded in volumes, nested volumes for air-in-glass), the deterministic last-object-wins tie-breaker at shared boundaries (volumes and surface/volume nesting rules from the CHM), `GlueDistanceInLensUnits` and `MaximumNestedTouchingObjects` settings, and a 3D-Layout geometry-error recovery table (`NumberOfLayoutRays = 0`, `IgnoreErrors`, `OpenNSCShadedModelExport` as a more robust alternative). **Plus a "Grouping multi-element parts under a Null Object parent" recipe** with a reusable `group_under_null_parent` helper — the standard fix for the recurring "moved one element of an achromat doublet and the glasses separated" failure. Insert a `NullObject`, point each child's `RefObject` at it, re-express child coords in the parent's frame; afterward the whole assembly moves as a rigid body. Apply once per multi-element seed (especially after `OpenConvertToNSCGroup`). Read when wiring up a multi-element NSC scene or when the 3D Layout shows "Geometry error" instead of rendering.
- **`references/multi-config.md`** — MCE patterns: configurations, operands, ConfigPickup/ThermalPickup solves, idiomatic per-config alignment loop. Read for thermal/zoom/multi-state designs.
- **`references/nsc-illumination-design.md`** — Non-imaging NSC design workflow (collimators, concentrators, light pipes): Lambertian LED via `SourceRadial`, the `DetectorPolar` far-field detector, and the **collimation merit** that the spatial wizard default can't express (angular criterion `RMS Angular Radius` + MinimumFlux guard, or hand-built NSDD→NSTR→NSDP energy-in-cone). Includes a worked two-element TIR-collimator recipe (Lambertian LED → ±12°). Read for source→far-field illumination optimization.

**Optimizing and analyzing:**
- **`references/optimization.md`** — Merit Function Editor + the **`ZOSAPI.Wizards`** namespace (auto-build merit functions instead of hand-adding 30+ operands — `SEQOptimizationWizard2`, `INSCOptimizationWizard`, `INSCBitmapWizard`, `INSCRoadwayLightingWizard`) + all optimization tools (Local DLS, Global, Hammer, QuickFocus, Scale Lens, Tolerancing). Includes an **"Optimization Wizard (auto-build merit function)"** entry point — read first when you want the optimizer to refine a conjugate distance instead of computing it analytically — and an **"NSC variables"** section covering `ZPositionCell` / `TiltAboutXCell` / etc. (NSC has no "thickness" cells; spacing is variable Z position). **Plus a "Aperture mode and the silent-resize trap" section** — the default `EntrancePupilDiameter` mode lets the optimizer silently resize the stop semi-diameter every cycle, which can grow your physical iris past its mount. Covers when to use `FloatByStopSize`, the bench-is-the-truth pattern, `MNCA`/`MXCA` boundary operands for downstream lens diameters, and the field-type interaction. Read **before marking variables**, not after the optimizer runs and the build doesn't fit. **Plus a "Refocus during merit-function evaluation" section** answering the most-asked least-documented question about Zemax optimization: the optimizer does NOT auto-refocus during MF computation, so you have to set up refocus yourself. Covers the four strategies (mark last thickness Variable, MarginalRayHeight solve, OPD solve, QuickFocus prep), the standard pattern for sequential imaging lenses, the centroid-vs-chief-ray orthogonality, the NSC equivalent (vary the detector's `ZPositionCell`), and a failure-mode table mapping common symptoms ("spot is huge", "POP intensity drops to nothing") to refocus mistakes. Plus a **"Smoke-test the merit function before a long run"** section that uses `RunAndWaitWithTimeout` on local DLS with `Fixed_1Cycle` to catch empty-MF / no-variables / pathological-cost failures before launching Global or Hammer.
- **`references/analyses.md`** — Generic Analyses framework (`New_Analysis(AnalysisIDM.X)`), the result data containers (DataGrid, DataSeries, DataScatterPoints, RayData, SpotData), and recipes for FFT MTF, Spot, Ray Fan, NSC 3D Layout. **Includes a "what design question maps to which analysis" table** covering MTF, PSF, wavefront, ray fans, distortion + field curvature, encircled energy, image simulation + geometric image analysis, coatings R/T/A — read this first when you need a quantitative metric and don't know which analysis produces it. **Plus a "Cardinal Points" recipe** (`AnalysisIDM.CardinalPoints`) for measuring EFL / FFL / BFL / principal-plane positions of a lens or surface range in one call. Replaces the fragile "insert lens forward + insert lens reversed + measure PARY in both" workaround — `InsertLensSeq(reverseSurfGeom=True)` is silently ignored in v24.1 and manual lens reversal drops aspheric coefficients, semi-diameters, and coating data (silently wrong FFL for any non-singlet). **Plus a "Units in analysis results" section** with the always-print-the-labels pattern (`XLabel` / `ValueLabel` / `SeriesLabels` / `HeaderData`) and a per-analysis unit cheat sheet (MTF in cycles per lens-unit, ray fan in μm, OPD in waves, FCD mixing lens-units and percent across series, etc.) — read this before treating any extracted numeric array as a physical quantity. Also documents **`Tools.OpenNSC3DLayoutExport`** (`INSC3DLayoutExport`) for programmatic NSC 3D Layout image export with camera-angle / pixel-size / ray-coloring control — use this when a build script needs to auto-save a layout PNG/JPG/BMP without opening the GUI. Plus a **"Detector Viewer (NSC irradiance map)"** recipe (`IAS_DetectorViewer`) for target-detector uniformity / spot-size verification with both a saveable image and the underlying numeric grid, and the NSC ray-trace **tool-vs-analysis distinction** (no analysis-window NSC ray trace exists; use `Tools.OpenNSCRayTrace` + the 3D Layout for visualization).
- **`references/data-extraction.md`** — NSC-specific detector data: `GetDetectorData` for total power, `GetAllCoherentDataSafe` for the scalar E-field (Ex only — workaround for full Stokes by combining with the Detector Viewer's incoherent irradiance). **Starts with a "Picking the right extraction path" table** and an **NSDD operand readout** recipe for derived scalars (total flux, RMS spot radius, RMS angular radius, centroid, max/min, mean, MTF) — `MFE.GetOperandValue(MOT.NSDD, ...)` runs the optimized internal C# routine in milliseconds, no per-pixel loop, no ZRD. Includes the canonical **collimation check pattern** (`Pix#=-9, Data#=2` on a Detector Rectangle = RMS angular radius). Don't iterate the ZRD for metrics NSDD already exposes. Read for NSC polarization/coherent work and any derived-metric extraction.
- **`references/physical-optics.md`** — Sequential **Physical Optics Propagation (POP)**: diffraction-based beam propagator (`IAS_PhysicalOpticsPropagation`) for laser beams through real lenses, single-mode fiber coupling, spatial-filter modeling, and any sequential coherent E-field work. Includes when-to-use-POP-vs-rays-vs-NSC-coherent table, full settings recipe with `AutoCalculateBeamSampling()`, the `.ZBF` (Zemax Beam File) chain pattern, per-surface POP settings (`surf.PhysicalOpticsData` — pinhole-aperture pattern is critical), the `POPD` merit-function operand for closed-loop optimization on POP results, and the unique advantage over NSC: POP gives full Ex AND Ey complex grids (no Stokes workaround needed). **Plus a "ZBF binary layout" reference and a "Propagating POP past unsupported surfaces" section** for `BlackBoxLens` / GridSag / custom DLL surfaces that POP cannot trace through. The standard fix is one path: load the vendor's playback ZMX (BB already wired), then start POP at the post-BB surface with `BeamType = TopHat` (or `GaussianWaist` for telescope BBs) set to the BB's documented output dimensions — no synthesis needed for the common case. Falls back to a vendor-supplied `.ZBF` or measured-beam `.ZBF` when the built-in primitives don't capture the output profile. Alternative-path table (NSC coherent wrap via `OpenConvertToNSCGroup`, POP-compatible substitution via Paraxial / JonesMatrix / GridPhase) for cases where you need a result *through* the BB rather than after it. Read when the wave nature of light matters or when POP errors on a proprietary surface.
- **`references/ray-database.md`** — Sequential batch ray trace and the NSC ZRD ray database reader. Read when you need millions of per-ray attributes — these are 40× faster than naive loops.

**Boundaries and tactics:**
- **`references/user-extensions.md`** — What Python can and can't do at the extension layer (UDOC, User Analysis, User Extension are C#-only; Python can register operand callbacks). Short — read once.
- **`references/patterns.md`** — Property discovery workflow (using the probe script), in-place parameter sweeps, debugging checklist for the common "no power / wrong period / beams don't reach detector" failures.
- **`references/verification.md`** — How to **check that a design actually does what was intended** after every meaningful change. The four-step pattern (validate → capture layout image → extract numeric metrics with explicit pass/fail thresholds → save artifacts), plus a table mapping common design families (sequential lens, NSC illumination, NSC coherent/interference, polarization optics, multi-config thermal, ...) to the metrics + analyses you should be checking. Also covers `analysis.ToFile()` for layout PNG/JPG/BMP output and `Tools.OpenShadedModelVisualizationExport` for custom 3D rendering. Read whenever you're about to "just run the optimization and report" — verification is the difference between "the script ran" and "the design met spec."

**Bundled tooling:**
- **`scripts/probe_object_properties.py`** — Self-contained probe across **four parts of the API**: NCE object types, LDE surface types, analysis settings (`AnalysisIDM`), and tool settings (`Tools.Open*`). Each section iterates a configurable list at the top of the script. Dumps typed property names, defaults, setter methods, and (for NCE/LDE) ParN cell values. Run it before guessing property names for any unfamiliar type — the same `__implementation__` cast is needed everywhere, and silent Python-attribute creation makes wrong guesses hard to detect.

**External research (when this skill doesn't cover it):**
- **`scripts/chmseek_zos.py`** — wrapper around the `chmseek` CLI that reads OpticStudio's two CHM help files. **Two roles:**
  1. **Discovery** — when the skill doesn't document the interface, method, enum, or concept you need. `ZOS-API.chm` has the full API reference (every interface, every method); `OpticStudio_Help_en.chm` covers optical concepts and GUI features the API exposes thinly.
  2. **Debugging** — **first response when an exception fires.** A `System.ArgumentException: Expected Integer, got 'Double'`, `AttributeError`, or "value cannot be converted" message means the API has a documented type/shape that you got wrong. Look it up via `chmseek_zos.py search "<TypeName>"` before writing a try/except wrapper or catch-and-fallback. The exception is the signal; swallowing it loses the signal and usually masks a real bug. See `pythonnet-gotchas.md` § "Loud failures: look it up, don't catch."

  The wrapper handles Windows encoding for its own output, accepts `--chm zos` / `--chm gui` shortcuts, and prints scannable results with copy/paste-ready READ commands. **If you invoke it via `conda run` from another project dir, you MUST add `--no-capture-output`** — bare `conda run` re-encodes the child's stdout through cp1252 and crashes on the non-ASCII in CHM content (the wrapper can't prevent conda's re-encode step). Workflow, examples, and the `conda run` trap are in `references/patterns.md` § "Looking up the API with chmseek." **Reach for it before assuming an API doesn't exist or writing a workaround for an exception.**

## Starter template

A minimal scene to copy and adapt. Connect, build a one-source / one-detector NSC system, ray-trace, read total power, clean up:

```python
import clr, os, winreg
# (PythonStandaloneApplication boilerplate — see references/boilerplate.md)
zos = PythonStandaloneApplication()
ZOSAPI, TheApplication = zos.ZOSAPI, zos.TheApplication
TheSystem = TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)
NCE = TheSystem.NCE
TheSystem.SystemData.Wavelengths.GetWavelength(1).Wavelength = 0.473  # um
OT = ZOSAPI.Editors.NCE.ObjectType

# Source
src = NCE.GetObjectAt(1)
src.ChangeType(src.GetObjectTypeSettings(OT.SourceDiode))
sdata = src.get_ObjectData().__implementation__
sdata.XMinusWidth = sdata.YMinusWidth = 1.5         # mm, 1/e^2 half-width
sdata.XMinusDivergence = sdata.YMinusDivergence = 0.043  # deg
sdata.Power = 0.2                                   # W
sdata.NumberOfAnalysisRays = 1_000_000
src.ZPosition = -100.0                              # mm

# Detector
NCE.InsertNewObjectAt(2)
det = NCE.GetObjectAt(2)
det.ChangeType(det.GetObjectTypeSettings(OT.DetectorRectangle))
ddata = det.get_ObjectData().__implementation__
ddata.XHalfWidth = ddata.YHalfWidth = 1.0
ddata.NumberXPixels = ddata.NumberYPixels = 100

# Ray trace
rt = TheSystem.Tools.OpenNSCRayTrace()
rt.SplitNSCRays = False; rt.ScatterNSCRays = False
rt.UsePolarization = True; rt.IgnoreErrors = True
rt.ClearDetectors(0); rt.RunAndWaitForCompletion(); rt.Close()

_, power = NCE.GetDetectorData(2, -1, 0, 0)
print(f"Power on detector: {power:.4e} W")

del zos; zos = None
```
