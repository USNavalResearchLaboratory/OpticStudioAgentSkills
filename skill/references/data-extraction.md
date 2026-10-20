# Detector Data Extraction

After a ray trace, results live on the detector objects. The API exposes both incoherent-irradiance (energy summed without phase) and coherent (E-field with phase) data, plus higher-level Detector Viewer analyses.

## Picking the right extraction path

**Default to the cheapest path that gives the metric you need.** The four extraction layers, fastest first:

| What you need | Use | Why |
|---|---|---|
| **A single derived scalar** — total power, RMS spot, RMS angular radius, centroid x/y/z, MTF at a frequency, mean/max/min flux | **NSDD operand via `MFE.GetOperandValue`** (see below) — no analysis, no ZRD, no per-pixel loop | Runs the optimized internal C# routine; ~ms per call |
| **Per-pixel power grid** (full 2D incoherent irradiance) | `NCE.GetAllDetectorDataSafe(det, Data)` | One call returns the whole grid as a flat `double[]` |
| **Coherent E-field grid** (with phase) | `NCE.GetAllCoherentDataSafe(det, DDT.X)` | Only API path that returns coherent data correctly (Detector Viewer is broken for this in v24.1) |
| **Per-segment ray attributes** (which ray hit which face, OPL of segment 3 of ray 47, etc.) | `OpenNSCRayTrace` with `SaveRays=True` → `OpenRayDatabaseReader` | Last resort. ZRD files are large, iteration is slow. See `ray-database.md`. |

**Don't iterate rays for a metric an operand exposes.** RMS spot, RMS angular radius, centroid coordinates, mean flux, MTF — all available via NSDD `Pix#`/`Data#` combinations (table below). Iterating the ZRD to compute these in numpy is 100-1000× slower and prone to weighting bugs.

## NSDD operand readout (single-call derived metrics)

`MFE.GetOperandValue(MeritOperandType.NSDD, srf, det, pix, data, 0, 0, 0, 0)` evaluates the NSDD operand on-the-fly. The first four parameter slots after the operand type map to NSDD's documented cells: **Surface, Detector, Pix#, Data#** (the remaining `Px/Py/Ex/Ey` slots are padding zeros).

```python
import ZOSAPI as Z
MOT = Z.Editors.MFE.MeritOperandType
GetVal = TheSystem.MFE.GetOperandValue

# 1) Clear detectors (NSDD with detector=0 clears all energy)
GetVal(MOT.NSDD, 1, 0, 0, 0, 0, 0, 0, 0)

# 2) Run an NSC trace — NSDD reads data on detectors; it does NOT trace
rt = TheSystem.Tools.OpenNSCRayTrace()
rt.SplitNSCRays = True; rt.UsePolarization = True; rt.IgnoreErrors = True
rt.ClearDetectors(0)                                # equivalent to NSDD-with-det=0
rt.RunAndWaitForCompletion(); rt.Close()

# 3) Read derived metrics directly — no per-pixel iteration
det = 5                                              # object number of your Detector Rectangle
total_flux        = GetVal(MOT.NSDD, 1, det,   0, 0, 0,0,0,0)   # sum of flux over all pixels (W)
rms_radial_pos    = GetVal(MOT.NSDD, 1, det,  -9, 0, 0,0,0,0)   # weighted RMS r (lens units) — flux-weighted
rms_radial_ang    = GetVal(MOT.NSDD, 1, det,  -9, 2, 0,0,0,0)   # weighted RMS angular radius — intensity-weighted (radians?)
rms_x_pos         = GetVal(MOT.NSDD, 1, det, -10, 0, 0,0,0,0)   # weighted RMS x
rms_y_pos         = GetVal(MOT.NSDD, 1, det, -11, 0, 0,0,0,0)
centroid_x        = GetVal(MOT.NSDD, 1, det,  -6, 0, 0,0,0,0)   # x coord of flux centroid
centroid_y        = GetVal(MOT.NSDD, 1, det,  -7, 0, 0,0,0,0)
max_flux          = GetVal(MOT.NSDD, 1, det,  -1, 0, 0,0,0,0)
ray_count         = GetVal(MOT.NSDD, 1, det,  -3, 0, 0,0,0,0)   # number of rays striking (NOT RMS — common mix-up)
```

### Critical caveats

