# NSC Illumination / Non-Imaging Design (sources → far-field)

Recipes for **non-imaging** NSC design — collimators, concentrators, light pipes —
where the goal is an energy distribution (spatial or angular) on a detector, not
an image. This file is the workflow layer; it leans on three others:

- **Object vocabulary** (lens/asphere/CPC bodies, `DetectorPolar`, `SourceRadial`):
  `nsc-objects.md` § "Freeform / asphere / illumination objects" — all names there
  are probe-verified.
- **The optimization engine** (`NSCOptimizationWizard`, NSDD/NSTR/NSDP operands,
  NSC variables): `optimization.md`.
- **Placement/grouping** (RefObject, Null-Object parents): `conventions.md`.

## When NSC, not sequential

Use NSC (not the sequential LDE) when the source is extended/Lambertian, when TIR
or multiple ray paths matter, or when the optics are faceted/freeform. TIR and
refraction are automatic in NSC; ray splitting is off by default and only needed
to account for Fresnel/ghost losses (and then requires polarization ray tracing).
See `nsc-objects.md` for the TIR/ray-splitting details.

## Sources: modeling a Lambertian LED

Use `SourceRadial` (`nsc-objects.md`) — it carries an arbitrary radial
intensity-vs-angle profile, which is how you build a Lambertian (cosine) or any
measured LED distribution. Set the angular extent with `MinAngle`/`MaxAngle`, the
emitting-area half-widths (`XHalfWidth`/`YHalfWidth`) for étendue, and the profile
itself via `SetSubAngleI(i, value)` across `NumberOfPoints`. Set
`NumberOfAnalysisRays` high (1e6+): angular merit metrics are ray-statistical and
noisy at low ray counts.

```python
OT = ZOSAPI.Editors.NCE.ObjectType
src = NCE.GetObjectAt(1)
src.ChangeType(src.GetObjectTypeSettings(OT.SourceRadial))
sd = src.get_ObjectData().__implementation__
sd.NumberOfAnalysisRays = 2_000_000
sd.Power = 1.0
sd.MinAngle = 0.0; sd.MaxAngle = 90.0          # Lambertian fills the hemisphere
# Build a cosine falloff across the profile points (SetSubAngleI is the intensity
# table; confirm the exact value convention against the GUI before trusting shape).
for i in range(sd.NumberOfPoints):
    pass                                        # set sd.SetSubAngleI(i, cos-weighted value)
```

## Detectors: spatial vs angular

A collimator is judged in **angle space**, so use `DetectorPolar` (`nsc-objects.md`),
which bins flux purely by ray angle. Set `MaxAngle` a bit beyond the spec cone (so
you can see the tail) and choose `NumberPPixels` so a pixel boundary lands on the
spec edge. For a ±12° spec: `MaxAngle = 24`, `NumberPPixels = 121` → 0.2°/pixel, so
θ = 12° falls on pixel ~60.

A `DetectorRectangle` can also report angle-space data, but `DetectorPolar` is the
clean tool for energy-in-cone vs polar angle.

## Collimation merit — the key point

The NSC wizard's *default* targets a **spatial** detector criterion (irradiance
uniformity / max / total flux). **That does not measure collimation.** Two ways to
express an angular target:

**Route A — angular criterion via the NSC wizard.** The wizard's criterion list is
detector-dependent; on a `DetectorPolar` it includes angular metrics (RMS Angular
Radius/X/Y, Angular Uniformity, Angular centroids). Target **RMS Angular Radius →
0**. Always set a minimum-flux floor so the optimizer can't "win" by dumping light
off the detector. The `Criterion` value is an integer index whose meaning depends
on the detector type — **discover it at runtime, don't hard-code** (see
`optimization.md` for the wizard's full property set and the NSDD/NSTR/NSDP
machinery it generates).

