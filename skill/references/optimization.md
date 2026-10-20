# Merit Function and Optimization

Optimization in OpticStudio is a two-part workflow: build a Merit Function (MFE) that quantifies "how good" the design is, then run an optimization tool that varies the marked-variable parameters to minimize it. This file covers both, plus the related tools (QuickFocus, Scale Lens, Tolerancing).

All optimization tools follow the same lifecycle: `Tools.Open*()` → set settings → `RunAndWaitForCompletion()` → read results → `Close()`.

**Only one `ISystemTool` can be open at a time** (per the `IOpticalSystemTools` interface contract). Forgetting `Close()` blocks the next `Tools.Open*()` call from succeeding — the API will silently return a closed tool or throw, depending on version. Always close before opening another.

**`RunAndWaitForCompletion()` returns a `ZOSAPI.Tools.RunStatus`**: `Completed`, `FailedToStart`, `TimedOut`, or `InvalidTimeout`. The skill code in this file omits the check for brevity, but in real scripts capture the return value and branch on it — silent failures here are the second-most-common "the optimizer didn't actually run" bug after forgetting to mark variables.

```python
opt = TheSystem.Tools.OpenLocalOptimization()
# ... configure ...
status = opt.RunAndWaitForCompletion()
if status != ZOSAPI.Tools.RunStatus.Completed:
    raise RuntimeError(f"Optimization did not complete: {status}")
opt.Close()
```

**`TheSystem.Tools.RemoveAllVariables()`** is a direct method (not an `Open*` tool) — clears every variable solve in the system in one call. Use before re-marking a fresh set of variables for an optimization run.

## Optimization Wizard (auto-build merit function)

Before any of the manual MFE/operand machinery below, **try the Optimization Wizard first**. It generates a default merit function (image-quality MF: RMS spot or wavefront across all fields and wavelengths, plus the boundary constraints) — i.e. exactly what hand-anchoring lens positions usually fails to capture. The wizard is the right entry point when you want to *let the optimizer find the conjugate distance* (e.g. the object-to-image conjugate distance for a relay) instead of computing it analytically and discovering an EFL-vs-BFL mismatch later.

The wizard interfaces live in `ZOSAPI.Wizards`, and each is reached as a property on the **MFE editor** (sequential) or **NCE editor** (NSC). The detailed wizard list and the full sequential recipe are in **§ "Auto-build the merit function with a Wizard"** further down — re-read it now if you haven't. The TL;DR sequential pattern:

```python
# Optionally clear the MFE first. Use DeleteAllRows() — the canonical "clear
# everything" method on the IEditor base interface (works on LDE/NCE/MCE/MFE/TDE
# uniformly). DO NOT call RemoveAllOperands() — that method does NOT exist on
# IMeritFunctionEditor. DO NOT loop RemoveOperandAt(i) — observed empirically
# to crash the IPC pipe in standalone mode (likely index-shift confusion as
# rows shift up after each removal). If you really want incremental removal
# rather than DeleteAllRows, use the plural RemoveOperandsAt(start, count) in
# one call, or iterate in REVERSE-index order.
TheSystem.MFE.DeleteAllRows()              # safe; or skip entirely — wizard.Apply() overwrites from StartAt anyway
wiz = TheSystem.MFE.SEQOptimizationWizard2
# Skip Rings/Arms — they're typed as PupilRingsCount/PupilArmsCount enums
# (pythonnet 3 won't auto-coerce ints), and defaults Rings=3 / Arms=6 are
# what most designs want anyway. See full property list further down.
wiz.Type      = ZOSAPI.Wizards.OptimizationTypes.RMS
wiz.Criterion = ZOSAPI.Wizards.CriterionTypes.Spot         # NOT wiz.Data — that property doesn't exist. Spot / Wavefront / Angular / Contrast
wiz.Reference = ZOSAPI.Wizards.ReferenceTypes.Centroid
wiz.AssumeAxialSymmetry = True
wiz.UseGaussianQuadrature = True
wiz.UseGlassBoundaryValues = True; wiz.GlassMin=3; wiz.GlassMax=15; wiz.GlassEdgeThickness=3
wiz.UseAirBoundaryValues   = True; wiz.AirMin=0.5; wiz.AirMax=1000; wiz.AirEdgeThickness=0.5
wiz.OverallWeight = 1.0
wiz.StartAt = 1                                            # direct property, NOT wiz.CommonSettings.StartAt
wiz.Apply()                                                # populates the MFE
```

**NSC mode uses a different wizard.** `SEQOptimizationWizard2` is sequential-only; the non-sequential equivalent is `INSCOptimizationWizard`, accessed off the same `TheSystem.MFE` namespace but with NSC-specific properties (`UseDetector`, `UseSource`, `Criterion`, `MinimumFlux`, `RaySampling`, `EdgeSampling`, `OverallWeight`, `IsRaytraceSettingsUsed`, `IsSplitRaysUsed`, `IsScatterRaysUsed`, `IsUsePolarizationUsed`, `IsClearDataSettingsUsed`, `IsResampleDetectorUsed`, `BitmapFile`). It builds an MFE that targets one detector criterion (uniformity / max irradiance / total flux / etc.) for one source. Discoverable via `print(dir(TheSystem.MFE.NSCOptimizationWizard.__implementation__))`.

```python
nwiz = TheSystem.MFE.NSCOptimizationWizard          # INSCOptimizationWizard
nwiz.UseSource   = 0                                # 0 = all sources
nwiz.UseDetector = 7                                # object # of the target/image detector
nwiz.Criterion   = 1                                # see GetCriterionAt(i) for the enum-via-string list
nwiz.IsClearDataSettingsUsed = True
nwiz.IsRaytraceSettingsUsed  = True
nwiz.IsSplitRaysUsed = False; nwiz.IsScatterRaysUsed = False
nwiz.IsUsePolarizationUsed = True
nwiz.OverallWeight = 1.0
nwiz.CommonSettings.StartAt = 1
nwiz.Apply()
```

