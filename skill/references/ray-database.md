# Ray Data: Batch Trace and ZRD Reader

**First, check whether you actually need per-ray data.** For derived scalars (total power, RMS spot, RMS angular radius, centroid, MTF, mean/max/min flux) the `NSDD` operand via `MFE.GetOperandValue` is 100-1000× faster — it runs the optimized internal C# routine in milliseconds. See `data-extraction.md` § "NSDD operand readout." Only reach for the ZRD reader when you need per-ray-segment attributes the operands don't expose (which face a specific ray hit, OPL of segment 3 of ray 47, whether a ray was scattered or split at a given object).

For high-volume ray work, the per-detector approach (1 NSC trace → 1 detector aggregate) is too coarse. Two purpose-built APIs let you submit thousands or millions of rays at once and read individual ray attributes back:

- **Sequential batch ray trace** (`Tools.OpenBatchRayTrace`) — submit rays through an LDE system; read out per-ray image-plane positions, OPL, intensity, etc.
- **NSC ray database (ZRD)** — persist every ray segment from an NSC trace to a `.ZRD` file, then iterate them via `Tools.OpenRayDatabaseReader`.

Both push the per-ray loop into compiled C# (the `RayTrace.dll` external assembly), which is roughly 40× faster than running the loop in Python with per-call API overhead.

## Sequential batch ray trace

Used to compute spot diagrams, custom ray fans, OPL maps, etc. without going through the full Spot/RayFan analyses. Four "create" methods depending on whether ray inputs are normalized vs. direct, polarized vs. unpolarized:

| Method | Inputs | When |
|--------|--------|------|
| `CreateNormUnpol(N, raysType, surface)` | (Hx, Hy) field + (Px, Py) pupil normalized to [-1, 1] | Most common — replicates Spot/RayFan inputs |
| `CreateNormPol(N, raysType, surface, jx, jy, xphase, yphase)` | Same + initial polarization state | Polarization-aware spot/MTF |
| `CreateDirectUnpol(N, raysType, surface)` | Real-world (x, y, z) start + (l, m, n) direction cosines | When you have ray bundles from outside |
| `CreateDirectPol(N, raysType, surface, jx, jy, xphase, yphase)` | Same + polarization | Polarized direct rays |

`raysType` is `ZOSAPI.Tools.RayTrace.RaysType.Real` (the usual choice) or `.Paraxial`. `surface` is the LDE surface to trace to (use `LDE.NumberOfSurfaces` for the image plane).

### Pattern: spot diagram via batch trace

```python
import System
from System import Int32, Double, Enum

raytrace = TheSystem.Tools.OpenBatchRayTrace()
nsur = TheSystem.LDE.NumberOfSurfaces
N = 900                          # number of rays
RT = ZOSAPI.Tools.RayTrace
data = raytrace.CreateNormUnpol(N, RT.RaysType.Real, nsur)

# Add rays
for _ in range(N):
    px = np.random.random() * 2 - 1
    py = np.random.random() * 2 - 1
    data.AddRay(1,  # waveNumber
                0.0, 0.5,            # Hx, Hy
                px, py,              # Px, Py
                Enum.Parse(RT.OPDMode, "None"))

raytrace.RunAndWaitForCompletion()

# Read results
data.StartReadingResults()
sysInt = Int32(0)
sysDbl = Double(0.0)
output = data.ReadNextResult(sysInt, sysInt, sysInt,
                              sysDbl, sysDbl, sysDbl,
                              sysDbl, sysDbl, sysDbl,
                              sysDbl, sysDbl, sysDbl, sysDbl, sysDbl)
while output[0]:                                          # success
    if output[2] == 0 and output[3] == 0:                  # ErrorCode + vignetteCode
        ray_idx = output[1]
        x_image = output[4]; y_image = output[5]; z_image = output[6]
        l = output[7]; m = output[8]; n = output[9]
        # output[10..13] = additional ray attributes (intensity, OPL, etc.)
        # store / process
    output = data.ReadNextResult(sysInt, sysInt, sysInt,
                                  sysDbl, sysDbl, sysDbl,
                                  sysDbl, sysDbl, sysDbl,
                                  sysDbl, sysDbl, sysDbl, sysDbl, sysDbl)

raytrace.Close()
```

