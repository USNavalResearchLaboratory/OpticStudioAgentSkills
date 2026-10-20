# Physical Optics Propagation (POP)

POP is OpticStudio's diffraction-based beam propagator. It carries a sampled complex E-field through sequential surfaces using Fresnel / angular-spectrum integrals — not rays. Use it when ray tracing is the wrong answer: laser-beam waist evolution, near-field diffraction, single-mode fiber coupling, spatial-filter design, anywhere the beam's wave nature matters.

POP is sequential-only. For non-sequential coherent E-field work, see `data-extraction.md` (`GetAllCoherentDataSafe`) — that's a different paradigm and has the Ex-only limitation.

## When to use POP vs the alternatives

| Question | Use |
|---|---|
| "Where does the geometric image plane focus?" "What's the RMS spot at field 3?" | Ray tracing (`StandardSpot`, `FftMtf`, ...) |
| "How does my Gaussian beam waist evolve through this telescope?" "What's the spot at the image plane after a real lens stack?" | **POP** |
| "What fraction of my beam couples into a single-mode fiber?" | **POP** with `ComputeFiberCouplingIntegral=True` |
| "How does a spatial filter clean my beam?" | **POP** (the pinhole's diffraction is the whole point) |
| "What's the diffraction pattern at the focus?" (Airy, near-field rings, etc.) | **POP** or `FftPsf` (POP if you also need post-focus propagation) |
| "Two beams interfere on a target plane — what's the fringe pattern?" | NSC coherent extraction (Ex only — see `data-extraction.md`) **OR** POP if you can model both arms in sequential |
| "What's the irradiance map a few mm before/after focus?" | **POP** |

POP is slower than ray tracing — N² scaling in the sampling — and it requires knowing your beam parameters (waist or angle), not just the entrance pupil. Use it deliberately, not as a default.

## Settings interface

POP lives in its own analysis sub-namespace: **`ZOSAPI.Analysis.PhysicalOptics.IAS_PhysicalOpticsPropagation`**, but `pop.GetSettings()` returns the generic `IAS_` interface. **You must cast via `.__implementation__`** to see `BeamType`, `EndSurface`, etc. — without the cast they look like Python attribute writes that succeed silently and don't reach Zemax. This is the same pattern as NCE objects (see `pythonnet-gotchas.md`):

```python
pop = TheSystem.Analyses.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.PhysicalOpticsPropagation)
s = pop.GetSettings().__implementation__   # REQUIRED for POP-specific properties
print(dir(s))
```

Confirmed properties on `IAS_PhysicalOpticsPropagation`:

| Property / method | Purpose |
|---|---|
| `BeamType` | Beam definition: Gaussian Waist / Gaussian Angle / Gaussian Size+Angle / Top Hat / file-based ZBF |
| `BeamTypeFilename` | When `BeamType` is file-based, the `.ZBF` source file (must be in `TheApplication.POPDir`) |
| `GetParameterName(i)` / `GetParameterValue(i)` / `NumberOfParameters` | Beam-type-specific parameters (waist, divergence, M², etc.) — varies by `BeamType` |
| `StartSurface` / `EndSurface` | **Both are `IAS_Surface` selectors — assign with `s.StartSurface.SetSurfaceNumber(N)` / `s.EndSurface.SetSurfaceNumber(N)`, NOT `= N`** (which silently no-ops or rebinds the attribute). `StartSurface` defaults to 1 but can be moved later in the system — useful for skipping past POP-incompatible surfaces (BlackBoxLens, certain UserDefinedSurface DLLs); see "Propagating POP past unsupported surfaces" below. |
| `Field` / `Wavelength` | Same selector pattern: `s.Field.SetFieldNumber(N)`, `s.Wavelength.SetWavelengthNumber(N)` |
| `DataType` | `POPDataTypes` enum exposes only `Irradiance`, `EXIrradiance`, `EYIrradiance`, `Phase`, `EXPhase`, `EYPhase`. **There are NO `Real_X` / `Imaginary_X` options** — to recover the complex E-field, run POP twice (once for `EXIrradiance`, once for `EXPhase`) and reconstruct as `√(irradiance) · exp(i·phase)` (same for Y). |
| `LogScale`, `PlotScale`, `ContourFormat`, `RowOrColumn` | Plot styling |
| `AutoCalculateBeamSampling()` | Auto-pick X/Y sampling and array width based on the configured beam — **call this before Apply()** unless you know what you're doing |
| `ComputeFiberCouplingIntegral` (bool) | Enable fiber coupling efficiency calculation |
| `FiberType`, `FiberTypeFilename`, `FiberPosition`, `IgnoreFiberPolarization` | Receiver fiber properties |
| `GetFiberParameterValue(i)` / `NumberOfFiberParameters` | Fiber-type-specific params (mode-field diameter, NA, etc.) |
| `GetBeamTypeFiles()` / `GetFiberTypeFiles()` | List `.ZBF` and `.DLL` files available in `POPDir` |
| `OutputBeamFile` (str) | Path to write the propagated complex E-field as a `.ZBF` (must be in `POPDir`) |
| `SaveOutputBeam` (bool) | Enable `.ZBF` write at the end surface |
| `SaveBeamAtAllSurfaces` (bool) | Write `.ZBF` at every surface (one file per surface) — useful for diagnosing where the beam goes wrong |
| `PeakIrradiance` (read after Apply) | Output: peak irradiance in the array |
| `ReadPowerFromFile()` | Pull total power from a saved beam file |
| `Project` | Projection method (Equal-area, etc.) for off-axis fields |

Plus the inherited `Save()`, `LoadFrom(cfg)`, `ModifySettings(cfg, key, value)` from `IAS_` for the cfg fallback.

### Worked recipe: Gaussian beam through a lens stack

```python
AIDM = ZOSAPI.Analysis.AnalysisIDM
POPDT = ZOSAPI.Analysis.PhysicalOptics.POPDataTypes        # Irradiance/EXIrradiance/EYIrradiance/Phase/EXPhase/EYPhase
POPBT = ZOSAPI.Analysis.PhysicalOptics.POPBeamTypes        # confirm member names via probe

pop = TheSystem.Analyses.New_Analysis(AIDM.PhysicalOpticsPropagation)
s = pop.GetSettings().__implementation__                   # REQUIRED — see above

# 1) Define the beam (BeamType-specific parameters via GetParameterName/Value pairs)
s.BeamType = POPBT.GaussianWaist                           # confirm member via probe
# Set the waist parameter (index varies by beam type; first param is usually waist X):
# s._set_ParameterValue(0, 0.5)   # mm — see "Why GetParameterName" below

# 2) Where to propagate to and what to display
#    EndSurface / Field / Wavelength are IAS_Surface / IAS_Field / IAS_Wavelength
#    SELECTORS — assign via SetSurfaceNumber(N), NOT via "= N" (which silently no-ops)
s.EndSurface.SetSurfaceNumber(TheSystem.LDE.NumberOfSurfaces)   # image plane
s.Field.SetFieldNumber(1)
s.Wavelength.SetWavelengthNumber(1)
s.DataType = POPDT.Irradiance                              # or .EXIrradiance / .EXPhase / etc.

# 3) Let POP pick the sampling — this is the right default
s.AutoCalculateBeamSampling()

# 4) Optionally save the propagated complex E-field
import os
s.SaveOutputBeam = True
s.OutputBeamFile = os.path.join(TheApplication.POPDir, 'pop_at_image.ZBF')
# s.SaveBeamAtAllSurfaces = True       # one .ZBF per surface — for diagnosis

pop.ApplyAndWaitForCompletion()
peak = s.PeakIrradiance                # output value, populated after Apply
results = pop.GetResults()
grid = results.GetDataGrid(0)          # 2D irradiance/phase/E-component map
# convert to numpy with the standard reshape helper from boilerplate.md
pop.Close()
```

### Reconstructing the complex E-field

POP's `DataType` enum has no `Real_X / Imaginary_X / Real_Y / Imaginary_Y` — only `EXIrradiance`, `EXPhase` (and `EY*`). To get the complex E-field, run POP twice and reconstruct:

```python
import numpy as np

def get_pop_complex_E(pop_settings_impl, component='X'):
    """Run POP twice (irradiance + phase) and return the complex E_<component> grid."""
    POPDT = ZOSAPI.Analysis.PhysicalOptics.POPDataTypes
    irr_dt   = POPDT.EXIrradiance if component == 'X' else POPDT.EYIrradiance
    phase_dt = POPDT.EXPhase      if component == 'X' else POPDT.EYPhase

    pop_settings_impl.DataType = irr_dt
    # ... apply, extract grid ...
    irr = ...                                              # numpy 2D from GetDataGrid(0)

    pop_settings_impl.DataType = phase_dt
    # ... apply again, extract grid ...
    phase = ...                                            # numpy 2D from GetDataGrid(0); radians

    return np.sqrt(np.maximum(irr, 0)) * np.exp(1j * phase)
```

For full vector polarization analysis (Ex AND Ey), do this for both components — four POP runs in total. The runs are independent so they can share the same beam definition and only differ in `DataType`.

**Why `GetParameterName` / `GetParameterValue`:** the parameter slots have meaning only relative to the chosen `BeamType` — for Gaussian Waist they are (Waist X, Waist Y, Decenter X, Decenter Y, Aperture, ...); for Top Hat they are different. Always loop `for i in range(s.NumberOfParameters): print(s.GetParameterName(i), s.GetParameterValue(i))` to confirm what you're setting before assuming an index.

## What POP returns

After `ApplyAndWaitForCompletion`:
- `s.PeakIrradiance` — peak value in the result array (settings sub-object, post-Apply)
- `results.GetDataGrid(0).Values` — 2D `System.Double[,]` of the chosen `DataType` (Irradiance, Phase, E_x_real, E_x_imaginary, ...). Use the `reshape` helper from `boilerplate.md`. `grid.MinX/MinY/Dx/Dy/Nx/Ny` describe the sampling.
- For fiber coupling (`ComputeFiberCouplingIntegral=True`): the result text dump (`results.GetTextFile(...)`) includes system efficiency, receiver efficiency, and total fiber coupling. Or use the `POPD` operand (below) to read these directly.
- `OutputBeamFile` written (if `SaveOutputBeam=True`) — see next section.

## `.ZBF` files (Zemax Beam File)

POP can read and write its complex-E-field state as `.ZBF` files. These live in `TheApplication.POPDir` (POP rejects `OutputBeamFile` paths outside `POPDir` — same restriction as `ImagesDir` for image-export tools).

**Use cases:**
- **Chain POP runs.** Run POP through arms 1..N, save the output beam, then load it as the input beam for a downstream analysis. Set `BeamType` to the file variant and `BeamTypeFilename = '<saved>.ZBF'`.
- **Reuse a measured / externally generated beam.** If you have a measured wavefront or a beam from another tool, write it to a `.ZBF` (binary format documented in OpticStudio Help → "ZBF File Format") and load it as a custom source.
- **Inspect intermediate states.** `SaveBeamAtAllSurfaces = True` writes one `.ZBF` per surface — invaluable when the final result is wrong and you need to find which surface introduced the artifact.

The `.ZBF` binary format stores Nx, Ny, sampling, wavelength, and the complex E-field. OpticStudio Help has the byte-level layout if you need to parse one yourself; for normal use, just hand the path back to POP.

### ZBF binary layout (for synthesizing or parsing one)

When you need to build a `.ZBF` from numpy (e.g. to feed POP with a measured beam, a vendor-provided post-shaper field, or a synthesized top-hat), here is the byte-level format from the CHM:

```
4-byte int   version (= 1)
4-byte int   nx                              # samples in x
4-byte int   ny                              # samples in y
4-byte int   is_polarized (0 unpolarized, 1 polarized)
4-byte int   units (0=mm, 1=cm, 2=in, 3=m)
16 bytes     reserved (4 ints, any value)
8-byte dbl   dx                              # x spacing (lens units)
8-byte dbl   dy                              # y spacing
8-byte dbl   z_x, rayleigh_x, waist_x        # pilot beam in x (3 doubles)
8-byte dbl   z_y, rayleigh_y, waist_y        # pilot beam in y (3 doubles)
8-byte dbl   wavelength_in_medium            # in lens units (NOT µm)
8-byte dbl   index_of_refraction
8-byte dbl   receiver_efficiency             # 0 if no fiber coupling
8-byte dbl   system_efficiency               # 0 if no fiber coupling
64 bytes     reserved (8 doubles, any value)
2*nx*ny dbl  Ex values (interleaved real, imag, in row-major)
2*nx*ny dbl  Ey values (only if is_polarized=1)
```

`|Ex|² + |Ey|²` is in **watts** — the synthesized field must be power-normalized, not amplitude-normalized. The "pilot beam" doubles encode an internal Gaussian reference POP uses to track phase curvature; for a synthesized arbitrary beam, set them to sensible values matching your beam's nominal waist (e.g. for a 5 mm top-hat, `waist_x = waist_y = 2.5e-3` if units=meters; `z_x = z_y = 0` if at the waist).

## Propagating POP past unsupported surfaces (Black Box, GridSag, …)

Some sequential surface types **do not support POP**: `BlackBoxLens` (encrypted — POP cannot see per-surface data), Skew Gaussian sources, and a few user-defined-surface DLLs. The CHM is explicit: features requiring access to specific surface data "cannot reproduce the same results from a black box file as the original file." Naively running POP through such a surface returns garbage without raising an error.

The fix is the same in every case: **start POP at the surface immediately after the unsupported element, with a beam definition that matches what the element produces.** POP has both `StartSurface` and `EndSurface` selectors and treats the starting beam as the source — exactly the right tool for skipping over an opaque element.

### Standard pattern: vendor BB + built-in beam type at the post-BB plane

Most commercial BBs are beam-shapers or imaging assemblies whose **output beam is the whole point of the product** and is documented as a primitive shape (top-hat, Gaussian, fiber mode) with known dimensions. Vendors also typically ship a **playback ZMX** alongside the `.ZBB` — a complete working sequential system with the BB already wired at the correct distances. The flow:

```python
POP = ZOSAPI.Analysis.PhysicalOptics
BeamTypes = POP.POPBeamTypes

# 1. Load the vendor's playback ZMX (BB already at the right surface, distances baked in)
TheSystem.LoadFile(r'C:\path\vendor_playback.zmx', False)
#    e.g. for a refractive top-hat beam shaper: surface 0=OBJ, 1=STD dummy,
#         2=BlackBoxLens(*.ZBB), 3-4=STD spacing, 5=IMA. BB is at surface 2;
#         post-BB plane is surface 3.

# 2. (Optional) extend the system: insert your downstream optics AFTER the last surface
#    of the vendor playback, or convert surfaces 1..(n-2) to NSC via OpenConvertToNSCGroup
#    if your downstream bench is non-sequential. See sequential-design.md.

# 3. Run POP starting at the post-BB plane with the BB's documented output beam
pop = TheSystem.Analyses.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.PhysicalOpticsPropagation)
s = pop.GetSettings().__implementation__
s.StartSurface.SetSurfaceNumber(3)                # surface immediately after the BB
s.EndSurface.SetSurfaceNumber(TheSystem.LDE.NumberOfSurfaces)
s.Field.SetFieldNumber(1); s.Wavelength.SetWavelengthNumber(1)

# Built-in TopHat matches what most beam-shapers deliver. Set both widths to
# the vendor's documented output diameter.
s.BeamType = BeamTypes.TopHat
# Top-hat dimensions live in the beam-type parameters — discover via:
#   for i in range(s.NumberOfParameters): print(i, s.GetParameterName(i))
# (typically "Width X" and "Width Y" — set with s.SetParameterValue(i, value_in_lens_units))

s.AutoCalculateBeamSampling()
pop.ApplyAndWaitForCompletion()
```

**This is the right path for refractive top-hat beam shapers, including catalog parts like the Edmund TopHat.** The vendor's documented output (a flat-top of specified diameter) maps directly onto Zemax's built-in `BeamType = TopHat` — no synthesis needed. For Gaussian-output BBs (telescope, fiber-coupling assemblies), use `BeamType = GaussianWaist` instead, with the vendor's quoted post-BB waist.

### When the built-in beam types aren't good enough

Two cases where you need a `.ZBF` instead of the built-in primitives:

- **Vendor ships a measured or simulated field profile** alongside the BB (some shippers include a `.ZBF` or `.DAT` because the output beam has a non-primitive edge/phase profile). Drop the file into `TheApplication.POPDir`, then `s.BeamType = BeamTypes.File; s.BeamTypeFilename = 'vendor.ZBF'`.
- **You have a measured beam from camera/wavefront data** and want POP to propagate from there. Write the field to a `.ZBF` per the binary layout above and load the same way.

The ZBF binary format is documented above (40-byte header + Ex/Ey doubles). Writing one is ~30 lines of `struct.pack`; do this case-by-case rather than maintaining a synthesis helper — the right edge profile, sampling, and pilot-beam params depend on the specific source. **Do not write a super-Gaussian top-hat from numpy when `BeamType = TopHat` covers the same ground** — extra complexity, no extra fidelity.

### When the post-BB beam isn't enough — alternative paths

If you genuinely need a coherent result *through* the BB (not just from after it), POP can't do it. Two alternatives:

| Need | Path |
|---|---|
| Polarization-sensitive coherent propagation through arbitrary geometry | Wrap the BB-containing sequential system as an NSC group via `OpenConvertToNSCGroup`, then use `NCE.GetAllCoherentDataSafe` (scalar Ex; pair with the Stokes workaround in `data-extraction.md` for full polarization). Worse spatial sampling than POP. |
| Coherent result through an element whose function you can describe analytically | Substitute the BB with a POP-compatible equivalent: `Paraxial` for an ideal lens, `JonesMatrix` for a polarization element, `GridPhase` / `UserDefinedSurface` (DLL) for a phase plate. Costs accuracy on the substituted element in trade for POP's full Ex/Ey through the whole system. |

For a polarization-sensitive coherent bench using a BB beam-shaper followed by PBS/QWPs and a target plane: the post-BB POP path is usually right — you care about field at the target plane, not inside the BB.

## Per-surface POP settings (`surf.PhysicalOpticsData`)

POP behavior at each LDE surface is configurable. Reach via `surf.PhysicalOpticsData` on `ILDERow` (typed implementation discoverable with the probe script — `surf.get_PhysicalOpticsData().__implementation__`):

| Per-surface setting | When to use |
|---|---|
| **Use Rays To Propagate To Next Surface** | Required for non-sequential, birefringent, and gradient-index surfaces. Also useful as a speed optimization for short distances where diffraction is negligible. |
| **Do Not Rescale Beam Size Using Ray Data** | Disable the auto-stretch algorithm when the ray grid enters a caustic and shouldn't be trusted to set beam shape. |
| **Use Angular Spectrum Propagator** | Force angular-spectrum (constant array width) instead of OpticStudio's auto-selected propagator. Use only when beam size doesn't change much over the propagation. |
| **Re-Compute Pilot Beam Parameters** | Required after any surface that significantly alters the beam — pinhole apertures most notably. The pilot beam tracks the dominant Gaussian envelope; a pinhole invalidates it. |
| **Auto Resample / Resample After Refraction** | Change array sampling mid-propagation. Auto Resample uses the pilot beam to pick new sampling automatically. |
| **Output Pilot Radius** (`Best Fit` / `Shorter` / `Longer` / `X` / `Y` / `Plane` / `User`) | How to compute the pilot beam's phase radius after the surface. `Best Fit` (default) is almost always right. |

**Pinhole-aperture pattern** (the one most easily wrong): after the pinhole surface, set both **Re-Compute Pilot Beam Parameters** and **Auto Resample**. Without this, POP's downstream propagation uses a pilot beam that no longer matches the diffracted reality and produces nonsense at subsequent surfaces.

## Sampling matters more than usual

POP results are very sampling-dependent. The two knobs are:
- **Number of samples** (`X Sampling`, `Y Sampling`) — usually a power of 2 from 32×32 up to 4096×4096. The work scales as N² per FFT; a 1024×1024 trace through 10 surfaces is reasonable on a workstation, 4096×4096 is slow.
- **Array width** (`X Width`, `Y Width` in lens units) — physical extent of the sampled grid at the entrance.

`AutoCalculateBeamSampling()` picks reasonable defaults from your beam parameters. Override only when the auto-pick is too coarse for your feature size (sub-wavelength fringes, etc.) or wastes samples on padding around a tiny beam.

If POP results look quantized, blocky, or have frame-edge artifacts: bump the sampling or check the per-surface "Use Rays To Propagate" / "Auto Resample" flags before assuming a physics bug.

## POPD merit-function operand

For closed-loop optimization on POP results, use the **`POPD`** operand. It returns whatever data code you pick. Selected codes (full list in OpticStudio Help → "POPD"):

| Data code | What it returns |
|---|---|
| 0 | Total fiber coupling (system × receiver efficiency) |
| 1 | System efficiency |
| 2 | Receiver efficiency |
| 3 | Total power |
| 4 | Peak irradiance |
| 5, 6, 7 | Pilot beam X position, Rayleigh range, waist |
| 8, 9, 10 | Pilot beam Y position, Rayleigh range, waist |
| 11, 12, 13 | X, Y, Z coords of the beam-array center on the end surface |
| 21, 22 | X, Y centroid of the irradiance distribution |
| 23, 24, 25, 26 | X, Y beam width and X, Y M² values |
| 27+ | Higher-order beam moments and cross terms |

**Operand setup gotcha** (from the OpticStudio Help): POPD reads the *saved* POP analysis settings. Configure POP in the GUI (or via API), **press Save on the settings dialog**, then add `POPD` rows to the MFE. If `Surf` / `Wave` / `Field` on the operand are 0, POPD uses the saved values; otherwise the operand's values override.

`POPI` is a related operand for irradiance threshold checks.

## Polarization in POP

POP propagates Ex and Ey independently. The `DataType` enum exposes only **irradiance and phase** per component (`EXIrradiance` / `EXPhase` / `EYIrradiance` / `EYPhase`) — no real/imaginary directly. Reconstruct the complex E via the helper above (`get_pop_complex_E`). For full vector polarization analysis (both Ex AND Ey), that's **four POP runs** total. POP respects `SystemData.Polarization` (Jx, Jy, phase) for the input beam, so you can launch elliptical / circular / arbitrary states.

For two-beam interference verification specifically: a sequential model of one arm of a coherent two-beam setup, propagated via POP to the target plane, gives you full Ex AND Ey complex grids (four POP runs, combined in numpy) — no Stokes workaround needed (compare with the NSC `GetAllCoherentDataSafe` Ex-only limitation in `data-extraction.md`). The trade-off is you lose the second arm's geometric independence; you'd have to model both arms in sequential and combine two such four-run sets with the right phase relationship to reconstruct the interference. For two-arm interference, NSC + Stokes workaround is usually less work overall.

## Gotchas

- **`OutputBeamFile` must be inside `TheApplication.POPDir`.** Same silent-rejection pattern as `ImagesDir` for image-export tools (see `analyses.md` § "NSC 3D Layout image export"). Render to POPDir, copy out if needed.
- **`AutoCalculateBeamSampling()` must be called before `Apply()`** if you want it to take effect — calling it after just gets you a recommendation for the next run.
- **Don't confuse POP's "save settings" with the analysis cfg.** POP's GUI Save button writes the settings used by the `POPD` operand, separate from the IAS_ `Save()` cfg-file mechanism. Both exist and serve different purposes.
- **POP is sequential-only.** For NSC coherent E-field work, use `GetAllCoherentDataSafe` (single-component limitation — see `data-extraction.md`). There is no NSC POP equivalent in v24.1.
- **Pilot beam can desynchronize from reality** after pinholes / tightly clipping apertures. Set per-surface "Re-Compute Pilot Beam Parameters" + "Auto Resample" at any aperture surface.
- **Sampling artifacts look like physics.** If a result looks wrong, double the sampling once before debugging anything else.
- The `BeamType`, `DataType`, `LogScale`, etc. enums all live in `ZOSAPI.Analysis.PhysicalOptics`. The probe script's `ANALYSIS_TYPES` list already has `PhysicalOpticsPropagation` — extend it if you need to dump the enum members.

## Quick orientation table

| You want... | Path |
|---|---|
| Run POP and get a 2D irradiance grid | `New_Analysis(AnalysisIDM.PhysicalOpticsPropagation)` → `AutoCalculateBeamSampling()` → `Apply` → `GetResults().GetDataGrid(0)` |
| Compute fiber coupling efficiency | Same, plus `ComputeFiberCouplingIntegral = True`, `FiberType`, `FiberTypeFilename`, `FiberPosition` — read from `POPD` codes 0/1/2 or the text dump |
| Save propagated E-field for later | `SaveOutputBeam = True`, `OutputBeamFile = '<POPDir>/...ZBF'` |
| Diagnose where the beam goes wrong | `SaveBeamAtAllSurfaces = True` — inspect the per-surface `.ZBF` files |
| Optimize a system on POP results | Add `POPD` operand rows to the MFE (after pressing Save in the POP analysis dialog so the operand can find the settings) |
| Inspect what POP enums / settings exist | Probe script's `ANALYSIS_TYPES` includes POP; or `chmseek grep "ZOSAPI.Analysis.PhysicalOptics"` |