Internally this wizard generates an `NSDD ... 0 0 0` (clear-detectors) row, an `NSTR` row (trace from source), and a group of `NSDD/NSDC/NSDP` readout rows targeting your chosen criterion. Same machinery as building the operands by hand, but consistent across runs.

**Limitations to know:**
- `SEQOptimizationWizard2` is sequential-only — it operates on LDE surfaces. Calling it in an NSC system has no useful effect.
- The Optimization Wizard *builds* the merit function; it does not run optimization. After `Apply()`, mark variables (next section) and call `Tools.OpenLocalOptimization()`.
- Add custom operands (e.g. specific conjugate-distance constraints) **after** `wiz.Apply()`, not before — `Apply()` overwrites the MFE from `StartAt` onward.
- After `Apply()`, **call `TheSystem.UpdateStatus()`** — a malformed wizard config (e.g. `UseDetector` pointing at a non-detector object) leaves the MFE in a broken state without raising.

## NSC variables (no thickness cells — use position cells)

NSC has no "thickness cells" the way LDE does; lens *spacing* is encoded as the `ZPosition` of each downstream object. To let the optimizer refine a relay's lens positions, mark the **`ZPositionCell`** (or `XPositionCell` / `YPositionCell` / `TiltAboutXCell` / `TiltAboutYCell` / `TiltAboutZCell`) as a variable on each `INCERow`. These cells are confirmed on `ZOSAPI.Editors.NCE.INCERow` and inherit the standard `IEditorCell` interface, so the same `MakeSolveVariable()` / `MakeSolveFixed()` methods apply:

```python
TheSystem.Tools.RemoveAllVariables()                      # clear any previous variables

obj = TheSystem.NCE.GetObjectAt(5)                        # the lens to vary
obj.ZPositionCell.MakeSolveVariable()                     # let optimizer move it along Z
obj.TiltAboutYCell.MakeSolveVariable()                    # and tilt it about Y

# Object-specific shape parameters (radius, conic, etc.) are still on ParN cells:
obj.GetCellAt(int(ZOSAPI.Editors.NCE.ObjectColumn.Par2)).MakeSolveVariable()

status = TheSystem.UpdateStatus()                         # validate after marking variables
if status:
    raise RuntimeError(f"System invalid after marking variables: {status}")
```

Use `obj.GetObjectCell(ZOSAPI.Editors.NCE.ObjectColumn.<name>)` (or `obj.GetCellAt(int_index)`) for the typed-by-name path to per-object parameters; the explicit cell-property accessors (`ZPositionCell`, etc.) are clearer for the standard pose parameters.

After running an NSC optimization, **always call `TheSystem.UpdateStatus()` again** before reading the optimized values — the optimizer can leave the system in a state that the GUI would flag (e.g. an object pushed inside another), and the status check is your only programmatic warning.

```python
opt = TheSystem.Tools.OpenLocalOptimization()
opt.Algorithm = ZOSAPI.Tools.Optimization.OptimizationAlgorithm.DampedLeastSquares
opt.Cycles = ZOSAPI.Tools.Optimization.OptimizationCycles.Automatic
status = opt.RunAndWaitForCompletion()
opt.Close()
if status != ZOSAPI.Tools.RunStatus.Completed:
    raise RuntimeError(f"Optimization failed: {status}")
post = TheSystem.UpdateStatus()
if post:
    raise RuntimeError(f"Optimized system invalid: {post}")
print(f"New Z = {TheSystem.NCE.GetObjectAt(5).ZPosition:.4f}")
```

## Merit Function Editor (MFE)

```python
TheMFE = TheSystem.MFE
op = TheMFE.AddOperand()                        # appended at end
op = TheMFE.InsertNewOperandAt(idx)             # at specific row (1-based)
op.ChangeType(ZOSAPI.Editors.MFE.MeritOperandType.RSCE)
op.Target = 0.0
op.Weight = 10.0
op.GetCellAt(2).IntegerValue = 1                # operand-specific args via cells
TheMFE.NumberOfOperands
TheMFE.GetOperandAt(idx)
TheMFE.RemoveOperandAt(idx)                     # see warning below — fragile in standalone
TheMFE.RemoveOperandsAt(start, count)           # batch remove (safer in one call)
TheMFE.DeleteAllRows()                          # clear the entire MFE — IEditor base method, canonical
mf_value = TheMFE.CalculateMeritFunction()      # current MF value
```

**Removing operands — pitfalls and the safe path.** `IMeritFunctionEditor` does **not** have a `RemoveAllOperands()` method (despite the name an agent might guess). The actual options:

| Method | When |
|---|---|
| `TheMFE.DeleteAllRows()` | **Preferred for "clear everything."** Inherited from `IEditor`; works the same way on LDE/NCE/MCE/MFE/TDE. |
| `TheMFE.RemoveOperandsAt(start, count)` | Batch remove a contiguous block in one IPC call. Use when you want to keep some operands. |
| `TheMFE.RemoveOperandAt(i)` | One-at-a-time. **Observed empirically to crash the IPC pipe in standalone mode** when called in a forward-index loop (rows shift up after each removal, so subsequent calls reference already-removed rows). If you really must remove one at a time, iterate in reverse-index order: `for i in range(TheMFE.NumberOfOperands, 0, -1): TheMFE.RemoveOperandAt(i)`. |

If you're calling the Optimization Wizard right after, you don't need to clear at all — `wiz.Apply()` overwrites the MFE from `CommonSettings.StartAt` onward.

**Cell access for operand parameters.** Each `MeritOperandType` defines what the cells mean (e.g. for `MNCA`/`MXCA`, `GetCellAt(2)` is the start surface and `GetCellAt(3)` is the end surface). The CHM has the per-operand cell layouts; the GUI's Merit Function Editor also displays the column headers when you select the operand. **Do not assume cell indices** — verify against the CHM or by reading defaults after `ChangeType`.