### Pythonnet ref-arg pattern

`ReadNextResult` (and many other ZOS-API methods) declare `out`/`ref` parameters in C#. In Python you must pass placeholder `System.Int32(0)` and `System.Double(0.0)` values for each — they're rebound to the actual outputs by pythonnet, which returns everything in a tuple:

```python
output = data.ReadNextResult(sysInt, sysInt, sysInt, sysDbl, ...)
# output[0] = bool success flag
# output[1..N] = the rebound out-args, in declared order
```

Plain Python `int(0)` / `float(0.0)` are not equivalent — they get boxed differently and the call may silently misbehave.

## NSC ray database (ZRD)

The ZRD file persists the full ray history (every segment, every reflection, every split) of an NSC trace. Useful when you want to:
- Replay a trace through different detector filters without re-tracing
- Inspect individual ray paths for debugging
- Compute custom statistics that the Detector Viewer doesn't expose

### Step 1: save a ZRD during the NSC trace

```python
nscRT = TheSystem.Tools.OpenNSCRayTrace()
nscRT.SplitNSCRays = True
nscRT.ScatterNSCRays = False
nscRT.UsePolarization = True
nscRT.IgnoreErrors = True
nscRT.SaveRays = True                                    # enable ZRD output
nscRT.SaveRaysFile = 'mydesign.ZRD'                      # written next to the .zos file
nscRT.ClearDetectors(0)
nscRT.RunAndWaitForCompletion()
nscRT.Close()
```

Big files: a multi-million-ray trace with splitting can produce hundreds of MB. Use `OpenZRDFilter` (below) to pre-filter at the source.

### Step 2: read the ZRD with OpenRayDatabaseReader

The two reader methods have signatures with `out` parameters of mixed types. The CHM declarations (verbatim) are:

```csharp
bool ReadNextResult(out int rayNumber, out int waveIndex, out double wlUM, out int numSegments);
bool ReadNextSegmentFull(
    out int segmentLevel, out int segmentParent, out int hitObj, out int hitFace, out int insideOf,   // 5 ints
    out RayStatus status,                                                                              // 1 enum (NOT int)
    out double x, out double y, out double z,                                                          // 3 doubles
    out double l, out double m, out double n,                                                          // 3 doubles (direction cosines)
    out double exr, out double exi, out double eyr, out double eyi, out double ezr, out double ezi,   // 6 doubles (E-field)
    out double intensity, out double pathLength,                                                       // 2 doubles
    out int xybin, out int lmbin,                                                                      // 2 ints AFTER the doubles
    out double xNorm, out double yNorm, out double zNorm,                                              // 3 doubles (surface normal)
    out double index, out double startingPhase, out double phaseOf, out double phaseAt);               // 4 doubles
```

Total per segment call: **7 ints + 1 RayStatus + 21 doubles**, interleaved (ints are split by doubles around `xybin`/`lmbin`). Use `System.Int32(0)`, `System.Double(0.0)`, and an enum-typed placeholder for `RayStatus` — plain Python `0` / `0.0` are boxed by pythonnet but the wrong-type overload may resolve silently. The output tuple's element at position `i+1` corresponds to the i-th `out` parameter in declared order.