```python
nwiz = TheSystem.MFE.NSCOptimizationWizard
nwiz.UseSource   = 0                          # all sources
nwiz.UseDetector = POLAR_DET_OBJ             # the DetectorPolar object number
# Find the index that maps to "RMS Angular Radius" for THIS detector type:
for i in range(nwiz.NumberOfCriterion):
    print(i, nwiz.GetCriterionAt(i))
nwiz.Criterion   = ANGULAR_RMS_IDX           # set from the printout above
nwiz.IsMinimumFluxUsed = True
nwiz.MinimumFlux = 0.9 * SOURCE_FLUX         # keep light on the detector
nwiz.IsSplitRaysUsed = False                 # TIR still works with splitting off
nwiz.IsClearDataSettingsUsed = True
nwiz.IsRaytraceSettingsUsed  = True
nwiz.Apply()
TheSystem.UpdateStatus()
```

**Route B — hand-built energy-in-cone** (full control of "fraction within ±12°").
Same three-part structure the wizard generates (`optimization.md`): one
`NSDD … Det#=0` to clear all detectors, an `NSTR` to trace the source(s), then
**`NSDP`** readouts on the polar detector. Sum NSDP over the inner θ ≤ 12° pixels
for flux-in-cone, sum all pixels (Pix# = 0) for total, and ratio them with
`DIVI`/`OPGT`/`OPLT`; drive the ratio → 1 (or constrain flux **outside** the cone
→ 0).

`[PROBE-VERIFY]` NSDP's exact cell-argument order and which Data# codes it honors:
the CHM says it is "similar to NSDD" but does not reprint NSDP's own table. Read
`MeritOperandType.NSDP` in the live MFE (or `chmseek_zos.py search "NSDP"`) before
relying on a specific cell layout.

## Variables for collimator optimization

NSC has no thickness cells — vary the lens/collar **ParN/typed cells** and object
poses (see `optimization.md` § "NSC variables"): the asphere `RadiusN`/`ConicN`/
`CoeffNOnRPowerM` cells, the collar's `Min/MaxFrontAperture` (the radius dividing
"lens rays" from "TIR rays"), and element `ZPositionCell` for axial spacing. Keep
the LED and detector fixed. Mark a cell variable with
`obj.SomethingCell.MakeSolveVariable()` or
`obj.GetObjectCell(ZOSAPI.Editors.NCE.ObjectColumn.ParN).MakeSolveVariable()`.

Smoke-test the merit function with a short `RunAndWaitWithTimeout` before a long
run (`optimization.md`), and re-check `TheSystem.UpdateStatus()` afterward —
statistical merit functions plus overlapping NSC objects are an easy way to get a
silently-broken system.

## Worked recipe: two-element TIR collimator (Lambertian LED → ±12°)

A classic LED collimator = a central refractive lens over the near-axis cone + an
outer TIR collar over the wide-angle rays (often one molded part; modeled as two
coaxial NSC objects).

1. **Source** — `SourceRadial`, Lambertian profile, at the origin emitting +Z
   (above).
2. **Central lens** — `EvenAsphereLens` over the near-axis cone (≈ ≤ ±35°);
   collimates the rays that hit it by refraction.
3. **Outer collar** — `AnnularAsphericLens` (or `CPC`) as a solid dielectric;
   wide rays enter the inner wall, **TIR off the outer wall** (automatic), exit
   collimated. The collar's `MinFrontAperture` sets the lens↔collar transition.
4. **Detector** — `DetectorPolar` downstream on-axis, `MaxAngle ≈ 24`, facing −Z.
5. **Group** the lens + collar under a Null-Object parent so they move as one unit
   (`conventions.md`).
6. **Variables** — asphere coeffs/radii/conics on both elements, the collar
   transition radius, axial spacings (above).
7. **Merit** — Route A (RMS Angular Radius on the polar detector + MinimumFlux),
   optionally plus a Route-B hand constraint that flux outside ±12° → 0.
8. **Optimize** — `OpenLocalOptimization` (`optimization.md`); smoke-test first.
9. **Read result** — NSDP energy in the θ ≤ 12° pixels ÷ total = fraction collimated.