### Cell value type: look it up, don't try/fallback

Every editor cell exposes both `IntegerValue` and `DoubleValue` setters in pythonnet, but **only one is valid for a given cell**. Calling the wrong one raises `System.ArgumentException: Expected Integer, got 'Double'` (or the reverse — the message is reversed-feeling: the Zemax cell type appears second). The temptation is to write a try/fallback wrapper that catches the exception and tries the other setter. **Do not do that for MFE operand cells.** It's an antipattern here for three reasons:

1. **MFE operand cell types are documented per operand.** Every `MeritOperandType.X` has a fixed cell layout in the CHM (`MeritOperandType.RSCE`: Surf=int, Wave=int, Hx=double, Hy=double, Px=double, Py=double, ring sampling=int). There is no ambiguity to defend against — look it up.
2. **A try/fallback masks real bugs.** A typo, the wrong cell index, or a stale assumption about an operand's layout silently gets retried with the wrong setter and may succeed (truncating a 0.7 to 0, setting a surface number to 1 from a 1.5 you meant to fix). The exception was the signal that something is wrong; swallowing it loses the signal.
3. **Heuristics on the value type are wrong.** "If `value.is_integer()` use `IntegerValue` first" gets it backward for any cell that wants `0.0` on a Double-typed input (Hx=0, Py=0, etc.). The right type is determined by the **cell**, not by what value you happen to be passing.

**Do this instead:**

```python
# 1) Look up the cell layout once, hard-code the setters per operand.
def add_RSCE(MFE, surf, wave, hx, hy, target=0.0, weight=1.0):
    op = MFE.AddOperand()
    op.ChangeType(ZOSAPI.Editors.MFE.MeritOperandType.RSCE)
    op.GetCellAt(2).IntegerValue = int(surf)        # Surf — int
    op.GetCellAt(3).IntegerValue = int(wave)        # Wave — int
    op.GetCellAt(4).DoubleValue  = float(hx)        # Hx   — double
    op.GetCellAt(5).DoubleValue  = float(hy)        # Hy   — double
    op.Target = float(target); op.Weight = float(weight)
    return op
```

**Look the layout up via:**
- `chmseek_zos.py search "MeritOperandType.<NAME>"` — returns the operand's CHM page with cell-by-cell descriptions.
- The GUI's MFE column headers — select an operand row in the editor and the headers show "Surf", "Wave", "Hx", "Hy", etc.
- `op.GetCellAt(i).Value` (read) after `ChangeType` returns defaults; `Value` is a string but the type appears in the cell display.

**When try/fallback IS appropriate** — and the only time:

- **MCE `IGNR` cell** — integer-typed but no documented note that it differs from the surrounding double cells. See `multi-config.md`.
- **Coordinate Break `Order` cell** (Par column) — integer-typed in an otherwise double-cell row. See `sequential-design.md`.
- **A handful of NSC ParN cells** where the integer/double split isn't documented and varies by object type.

In those cases, the try/fallback is a defense against an undocumented corner of the API — **not** a default pattern for every editor cell. If you find yourself wrapping every `_set_cell` call in a try/fallback, you've stopped using the type system as a debugging tool. Look it up.

### Common operand types