- **`Data#=2` (angle space / intensity = flux per solid angle) is ONLY available for Detector Rectangle.** Faceted detectors and `Pix#=0/-1` only support `Data#=0` or `Data#=1`. Calling with `Data#=2` on the wrong detector type returns 0 or garbage.
- **`Pix#=-3` is RAY COUNT, not any RMS.** Another AI's writeup confused `-3` with `-9` — they're unrelated. Always check the table.
- **`Pix#=-9/-10/-11/-12` + `Data#=0` gives RMS in LENS UNITS** (mm if your system is mm). With `Data#=2` it gives RMS in ANGLE SPACE (radians for a Detector Rectangle with angle-space data). Pick `Data#` to match the metric you want.
- **`Surface` is the NSC group surface number, not the detector object.** In pure-NSC mode (`SystemType.NonSequential`) it is always `1`. For a sequential system with an NSC group surface inserted, use that group's LDE surface number.
- **NSDD does not trace.** It reads from detector state at call time. Always trace (or run `NSTR`/`OpenNSCRayTrace`) first, then read NSDD.

### NSDD Pix# / Data# combinations (most useful)

Cross-reference for the OpticStudio Help "NSC Operands" table. Verify any unusual combination there before relying on it.

| Pix# | Data# | Returns |
|---|---|---|
| `N > 0` | 0 / 1 / 2 | Flux / irradiance / intensity on pixel N |
| `0` | 0 / 1 / 2 | Total flux (position) / mean flux/area / total flux (angle) |
| `-1` | 0 / 1 / 2 | Max flux / max irradiance / max intensity |
| `-2` | 0 / 1 / 2 | Min flux / min irradiance / min intensity |
| `-3` | unused | **Number of rays striking the detector** (NOT a flux/RMS value) |
| `-4` | 0 / 1 / 2 | Std-dev (RMS-from-mean) of flux / irradiance / intensity over non-zero pixels |
| `-5` | 0 / 1 / 2 | Mean of flux / irradiance / intensity over non-zero pixels |
| `-6 / -7 / -8` | 0 / 1 / 2 | Centroid x / y / z (weighted by flux / irradiance / intensity) |
| `-9` | 0 / 1 / 2 | **Weighted RMS radial distance** about centroid (flux / irradiance / intensity weighting). With Data#=2 on a Detector Rectangle, this is RMS angular radius — the canonical collimation metric. |
| `-10 / -11 / -12` | 0 / 1 / 2 | Weighted RMS x / y / z about centroid |
| `-13` | 0 / 1 / 2 | Weighted RMS xy about centroid (cross-moment) |
| `-14 / -15` | 0 / 1 | Geometric MTF in X / Y at the spatial frequency in cell 5 |

### Collimation check pattern

A common use: measure how well-collimated a beam is after a relay by reading RMS angular radius off a detector placed in the beam.

```python
def measure_collimation_rms_angle(TheSystem, det_obj_num):
    """Returns RMS angular radius (radians) of the flux distribution
    on a Detector Rectangle — small values = well-collimated."""
    import ZOSAPI as Z
    MOT = Z.Editors.MFE.MeritOperandType
    GetVal = TheSystem.MFE.GetOperandValue

    rt = TheSystem.Tools.OpenNSCRayTrace()
    rt.SplitNSCRays = True; rt.UsePolarization = True; rt.IgnoreErrors = True
    rt.ClearDetectors(0)
    if not rt.RunAndWaitForCompletion():
        rt.Close(); raise RuntimeError(f"NSC trace failed: {rt.ErrorMessage}")
    rt.Close()

    # Pix=-9, Data=2: weighted RMS radial distance in angle space (intensity-weighted)
    return GetVal(MOT.NSDD, 1, det_obj_num, -9, 2, 0, 0, 0, 0)
```