```python
import System
from System import Int32, Double

reader = TheSystem.Tools.OpenRayDatabaseReader()
reader.ZRDFile = r'C:\path\mydesign.ZRD'                 # full path
reader.RunAndWaitForCompletion()
if not reader.Succeeded:
    print(reader.ErrorMessage)

results = reader.GetResults()
RayStatus = ZOSAPI.Tools.RayTrace.RayStatus               # enum type; need a member as placeholder
rs0 = RayStatus.Terminated                                # any member works; pythonnet rebinds it on return.
                                                          # Real members: Terminated, Transmitted, Reflected,
                                                          # Diffracted, Scattered, TIR, BulkScattered,
                                                          # OrdinaryRay, ExtraordinaryRay, WaveShifted, RayError, ...
                                                          # (NO 'Continue' — that name doesn't exist in v24.1)

# Outer loop: rays
def read_next_ray():
    return results.ReadNextResult(Int32(0), Int32(0), Double(0.0), Int32(0))
    #                              ^ rayNumber ^ waveIndex ^ wlUM    ^ numSegments

def read_next_seg():
    return results.ReadNextSegmentFull(
        Int32(0), Int32(0), Int32(0), Int32(0), Int32(0),     # segmentLevel..insideOf
        rs0,                                                   # RayStatus enum placeholder
        Double(0.0), Double(0.0), Double(0.0),                 # x, y, z
        Double(0.0), Double(0.0), Double(0.0),                 # l, m, n
        Double(0.0), Double(0.0), Double(0.0),                 # exr, exi, eyr
        Double(0.0), Double(0.0), Double(0.0),                 # eyi, ezr, ezi
        Double(0.0), Double(0.0),                              # intensity, pathLength
        Int32(0), Int32(0),                                    # xybin, lmbin (AFTER doubles)
        Double(0.0), Double(0.0), Double(0.0),                 # xNorm, yNorm, zNorm
        Double(0.0), Double(0.0), Double(0.0), Double(0.0),    # index, startingPhase, phaseOf, phaseAt
    )

ray = read_next_ray()
while ray[0]:                                              # ray[0] = success bool
    rayNumber, waveIndex, wlUM, numSegments = ray[1], ray[2], ray[3], ray[4]
    seg = read_next_seg()
    while seg[0]:
        # Tuple index → out-param (declaration order, +1 for the success bool):
        #   [1] segmentLevel    [2] segmentParent  [3] hitObj          [4] hitFace
        #   [5] insideOf        [6] status         [7..9] x, y, z
        #   [10..12] l, m, n    [13..18] exr, exi, eyr, eyi, ezr, ezi
        #   [19] intensity      [20] pathLength    [21] xybin          [22] lmbin
        #   [23..25] xNorm, yNorm, zNorm           [26] index
        #   [27..29] startingPhase, phaseOf, phaseAt
        seg = read_next_seg()
    ray = read_next_ray()

reader.Close()
```

`ReadNextSegmentFull` is the modern all-attributes-at-once method. Older code uses `ReadNextSegment` (same int/enum/double interleave but **without** the `xybin/lmbin/xNorm/yNorm/zNorm/index/startingPhase/phaseOf/phaseAt` tail — 5 ints + RayStatus + 14 doubles) plus per-attribute property getters (`results.HitObject`, `results.Intensity`, etc., which return the value for the *current* segment). Prefer `Full` — fewer round trips through the pythonnet bridge.

## Filtering ZRDs

For "I only want rays that hit object 4 exactly twice" or "rays with intensity > 0.5 at the detector", use `Tools.OpenZRDFilter`. It produces a smaller ZRD that downstream readers can iterate quickly.

You can also pass a filter string directly to the Detector Viewer when replaying a ZRD:

```python
DetectorView = TheSystem.Analyses.New_DetectorViewer()
s = DetectorView.GetSettings()
s.RayDatabaseFilename = 'mydesign.ZRD'
s.ShowAs = ZOSAPI.Analysis.DetectorViewerShowAsTypes.FalseColor
s.Filter = 'X_HIT(2, 4)'                                  # only rays that hit object 2 four times
DetectorView.ApplyAndWaitForCompletion()
```

Filter syntax (`X_HIT`, `M_HIT`, `R_HIT`, etc.) is documented in the OpticStudio Help under "Detector ray filtering."

## When to use each path

| Scenario | Use |
|----------|-----|
| Need image-plane positions of N rays through a sequential lens | Batch ray trace |
| Custom spot diagram, OPL map, ray bundle through a sequential design | Batch ray trace |
| NSC trace with millions of rays — need per-ray attributes | NSC trace with `SaveRays = True` + RayDatabaseReader |
| Filter NSC results without re-tracing | OpenZRDFilter or Detector Viewer with filter string |
| Just want total power on a detector | `NCE.GetDetectorData(obj, 0, 0, 0)` — pixel=0 = total (−1 = max pixel, not total); no batch needed |
| Just want a coherent E-field grid on a detector | `NCE.GetAllCoherentDataSafe(obj, ...)` (see `data-extraction.md`) |