| Operand | What it constrains | Typical cells (Param1, Param2, ...) |
|---------|-------------------|-------------------------------------|
| `DMFS` | Default Merit Function start marker | none |
| `BLNK` | Comment / blank row | none |
| `EFFL` | Effective focal length | wavelength |
| `ASTI` | Astigmatism | surface, wave, field |
| `COMA` | Coma | surface, wave, field |
| `RSCE` / `RSCH` | RMS spot radius (Centroid / Chief) | surface, wave, field, ring sampling |
| `RWCE` / `RWCH` | RMS wavefront error | surface, wave, field |
| `MTFA` / `MTFT` / `MTFS` | MTF (avg, tangential, sagittal) | spatial freq, wave, field |
| `OPLT` / `OPGT` / `OPEQ` | Numeric inequality (less / greater / equal) on another operand row | row index, target |
| `MNCA` / `MXCA` | Min / max center thickness, air | start surf, end surf |
| `MNEA` / `MXEA` | Min / max edge thickness, air | start surf, end surf |
| `MNCG` / `MXCG` | Min / max center thickness, glass | start surf, end surf |
| `MNEG` / `MXEG` | Min / max edge thickness, glass | start surf, end surf |
| `MNIN` / `MXIN` | Min / max index of refraction (boundary on glass) | start surf, end surf |
| `UDOC` | User-Defined Operand (compiled C#/C++) — see `user-extensions.md` | UDOC index |

### Boundary-constraint pattern (avoid optimization-collapsed lenses)

A typical setup adds boundary operands so the optimizer can't drive thicknesses to zero or material indices into nonsense:

```python
MFOT = ZOSAPI.Editors.MFE.MeritOperandType
for op_type, target in [(MFOT.MNCA, 0.5), (MFOT.MXCA, 1000.0),
                        (MFOT.MNEA, 0.5),
                        (MFOT.MNCG, 3.0),  (MFOT.MXCG, 15.0),
                        (MFOT.MNEG, 3.0)]:
    op = TheMFE.AddOperand()
    op.ChangeType(op_type)
    op.Target = target; op.Weight = 1.0
    op.GetCellAt(2).IntegerValue = 1                 # start surface
    op.GetCellAt(3).IntegerValue = 3                 # end surface
```

The Merit Function Wizard in the GUI generates similar boilerplate; for scripted runs it's easier to add it explicitly.

### Marking variables for optimization

Make a surface property variable with `MakeSolveVariable()` on the cell:
```python
LDE.GetSurfaceAt(2).RadiusCell.MakeSolveVariable()
LDE.GetSurfaceAt(2).ThicknessCell.MakeSolveVariable()
```

For NSC parameters, mark the corresponding ParN cell variable using the same method on `obj.GetObjectCell(OC.Par3)`.

## Auto-build the merit function with a Wizard (`ZOSAPI.Wizards`)

For any standard imaging-design merit function — RMS spot or wavefront across all fields/wavelengths, with the usual boundary constraints — **don't hand-add 30+ operands**. Use the corresponding wizard from `ZOSAPI.Wizards`. It does everything the GUI's Optimization Wizard dialog does, accessed via `TheSystem.MFE.<WizardName>`.

```python
# Property names below are chmseek-confirmed against ISEQOptimizationWizard2.
# ALWAYS run scripts/probe_object_properties.py against the wizard before
# guessing — agent-invented names like "wiz.Data", "wiz.IsGlassUsed",
# "wiz.IsAirUsed", "wiz.IsAssumeAxialSymmetry", "wiz.GridSampling",
# "wiz.PupilIntegrationMethod" are NOT real properties and silently no-op
# (silent-Python-attribute trap — see pythonnet-gotchas.md).
wiz = TheSystem.MFE.SEQOptimizationWizard2

# Pupil sampling (Rings, Arms) — TYPED AS ENUMS (PupilRingsCount, PupilArmsCount),
# NOT raw ints. Pythonnet 3 won't auto-coerce `wiz.Rings = 3`. Easiest fix:
# DON'T SET THEM — defaults are Rings=3, Arms=6, which is what most designs want.
# If you really need to override, construct the enum:
# wiz.Rings = ZOSAPI.Wizards.PupilRingsCount.Ring_5

# Type / Criterion / Reference — also enums (don't pass ints):
wiz.Type      = ZOSAPI.Wizards.OptimizationTypes.RMS                 # RMS / PTV
wiz.Criterion = ZOSAPI.Wizards.CriterionTypes.Spot                   # Spot / Wavefront / Angular / Contrast
wiz.Reference = ZOSAPI.Wizards.ReferenceTypes.Centroid               # Centroid / ChiefRay / Unreferenced

# Sampling alternatives to Gaussian quadrature
wiz.UseGaussianQuadrature = True
# wiz.UseRectangularArray = True; wiz.GridSizeNxN = 6                # mutually exclusive with UseGaussianQuadrature

# Symmetry + obscuration
wiz.AssumeAxialSymmetry = True
wiz.Obscuration = 0.0                                                # double, 0.0–1.0

# Boundary constraints (the actual property names)
wiz.UseGlassBoundaryValues = True
wiz.GlassMin = 3.0; wiz.GlassMax = 15.0; wiz.GlassEdgeThickness = 3.0
wiz.UseAirBoundaryValues = True
wiz.AirMin   = 0.5; wiz.AirMax   = 1000.0; wiz.AirEdgeThickness   = 0.5

# Overall weight + insertion point
wiz.OverallWeight = 1.0
wiz.StartAt = 1                                                      # MFE row to insert at (direct prop, not wiz.CommonSettings.StartAt)

wiz.Apply()                                                          # populates the MFE
```

**Discoverable via probe:** the chmseek-confirmed `ISEQOptimizationWizard2` properties also include `Criterion`, `SpatialFrequency` (when `Criterion = MTF`), `UseAllConfigurations` / `ConfigurationNumber`, `UseAllFields` / `FieldNumber`, `IgnoreLateralColor`, `DeleteVignetted`, `MaxDistortionPct` / `UseMaximumDistortion`, plus the Manufacturing-Yield knobs (`OptimizeForBestNominalPerformance`, `OptimizeForManufacturingYield`, `ManufacturingYieldWeight`, `IsHighManufacturingYieldAvailable`). Methods: `Apply()`, `Initialize()`, `OK()`, `LoadSettings()`, `SaveSettings()`, `ResetSettings()`. **Probe before assuming any other name exists.**

The available wizard interfaces in `ZOSAPI.Wizards`:

| Wizard | Use case |
|---|---|
| `ISEQOptimizationWizard2` | Sequential default merit function (image-quality MF). Always prefer this over the obsolete `ISEQOptimizationWizard`. |
| `INSCOptimizationWizard` | Non-sequential design optimization MF (per-detector criteria). |
| `INSCBitmapWizard` | NSC bitmap-target merit function (e.g. illumination matching a target image). |
| `INSCRoadwayLightingWizard` | NSC roadway-lighting MF. |
| `ISEQToleranceWizard` | Sequential tolerance setup (already covered in § "Tolerancing"). |
| `INSCToleranceWizard` | NSC tolerance setup. |

Each wizard's typed properties are discoverable via the probe script — add `('SEQOptimizationWizard2', 'TheSystem.MFE.SEQOptimizationWizard2')` to a custom probe call, or just `print(dir(wiz.__implementation__))`.

**Pattern:** wizard first, then add any non-standard custom operands manually after `Apply()`. Don't reinvent the boundary-constraint boilerplate every time — that's exactly what the wizard handles.

## Aperture mode and the silent-resize trap

**Always pick the aperture mode before marking variables.** This is part of the optical-physics setup, not a separate concern. The `SystemData.Aperture.ApertureType` enum (full reference in `sequential-design.md` § "ApertureType enum reference") controls **what is pinned and what floats during ray tracing** — and therefore what the optimizer is allowed to silently change. Picking the wrong mode is one of the most common "the optimizer ran but the design doesn't fit my hardware" failures: `RSCE` / `MTFA` look great in the report, but the build doesn't match the model.

### The trap

The default mode is `EntrancePupilDiameter`: EPD is pinned to `ApertureValue`, **the stop semi-diameter is recomputed every cycle** to keep EPD constant. As lens powers and spacings change during optimization, the stop silently grows (or shrinks). Common failure: your stop surface is a 12.5 mm physical iris, but optimization grew it to 18 mm. Spot diagrams look beautiful — for a system that won't fit your mount.

Any aperture mode that floats the stop (`EntrancePupilDiameter`, `ImageSpaceFNum`, `ObjectSpaceNA`, `ParaxialWorkingFNum`, `ObjectConeAngle`) has this property. Only **`FloatByStopSize`** pins the stop and lets EPD float instead.

### Decision tree

| Physical situation | Pick |
|---|---|
| Input beam is collimated and X mm wide (most laser benches) | `EntrancePupilDiameter` with `ApertureValue = X` |
| Spec is "lens at f/N to a sensor" (camera-style) | `ImageSpaceFNum` |
| Spec is "collect from a fiber / point source at NA" | `ObjectSpaceNA` or `ObjectConeAngle` |
| Stop is a physical iris / pixel / fiber core you don't want to outgrow | `FloatByStopSize` (and set the stop's `SemiDiameter` to the iris size) |
| Stop is virtual, you'll size mounts around the optimized result | `EntrancePupilDiameter` (default — let Zemax pick the stop) |