For a perfectly collimated beam the value approaches `0`. The detector must be a **Detector Rectangle** (faceted detectors don't support `Data#=2`), and it must have enough pixels in angle space to resolve the divergence you're measuring — check the detector's angular extent / pixel count via its ObjectData properties before trusting small numbers.

## Total power on a detector

```python
ret, total_power = TheSystem.NCE.GetDetectorData(det_obj_idx, 0, 0, 0)   # pixel=0 → SUM over all pixels
print(f"Power: {total_power:.6e} W")
```

**`GetDetectorData(obj, pixel, Data, value)` — the `pixel` argument is an aggregate selector, and the codes are easy to get wrong.** Per the CHM (`ZOSAPI.Editors.NCE.INonSeqEditor.GetDetectorData`, ZOS-API help p_001503/ch_001664): for Detector Rectangles, Detector Surfaces, and faceted detectors —

| `pixel` | Returns (per the CHM) |
|---------|-----------------------|
| `0` | **Sum of the total flux over all pixels** — this is total power |
| `-1` | **Maximum** flux (single brightest pixel) — NOT total |
| `-2` | Minimum flux |
| `-3` | Number of rays striking the detector |
| `-4` / `-5` | Std-dev / mean of non-zero pixel data |
| `-6,-7,-8` | x / y / z coordinate of the flux centroid |
| `-9 … -13` | RMS radius / x / y / z / xy about the centroid (second moments) |
| `N > 0` | The N-th pixel (1-based **linear** index, row-major) |

The `Data` argument is the quantity: **0 = flux, 1 = flux/area, 2 = flux/solid angle** (faceted detectors also accept 4 = absorbed flux, 5 = absorbed flux/area; Detector Volumes use 0/1/2 = incident/absorbed/absorbed-per-volume).

**Trap:** `GetDetectorData(obj, -1, 0, 0)` returns the *maximum-pixel* flux, not total power. Use `pixel=0` for total. (This matches the NSDD `Pix#` table above — same `0 = total`, `-1 = max` convention.)

## Incoherent irradiance grid (per-pixel power)

Two single-call paths (avoid the per-pixel loop — both pull the whole grid in one IPC call):

```python
# A) GetAllDetectorDataSafe — flat double[] in row-major order
data_flat = TheSystem.NCE.GetAllDetectorDataSafe(det_obj_idx, 0)   # Data=0 flux, 1 irradiance, 2 intensity (Det Rect only)
rows = TheSystem.NCE.GetObjectAt(det_obj_idx).get_ObjectData().__implementation__.NumberYPixels
cols = TheSystem.NCE.GetObjectAt(det_obj_idx).get_ObjectData().__implementation__.NumberXPixels
grid = np.array(list(data_flat)).reshape(rows, cols)

# B) Per-pixel (slow for large grids — one IPC call per pixel).
#    `pixel` is a SINGLE 1-based linear index (row-major), NOT an (x, y) pair —
#    GetDetectorData has no separate y argument; the 3rd slot is `Data`.
pixel_index = col + row * cols + 1                    # 1-based linear index
ret, power = TheSystem.NCE.GetDetectorData(det_obj_idx, pixel_index, 0, 0)
```

For a saveable image artifact instead of (or in addition to) raw numbers, see the Detector Viewer recipe in `analyses.md`.

## Coherent E-field via `GetAllCoherentDataSafe`

```python
DDT = ZOSAPI.Editors.NCE.DetectorDataType
Ex_real_raw = TheSystem.NCE.GetAllCoherentDataSafe(det_obj_idx, DDT.Real)
Ex_imag_raw = TheSystem.NCE.GetAllCoherentDataSafe(det_obj_idx, DDT.Imaginary)
Ex_real = to_numpy(Ex_real_raw, zos)    # see boilerplate.md for to_numpy
Ex_imag = to_numpy(Ex_imag_raw, zos)
Ix = Ex_real**2 + Ex_imag**2            # |Ex|² (single polarization component!)
```

The four `DetectorDataType` values:

| Enum | Returns |
|------|---------|
| `DDT.Real` (0) | Ex real part (per pixel) |
| `DDT.Imaginary` (1) | Ex imaginary part |
| `DDT.Amplitude` (2) | |Ex|, NOT \|E_total\| |
| `DDT.Power` (3) | |Ex|² |

**Critical limitation:** the NSC coherent detector stores a **scalar** E-field, not a vector. `Real` and `Imaginary` give Ex (one polarization component); Ey is **not directly accessible** through this API. Indices 4+ are invalid enum values. The `surfaceNum` argument doesn't differentiate by polarization either.

This is fine for unpolarized or fixed-polarization analysis. It's a problem when you need full Stokes parameters (S0, S1, S2, S3) — see workaround below.

**Sequential alternative:** if your design can be modeled in sequential mode, **Physical Optics Propagation (POP)** gives you the full complex E-field — both Ex and Ey, with no Stokes workaround needed. POP propagates the wave directly via diffraction integrals. See `physical-optics.md`. The trade-off is that POP runs one beam at a time, so a two-arm interference setup needs two POP runs combined in numpy with the right phase relationship.

## Stokes workaround: combine Detector Viewer (incoherent) with API (coherent Ex)

For symmetric two-beam interference (e.g. equal-power LCP + RCP), the Detector Viewer's incoherent irradiance is proportional to S0 = |Ex|² + |Ey|². Combine that with the coherent API's |Ex|² to derive |Ey|² and then compute Stokes:

```python
# 1) Incoherent irradiance via Detector Viewer
DVSAT = ZOSAPI.Analysis.DetectorViewerShowAsTypes
dv = TheSystem.Analyses.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.DetectorViewer)
settings = dv.GetSettings()
settings.Detector = det_obj_idx             # select the detector (see multi-detector trap below)
settings.ShowAs = DVSAT.FalseColor
dv.ApplyAndWaitForCompletion()
grid = dv.GetResults().GetDataGrid(0)
DV = np.flipud(np.array(zos.reshape(grid.Values, grid.Values.GetLength(0),
                                                  grid.Values.GetLength(1))))
dv.Close()

# 2) Scale DV to match API units (only on illuminated pixels)
mask = DV > DV.max() * 0.01
scale = (2.0 * np.mean(Ix[mask])) / np.mean(DV[mask])
S0 = DV * scale

# 3) Stokes parameters
Iy = np.maximum(S0 - Ix, 0)            # |Ey|² = S0 - |Ex|²
S1 = Ix - Iy                            # linear horizontal/vertical
S2_mag = np.sqrt(np.maximum(S0**2 - S1**2, 0))   # for S3=0 (LCP+RCP physics)
S2 = -np.sign(np.gradient(S1, axis=1)) * S2_mag  # sign from S1 derivative
S3 = np.zeros_like(S0)                  # by symmetric LCP+RCP construction
```

The signs of S2 and S3 require physics-based assumptions because the API doesn't give them directly. For asymmetric setups, this workaround is less reliable.

## Detector Viewer analysis

The full analysis-API pattern:

```python
DVSAT = ZOSAPI.Analysis.DetectorViewerShowAsTypes
DVSDT = ZOSAPI.Analysis.DetectorViewerShowDataTypes

dv = TheSystem.Analyses.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.DetectorViewer)
settings = dv.GetSettings()
settings.Detector = det_obj_idx             # WHICH detector — see multi-detector trap below
settings.ShowAs = DVSAT.FalseColor          # FalseColor, GreyScale, TrueColor, CrossSection
settings.DataType = DVSDT.IncoherentIrradiance   # see caveat below
dv.ApplyAndWaitForCompletion()

results = dv.GetResults()
grid = results.GetDataGrid(0)               # numeric grid; GetDataGridRgb(0) for color
arr = np.flipud(np.array(zos.reshape(grid.Values,
                                     grid.Values.GetLength(0),
                                     grid.Values.GetLength(1))))
dv.Close()
```

**Caveat (v24.1):** setting `settings.DataType = CoherentIrradiance` or `CoherentPhase` appears to succeed (no error, readback shows the new value), but `GetDataGrid(0)` returns the same incoherent irradiance for all three values. The `ModifySettings` approach with binary `.cfg` files also doesn't differentiate. Don't rely on `DataType` to switch between coherent and incoherent through the Detector Viewer — use the API's `GetAllCoherentDataSafe` for coherent data instead.

**Multi-detector trap:** a Detector Viewer reads exactly **one** detector — the one named by `settings.Detector` (the NCE object number; confirm with `settings.IsValidDetector` / `settings.GetDetectorObjectNumber()`). **If you loop over several detectors but reuse a viewer (or a helper) without setting `settings.Detector` each time, every read returns the same detector's grid** — so a "loss budget" across planes shows the identical number on every plane and looks like the energy never changes. Set `settings.Detector` before each `ApplyAndWaitForCompletion()`, or — better for a single scalar like total flux — skip the viewer entirely and use `GetDetectorData(obj, 0, 0, 0)` per detector (above), which takes the object number directly and can't be confused this way.

## Saved-detector files (`.DDR`)

`SaveDetector` and `LoadDetector` work on individual detectors:

```python
NCE.SaveDetector(det_obj_idx, r'C:\path\detector.DDR')
NCE.LoadDetector(det_obj_idx, r'C:\path\detector.DDR', False)
```

The `.DDR` binary format is undocumented. If you need detector data, use the API methods above rather than parsing `.DDR` directly.

## NSC 3D layout export

```python
la = TheSystem.Analyses.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.NSC3DLayout)
la.ApplyAndWaitForCompletion()
la.GetResults().GetTextFile(r'C:\path\layout.txt')   # text dump
la.Close()
```

The 3D layout is an OpenGL rendering — `GetDataGridRgb(0)` returns `None` for it. Use `GetTextFile` for a text export, or just open the saved `.zos` in OpticStudio for the visual.

## ModifySettings + `.cfg` fallback

When typed analysis settings don't expose what you need (or appear to fail silently like the Detector Viewer's `DataType`), the fallback is `ModifySettings` operating on a saved `.cfg` config file:

```python
settings.SaveTo(r'C:\path\dv.cfg')
settings.ModifySettings(r'C:\path\dv.cfg', 'DET_DATA', '1')   # change one keyword
settings.LoadFrom(r'C:\path\dv.cfg')
dv.ApplyAndWaitForCompletion()
```

Many config files are partially binary; not every keyword you'd guess is present. Read the file in a text editor first to see what's actually there.