```python
# Bench-is-the-truth pattern: physical iris as the aperture-defining surface
SD = TheSystem.SystemData
SD.Aperture.ApertureType = ZOSAPI.SystemData.ZemaxApertureType.FloatByStopSize
stop = TheSystem.LDE.GetSurfaceAt(stop_surf_num)
stop.SemiDiameter = 12.5            # physical iris radius (lens units)
# Now the optimizer cannot grow the stop past 12.5 mm, regardless of lens powers.
# EPD becomes a *result* — read it after the trace via SD.Aperture.CurrentAperture
```

### Constraining downstream lens diameters too

`FloatByStopSize` pins only the stop. **For non-stop surfaces** (your downstream lenses, also bolted into mounts), use one of:

1. **`MNCA` / `MXCA` boundary operands** in the merit function — min/max clear aperture (= ray-traced semi-diameter) on a surface range. The wizard can add these for you (see "Optimization Wizard" above) or add them manually:
   ```python
   op = MFE.AddOperand()
   op.ChangeType(ZOSAPI.Editors.MFE.MeritOperandType.MXCA)
   op.GetCellAt(2).IntegerValue = 3        # surface from
   op.GetCellAt(3).IntegerValue = 7        # surface to
   op.Target = 12.7                         # max clear aperture (radius, lens units)
   op.Weight = 10.0
   ```

2. **`Fixed` solve on `SemiDiameterCell`** — hard pin a specific surface's semi-diameter. Use sparingly; it can cause failed ray traces if the optimizer needs to push rays past the limit:
   ```python
   surf.SemiDiameterCell.MakeSolveFixed()   # was Automatic by default
   surf.SemiDiameter = 12.7
   ```

`MechanicalSemiDiameter` (the physical lens-edge diameter, distinct from the optical clear aperture) is informational — it does not constrain the trace, but tolerancing and CAD-export tools use it.

### Field type interaction

Aperture mode interacts with `SD.Fields.SetFieldType`:
- `Angle` field type assumes the entrance pupil defines the aperture — pairs with `EntrancePupilDiameter` for camera-lens optimization.
- `ObjectHeight` assumes a finite object plane — pairs with `ObjectSpaceNA` / `ObjectConeAngle` for relay optimization.
- Combinations like `ObjectHeight + FloatByStopSize` mean both ends are pinned and only lens powers / spacings can move — common for finite-conjugate relays where the source and stop are both physical.

Mismatches don't error, but they make the optimizer's job harder than it needs to be.

## Refocus during merit-function evaluation

**The optimizer does NOT auto-refocus during MF computation.** This is the most-asked, least-documented question about Zemax optimization, and the source of "the optimizer ran but my spot is huge" complaints. Spot-radius operands (`RSCE` / `RSCH`), MTF operands, and wavefront operands all evaluate at **whatever image-surface position currently exists** — there's no implicit "find best focus, then evaluate MF" loop. If the image plane is in the wrong place, every operand reports degraded values, the optimizer chases lens-shape changes that compensate, and you get a strange-looking solution.

You have to set up refocus yourself. Three idiomatic strategies (sequential mode):

| Strategy | API | What it costs | What you get |
|---|---|---|---|
| **(1) Mark the last thickness as Variable** | `surf_before_image.ThicknessCell.MakeSolveVariable()` | One extra DOF for DLS to vary | True best focus per the merit function. The optimizer finds the BFL that minimizes whatever you're minimizing (RMS spot, MTF, wavefront) jointly with the lens shapes. **Default for almost every imaging-lens design.** |
| **(2) Marginal Ray Height solve on the last thickness** | `surf.ThicknessCell.CreateSolveType(SolveType.MarginalRayHeight)` with `_S_MarginalRayHeight.Height = 0.0` (default) and `PupilZone = 0.0` (default → paraxial) | None — no DOF added | Image plane *continuously* sits at the **paraxial focus**. Optimizer doesn't have to find it. **Limitation: paraxial only**, primary wavelength only — for highly aberrated systems the paraxial focus is not the best image plane. Set `PupilZone` to a non-zero value (e.g. 0.7) to use a real marginal ray instead. |
| **(3) OPD solve on the last thickness** | `surf.ThicknessCell.CreateSolveType(SolveType.OpticalPathDifference)` with the OPD target (in waves) and pupil zone | None | Image plane sits where OPD = target at the specified pupil zone. The classic "OPD=0 at pupil edge" pin gives the best on-axis wavefront focus. **Primary wavelength only, on-axis only.** |
| **(4) Run QuickFocus before optimization** | `Tools.OpenQuickFocus()` → `RunAndWaitForCompletion()` | A few seconds at script start | Starts you at a sensible focus *position* before MF evaluation begins; doesn't refocus during optimization. Most useful as **prep** when combined with strategy (1) — gives DLS a good initial guess so it converges faster. |

**The standard pattern** for a fresh imaging-lens optimization is (1) + (4): QuickFocus first to seed, then mark the last thickness Variable so the optimizer can refine. Don't use (2) or (3) for an aberration-dominated design — they pin you at the wrong focus and the MF will report falsely-bad numbers that the optimizer then chases.

```python
# Standard sequential-imaging-lens setup, with refocus handled by strategy (1) + (4):
img = TheSystem.LDE.GetSurfaceAt(TheSystem.LDE.NumberOfSurfaces)   # image surface
last_air = TheSystem.LDE.GetSurfaceAt(img.SurfaceNumber - 1)        # surface BEFORE image

# (4) Pre-focus to a sensible starting BFL
qf = TheSystem.Tools.OpenQuickFocus()
qf.Criterion = ZOSAPI.Tools.General.QuickFocusCriterion.SpotSizeRadial
qf.UseCentroid = True
qf.RunAndWaitForCompletion(); qf.Close()

# (1) Make the last air gap variable so optimization refines focus along with shapes
last_air.ThicknessCell.MakeSolveVariable()

# Now mark lens radii / spacings variable, build MF, run optimization — DLS will move
# the image plane along with everything else, finding true best focus per the MF.
```

### Reference point (Centroid vs Chief Ray) is orthogonal to refocus

The Optimization Wizard's "Reference" setting (`ReferTo = Centroid` vs `ChiefRay`) and the spot-operand variants (`RSCE` vs `RSCH`) control **what each ray's distance is measured from in the image plane** — not where the image plane is. Centroid reference is generally superior (most diffraction-based metrics improve when RMS-to-centroid drops); chief-ray reference is useful when chief-ray landing position itself is a constraint (sensor pixel, fiber tip). Picking the wrong reference will not move the focus — it just changes what RMS gets reported.

### NSC and refocus

NSC has no "image surface" concept — detectors are explicit objects at fixed Z positions. To refocus an NSC system, mark the detector's `ZPositionCell` as Variable (see "NSC variables" section above). The merit function still evaluates at the detector's current Z, so the same logic applies: if Z isn't variable, the optimizer can't find best focus.

### Common refocus-related failure modes

| Symptom | Likely cause |
|---|---|
| MF very high; spot ~ EFL/200; few cycles improve nothing | Last thickness not variable; optimizer is stuck at whatever BFL the file shipped with |
| MF improves slightly; spot still bad on real ray fan | Marginal Ray Height solve pinning paraxial focus on a highly-aberrated system. Switch to strategy (1). |
| Optimization "succeeds" but image-plane intensity drops to nothing in POP / Image Simulation | Optimizer found a local-min focus very far from the geometric image plane — POP's beam grid ran out of extent. Re-seed with QuickFocus and constrain the BFL with a min/max via `MNCA`/`MXCA`-style operands on a position dummy. |
| Spot looks great on-axis but defocused on field | Field-curvature problem, not refocus. Add `FCGT`/`FCGS` operands to constrain field curvature, or use the wizard's distortion/FC operands. |

## Local Optimization (DLS / Orthogonal Descent)

```python
opt = TheSystem.Tools.OpenLocalOptimization()
opt.Algorithm = ZOSAPI.Tools.Optimization.OptimizationAlgorithm.DampedLeastSquares  # or .OrthogonalDescent
opt.Cycles = ZOSAPI.Tools.Optimization.OptimizationCycles.Automatic                  # or Fixed_1_Cycle, Fixed_5_Cycles, Fixed_10_Cycles, ...
opt.NumberOfCores = 8
opt.RunAndWaitForCompletion()
mf_initial = opt.InitialMeritFunction
mf_final = opt.CurrentMeritFunction
opt.Close()
```

`Automatic` cycles runs until the MF improvement falls below an internal threshold. `DampedLeastSquares` is the default; `OrthogonalDescent` is more robust for stiff problems but slower per cycle.

### Smoke-test the merit function before a long run

Every `Tools.Open*` returns an `ISystemTool`, which exposes **`RunAndWaitWithTimeout(double timeOutSeconds)`** in addition to `RunAndWaitForCompletion()`. The timeout variant returns a `RunStatus` (`Completed` / `TimedOut` / `FailedToStart` / `InvalidTimeout`) and lets you bail early — perfect for a "did the MF actually evaluate, and is it dropping?" sanity check before committing to Hammer or a multi-hour Global. The optimizer keeps any improvement found before the timeout fires, so the test isn't wasted work.

```python
opt = TheSystem.Tools.OpenLocalOptimization()
opt.Algorithm = ZOSAPI.Tools.Optimization.OptimizationAlgorithm.DampedLeastSquares
opt.NumberOfCores = 8
opt.Cycles = ZOSAPI.Tools.Optimization.OptimizationCycles.Fixed_1_Cycle   # one cycle, then stop

mf_initial = opt.InitialMeritFunction
status = opt.RunAndWaitWithTimeout(30.0)                                  # seconds — hard ceiling
mf_after = opt.CurrentMeritFunction
opt.Close()

print(f"status={status} | MF: {mf_initial:.6g} -> {mf_after:.6g} | drop={mf_initial-mf_after:.6g}")
# Expect: status == RunStatus.Completed AND a finite, positive MF that dropped.
# Red flags:
#   - mf_initial == 0 or 1e10            -> MFE has no operands, or all weights zero
#   - mf_initial == mf_after exactly     -> no variables marked, optimizer is a no-op
#   - status == TimedOut at 30s/1 cycle  -> evaluation is pathologically slow (POP/Huygens in the MF, etc.)
#   - status == FailedToStart            -> tool rejected the configuration; check IsValid + ErrorMessage
```

What this catches *before* you launch a long run:
- **No variables marked.** `mf_initial == mf_after`, status `Completed`. Optimizer ran and did nothing because there's no DOF to vary. Check `zemax_get_variables` / scan the LDE/NCE for any cell with a Variable solve.
- **MF is empty or trivial.** `InitialMeritFunction == 0` or absurd (1e10). The wizard didn't run, or every operand has weight 0. `MFE.CalculateMeritFunction()` standalone (no optimizer) confirms.
- **MF doesn't actually depend on the variables.** `mf_initial == mf_after`, even though variables are marked. Common cause: operand surface numbers point at the wrong surface, or the variable is a "decoupled" parameter the MF never reads. Walk each operand's cells and check.
- **MF is dropping but barely** (5e-4 → 4.99e-4 over 1 cycle). Local will converge slowly but it'll get there; whether to launch a long Global depends on whether you trust the MF formulation. Often a sign that the wizard's auto-weights are wrong for your problem — adjust `OverallWeight` on glass/air boundary operands or add explicit constraint operands before paying for global.
- **Pathological per-cycle cost.** Timeout at 30s on a single cycle of local means each MF evaluation is slow (typically: POP, Huygens PSF, or NSC raytrace operands in the MF). Reduce sampling on those operands, or accept that Global will be very expensive.

The same `RunAndWaitWithTimeout(seconds)` works on `OpenGlobalOptimization`, `OpenHammerOptimization`, `OpenTolerancing`, `OpenLocalOptimization_HPC`, `OpenNSCRayTrace`, etc. — anything with `Tools.Open*`. For Global and Hammer it's the *only* sane way to run them (they have no natural stopping condition); for Local it's the smoke-test pattern above.

## Global Optimization

```python
gopt = TheSystem.Tools.OpenGlobalOptimization()
gopt.NumberToSave = 10
gopt.NumberOfCores = 8
gopt.RunAndWaitWithTimeout(60)        # seconds — global runs until you stop it
gopt.Cancel(); gopt.WaitForCompletion(); gopt.Close()
```

Global produces multiple distinct local minima. Read out via `gopt.GetGlobalSolution(i)` (i = 1..NumberToSave) and `gopt.MakeCurrent(i)` to load one back into the system.

## Hammer Optimization

Hammer is a basin-hopping continuous optimizer — keeps perturbing and re-running local until you stop it.

```python
hopt = TheSystem.Tools.OpenHammerOptimization()
hopt.RunAndWaitWithTimeout(10)        # seconds
hopt.Cancel()
hopt.WaitForCompletion()
hopt.Close()
```

## QuickFocus

Auto-focus the image plane to minimize a chosen criterion. Doesn't require a merit function.

```python
qf = TheSystem.Tools.OpenQuickFocus()
qf.Criterion = ZOSAPI.Tools.General.QuickFocusCriterion.SpotSizeRadial   # also SpotSizeXOnly, SpotSizeYOnly, Wavefront
qf.UseCentroid = True
qf.RunAndWaitForCompletion()
qf.Close()
```

## Scale Lens

Convert system units, or scale all dimensions by a factor.

```python
scale = TheSystem.Tools.OpenScale()
scale.ScaleByUnits = True
scale.ScaleToUnit = 2                  # 0=mm, 1=cm, 2=in, 3=m
# OR:
scale.ScaleByUnits = False
scale.ScaleFactor = 2.5
scale.RunAndWaitForCompletion()
scale.Close()
```

## Convert to Non-Sequential Group

Embed a sequential design as an NSC sub-group (useful for adding non-sequential elements around a sequential lens).

```python
conv = TheSystem.Tools.OpenConvertToNSCGroup()
conv.ConvertFileToNSC = True
conv.RunAndWaitForCompletion()
conv.Close()
```

## Tolerancing

Two-step pattern: configure the Tolerance Wizard (TDE), then run the Tolerancing tool.

```python
# 1) Wizard sets up tolerances on every surface/element
tWiz = TheSystem.TDE.SEQToleranceWizard
tWiz.SurfaceRadius = 0.1               # mm
tWiz.SurfaceThickness = 0.1
tWiz.SurfaceDecenterX = 0.1
tWiz.SurfaceDecenterY = 0.1
tWiz.SurfaceTiltX = 0.2                # mrad
tWiz.SurfaceTiltY = 0.2
tWiz.ElementDecenterX = 0.1
tWiz.ElementDecenterY = 0.1
tWiz.ElementTiltXDegrees = 0.2
tWiz.ElementTiltYDegrees = 0.2
tWiz.IsSurfaceSandAIrregularityUsed = False
tWiz.IsIndexUsed = False
tWiz.IsIndexAbbePercentageUsed = False
tWiz.OK()                              # apply

# 2) Run the tool
TolModes = ZOSAPI.Tools.Tolerancing
tol = TheSystem.Tools.OpenTolerancing()
tol.SetupMode = TolModes.SetupModes.Sensitivity   # also MonteCarlo, Inverse
tol.Criterion = TolModes.Criterions.RMSSpotRadius
tol.CriterionSampling = 3
tol.CriterionComp = TolModes.CriterionComps.OptimizeAll_DLS
tol.CriterionCycle = 2
tol.CriterionField = TolModes.CriterionFields.UserDefined
tol.NumberOfRuns = 20
tol.NumberToSave = 20
tol.RunAndWaitForCompletion()
# read tol.MeanCriterion, tol.MinCriterion, tol.MaxCriterion, tol.WorstOffenders, ...
tol.Close()
```

The `WorstOffenders` collection (when populated) tells you which tolerances dominate the criterion variance — the most actionable output for tightening a real spec.

## Other system tools

`TheSystem.Tools.Open*` exposes many more tools beyond the optimization/scaling ones above. They all follow the same lifecycle (`Open → configure → RunAndWaitForCompletion → Close`). Run `scripts/probe_object_properties.py` against any one to dump its typed properties. The most useful by category:

**Lens fine-tuning / asphere work:**
- `OpenQuickAdjust` — vary one parameter (radius or thickness) on selected surfaces to minimize a criterion (similar to QuickFocus but operates on any surface). Typed properties: `AdjustType` (Radius/Thickness), `Criterion` (QuickAdjustCriterion: SpotSizeRadial/X/Y, AngularRadial/X/Y), `UseCentroid`, `StartSurface`, `EndSurface`.
- `OpenFindBestAsphere` — iteratively fit an aspheric profile to a target surface.
- `OpenConvertAsphereTypes` — convert between EvenAspheric / OddAsphere / Extended / etc. types.

**Sensitivity / quick analyses (without a full Tolerancing run):**
- `OpenQuickSensitivity` — quick first-pass sensitivity vs. each tolerance.
- `OpenMeritFunctionCalculator` — evaluate the current merit function without running optimization.
- `OpenComputeRMSSpotSize` / `OpenRMSSpotRadiusCalculator` — direct RMS spot computation (faster than New_StandardSpot when you just need a number).
- `OpenToleranceDataViewer` — load + browse a saved tolerance result.

**Catalogs (see `system-and-application.md` for the full lens-catalog example):**
- `OpenLensCatalogs` — search stock-lens catalogs (Edmund, Thorlabs, ...) by EFL/EPD/element count/shape.
- `OpenMaterialsCatalog` — search glass catalogs.

**File / project management:**
- `OpenCreateZAR` — create a Zemax archive (`.ZAR`) bundling lens + glass catalogs + coatings + image data.
- `OpenRestoreZAR` — restore a `.ZAR` archive.
- `OpenCreateProject` / `OpenRestoreProject` — Zemax project files (different from ZAR; bundles the editor states).
- `OpenFileManager` — file management operations.
- `OpenDesignLockdown` — protect a design from edits.

**Export:**
- `OpenExportCAD` — export to STEP / IGES / SAT / STL / OBJ / ... (CADFileType enum has 20+ formats).
- `OpenShadedModelVisualizationExport` — export the 3D rendering.
- `OpenExportToSpeosLensSystem` / `OpenExportToSpeosWhitebox` — Ansys Speos handoff.

**Stray light (NSC):**
- `OpenLightningTrace` — fast NSC trace optimized for stray light.
- `OpenCriticalRaysetGenerator` — identify critical rays from a source.

**Ray aiming:**
- `OpenRayAimingWizard` — auto-configure ray aiming for systems with vignetting or extreme apertures.

**HPC variants:** Many compute-heavy tools have `_HPC` siblings (`OpenLocalOptimization_HPC`, `OpenGlobalOptimization_HPC`, `OpenHammerOptimization_HPC`, `OpenTolerancing_HPC`, `OpenNSCRayTrace_HPC`) that distribute across additional cores when an HPC license is present. Same API shape; the `_HPC` tools expose an `IHPCSettings` sub-object for cluster configuration:
- `HPCEnvironments` enum: `OnPremise`, `AWSKubernetes`, `AzureKubernetes`
- `HPCNodeSize` enum: `Default`, `Tiny`, `Small`, `Medium`, `Large`, `XLarge`
- `HPCRunState` enum (read during a run): `NotRunning`, `Initializing`, `ClusterAllocating`, `UploadingData`, `Queued`, `RunStarting`, `WaitingForResults`, `Complete`

Check `TheApplication.IsValidLicenseForAPI` and the HPC license bit before using.

## ZOSAPI.Tools sub-namespaces

If you're hunting for an interface or enum and don't find it where you expect, the `ZOSAPI.Tools` namespace is divided into sub-namespaces:

| Sub-namespace | What lives there |
|--------------|------------------|
| `ZOSAPI.Tools.General` | Most `Tools.Open*` interfaces (LensCatalogs, MaterialsCatalog, QuickFocus, QuickAdjust, Scale, ExportCAD, CreateZAR, ...), QuickFocusCriterion, ScaleToUnits, CADFileType, LensShape, LensType enums |
| `ZOSAPI.Tools.Optimization` | `OptimizationAlgorithm` (DampedLeastSquares, OrthogonalDescent), `OptimizationCycles` (Automatic, Fixed_*), `IGlobalOptimization`, `IHammerOptimization`, `ILocalOptimization` |
| `ZOSAPI.Tools.OptimizationTools` | Helper utilities for optimization tools |
| `ZOSAPI.Tools.RayTrace` | `RaysType` (Real/Paraxial), `OPDMode`, the four `IBatchRayTrace*` data interfaces (NormPol, NormUnpol, DirectPol, DirectUnpol), `IRayDatabaseReader` |
| `ZOSAPI.Tools.Tolerancing` | `SetupModes` (Sensitivity, MonteCarlo, Inverse), `Criterions` (RMSSpotRadius, ...), `CriterionComps`, `CriterionFields`, `ITolerancing` |
| `ZOSAPI.Tools.Layouts` | Programmatic layout drawings (1D/2D/3D), separate from `TheSystem.Analyses.New_Analysis(AnalysisIDM.NSC3DLayout)` |
| `ZOSAPI.Tools.FileManager` | File management operations |

Plus the top-level `ZOSAPI.Tools` itself defines `RunStatus`, `IHPCSettings`, `RayPatternOption`, `CriticalRayType`, `MaterialFormulas` (Schott, Sellmeier1-5, Herzberger, Conrady, Handbook1/2, Extended/2/3), `MaterialStatuses` (Standard, Preferred, Obsolete, Special, Melt), `IMaterialsCatalog`, and the base `ISystemTool`.

The `IInternalBirefringenceData` / `IInternalTransmissionData` interfaces (also in `ZOSAPI.Tools`) are the structured way to extract material absorption/birefringence data — useful for systems with thick crystals or filters.

When in doubt about a tool's properties, the probe script's `TOOL_TYPES` list includes most of these — add the one you need and rerun.

## Pattern: optimization-then-analyze

Most workflows look like:
1. Build the system (LDE/NCE) — see `sequential-design.md` or `nsc-objects.md`
2. Mark variables on the cells you want the optimizer to vary
3. Build the merit function (this file)
4. Run a local optimization (this file)
5. Read out spot/MTF/wavefront with `New_Analysis(...)` (see `analyses.md`)
6. If the result is unsatisfactory, add boundary operands or run Hammer/Global
