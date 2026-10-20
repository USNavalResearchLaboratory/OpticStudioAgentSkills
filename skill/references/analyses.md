# Analyses Framework

Analyses produce design metrics — spot sizes, MTF, wavefront error, ray fans, layout images, etc. Every analysis follows the same lifecycle and exposes its results through one (or more) of a small set of typed data containers.

The NSC Detector Viewer is a special case (covered in `data-extraction.md`). Everything else lives here.

## General lifecycle

```python
A = TheSystem.Analyses
# Create — either generic or via a typed convenience method
analysis = A.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.StandardSpot)
# OR: analysis = A.New_StandardSpot(); A.New_FftMtf(); A.New_RayFan(); A.New_Wavefront(); ...

# Configure
settings = analysis.GetSettings()
settings.MaximumFrequency = 50
settings.SampleSize = ZOSAPI.Analysis.SampleSizes.S_256x256
# (each analysis exposes different typed settings; see below)

# Run
analysis.ApplyAndWaitForCompletion()

# Extract
results = analysis.GetResults()
# ... read containers ...

# Clean up
analysis.Close()
```

## Settings: typed vs ModifySettings fallback

Most analyses expose typed settings on the object returned by `GetSettings()`. Set them directly:
```python
spot_settings = spot.GetSettings()
spot_settings.Field.SetFieldNumber(0)              # 0 = all fields
spot_settings.Wavelength.SetWavelengthNumber(0)    # 0 = all wavelengths
spot_settings.ReferTo = ZOSAPI.Analysis.Settings.RMS.ReferTo.Centroid
spot_settings.RayDensity = 15
```

Some analyses (notably `UniversalPlot1D`, `UniversalPlot2D`, and a few others) return `False` from `analysis.HasAnalysisSpecificSettings`. For those, fall back to `ModifySettings` against a saved `.cfg` file:

```python
analysis_settings = analysis.GetSettings()
print(analysis.HasAnalysisSpecificSettings)        # False → use ModifySettings
cfg = TheApplication.ZemaxDataDir + '\\Configs\\UNI.CFG'
analysis_settings.Save()                            # writes the cfg
analysis_settings.ModifySettings(cfg, 'UN1_OPERAND', 'RSRE')
analysis_settings.ModifySettings(cfg, 'UN1_STARTVAL', '5.0')
analysis_settings.ModifySettings(cfg, 'UN1_STEPS', '20')
analysis_settings.LoadFrom(cfg)
```

Keyword names (`UN1_OPERAND`, etc.) are documented in the ZPL `MODIFYSETTINGS` keyword help. Some `.cfg` files are partially binary — read the saved file in a text editor first to confirm a keyword exists before scripting against it.

## AnalysisIDM enum: the catalog of analyses

`ZOSAPI.Analysis.AnalysisIDM` is the master enum of every analysis OpticStudio can produce. The table below organizes the most useful entries **by the design question they answer** — pick the right tool by browsing this column first, then look up the recipe (every analysis follows the general lifecycle above; settings live under `ZOSAPI.Analysis.Settings.<sub-namespace>` per the table).

| If you want to know... | Use one of | Settings namespace |
|---|---|---|
| **Geometric blur per field** (RMS/geo spot radius, scatter pattern) | `StandardSpot`, `FullFieldSpot`, `ThroughFocusSpot`, `MatrixSpot` | `Settings.Spot` |
| **Spatial-frequency response** (resolution, MTF50) | `FftMtf`, `GeometricMtf`, `FftThroughFocusMtf`, `GeometricThroughFocusMtf`, `FftSurfaceMtf` | `Settings.Mtf` |
| **Diffraction-limited spot** (PSF) | `FftPsf`, `FftPsfCrossSection`, `GeometricPsf`, `HuygensPsf` | `Settings.Psf` |
| **Wavefront error** (PV/RMS WFE, OPD map) | `Wavefront`, `WavefrontMap`, `OPDFan`, `FootprintFan` | `Settings.Fans`, `Settings.Wavefront` |
| **Aberrations as ray heights** | `RayFan`, `Pupil_Aberration_Fan`, `Seidel`, `SeidelCoefficients` | `Settings.Fans`, `Settings.Aberrations` |
| **Distortion + field curvature** (off-axis behavior) | `FieldCurvatureDistortion`, `LongitudinalAberration`, `LateralColor`, `RelativeIllumination` | `Settings.Aberrations` |
| **Cardinal-point data** (EFL, FFL, BFL, principal/nodal plane positions for a lens or surface range) | `CardinalPoints` — replaces the PARY-ray-tracing-and-flip-the-lens workaround (which is fragile because `InsertLensSeq(reverseSurfGeom=True)` is silently ignored and manual lens-reversal drops asphere/coating data) | (no typed settings beyond `First/LastSurface` + `Wavelength`; use `GetTextFile` to read the report) |
| **Energy concentration vs radius** | `EncircledEnergy`, `GeometricEncircledEnergy`, `DiffractionEncircledEnergy` | `Settings.EncircledEnergy` |
| **What an extended scene looks like through the lens** (full image simulation) | `ImageSimulation`, `GeometricImageAnalysis`, `ExtendedSourceAnalysis` | `Settings.ExtendedScene` |
| **Diffraction-based beam propagation** (laser beam through real lenses, fiber coupling, spatial filter, sequential coherent E-field with both Ex and Ey) | `PhysicalOpticsPropagation` — see **`physical-optics.md`** for the full guide; this is its own paradigm with `.ZBF` beam files, per-surface POP settings, and `POPD` operands | `Analysis.PhysicalOptics` (own sub-namespace, not `Settings.X`) |
| **Coating performance** (R / T / A vs angle or wavelength) | `CoatingsRTAvsWavelength`, `CoatingsRTAvsAngle` (also see `surf.GetCoatingPerformanceData()` in `sequential-design.md`) | `Settings.Coatings` |
| **Geometry visualization** | `Layout2D`, `Layout3D`, `CrossSection2D`, `ShadedModel`, `NSC3DLayout`, `NSCShadedModel` | (no typed settings — render via `ToFile`) |
| **NSC detector data** (irradiance, phase, ray hits) | `DetectorViewer` | `Settings.Detector` |
| **Custom plot of any operand vs surface or wavelength** | `UniversalPlot1D`, `UniversalPlot2D`, `MultiConfigurationMatrix` | (no typed settings — use `ModifySettings` with `.cfg`; see "Settings caveats" above) |

If you don't see what you need: enumerate the full enum dynamically with `System.Enum.GetValues(ZOSAPI.Analysis.AnalysisIDM)`, then `chmseek grep "<EnumName>"` to find the settings interface and any usage examples. The settings interface for any `AnalysisIDM.X` is conventionally named `IAS_X` and lives in `ZOSAPI.Analysis.Settings.<category>` — discover both via the probe script (`scripts/probe_object_properties.py` has an `ANALYSIS_TYPES` list you can extend).

**Boilerplate that works for every entry above:**
```python
analysis = TheSystem.Analyses.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.StandardSpot)  # any AnalysisIDM value from the table above
settings = analysis.GetSettings()
# print(dir(settings.__implementation__))   # discover typed properties for this analysis
# settings.<typed properties> = ...
analysis.ApplyAndWaitForCompletion()
results = analysis.GetResults()
# read results.SpotData / NumberOfDataSeries / NumberOfDataGrids / GetTextFile(...)
analysis.ToFile(r'C:\path\plot.JPG', False, False)   # save the rendered figure (any analysis)
analysis.Close()
```

## Result data containers

`analysis.GetResults()` returns an `IAR_` interface with a uniform set of optional containers. Different analyses populate different ones; check the relevant `Number*` property before reading.

| Container | What it holds | Access |
|-----------|--------------|--------|
| `DataGrid` | 2D image (PSF, Detector Viewer, wavefront map) | `results.NumberOfDataGrids`; `results.GetDataGrid(i).Values` (System.Double[,]) |
| `DataGridRgb` | 2D RGB image (true-color renderings) | `results.NumberOfDataGridsRgb`; `results.GetDataGridRgb(i)` |
| `DataSeries` | 1D or 2D line plot (MTF, ray fan, encircled energy) | `results.NumberOfDataSeries`; `results.GetDataSeries(i).XData.Data` and `.YData.Data` |
| `DataSeriesRgb` | RGB-tagged line plots | `results.NumberOfDataSeriesRgb` |
| `DataScatterPoints` | Point cloud (spot diagrams, ray hits) | `results.NumberOfDataScatterPoints`; `results.GetDataScatterPoints(i)` |
| `DataScatterPointsRgb` | RGB point clouds | `results.NumberOfDataScatterPointsRgb` |
| `RayData` | Per-ray attributes (ray fan, Seidel) | `results.NumberOfRayData`; `results.GetRayData(i)` |
| `CriticalRayData` | Critical-ray subset | `results.NumberOfCriticalRayData` |
| `PathAnalysisData` | Image-quality paths | `results.NumberOfPathAnalysisData` |
| `SpotData` | Spot statistics (only `StandardSpot`-class analyses) | `results.SpotData.GetRMSSpotSizeFor(field, wave)`, `GetGeoSpotSizeFor(field, wave)` — **units are NOT documented and may match the GUI's auto-scaled display** (µm when `LensUnits=mm`, etc.). For unit-strict reporting use the `RSCE` / `RSCH` MFE operand instead — see "Spot size with strict units" below. |
| `HeaderData` / `MetaData` | Title and metadata strings | `results.HeaderData.Lines`, `results.MetaData.Lines` |

### Reading a 1D series (MTF, ray fan, FCD)

`YData` on `IAR_DataSeries` is `IMatrixData` (with `Rows`, `Cols`, and `GetValueAt(row, col)`). **Use `GetValueAt(r, c)` — do not rely on `list(YData.Data)` flatten order or `np.reshape`** (see the 2D-array iteration-order pitfall in `pythonnet-gotchas.md`):

```python
for i in range(results.NumberOfDataSeries):
    series = results.GetDataSeries(i)
    x = np.array([series.XData.Data[k] for k in range(len(series.XData.Data))])
    ym = series.YData
    rows, cols = ym.Rows, ym.Cols
    y = np.array([[ym.GetValueAt(r, c) for c in range(cols)] for r in range(rows)])
    # y[:, c] is column c — meaning depends on the analysis (see SeriesLabels)
```

Column count and meaning vary by analysis — **read `series.SeriesLabels` to identify each column**:
- **Encircled Energy:** 1 column — fraction enclosed.
- **MTF:** 2 columns — tangential, sagittal.
- **Ray Fan:** N columns — one per wavelength (× field × X/Y plane in separate series).
- **Field Curvature & Distortion:** **1 series with 5 columns** — tangential FC, sagittal FC, real Y, paraxial Y, distortion (%). Distortion is column 4. (The plan-table claim of "series 0 = FC, series 1 = distortion" is wrong; everything is in one series.)

### Reading a 2D image (PSF, wavefront map, Detector Viewer)
```python
grid = results.GetDataGrid(0)
arr_2d = zos.reshape(grid.Values, grid.Values.GetLength(0), grid.Values.GetLength(1))
arr = np.flipud(np.array(arr_2d))   # match Zemax's display orientation
# grid also has MinX, MinY, Dx, Dy, Nx, Ny describing the sampling
```

### Reading spot statistics
```python
results = spot.GetResults()
for field in range(1, n_fields + 1):
    rms = results.SpotData.GetRMSSpotSizeFor(field, wave_num)
    geo = results.SpotData.GetGeoSpotSizeFor(field, wave_num)
```

### Universal text-export fallback

When no typed container has the data you want, every analysis can dump its results as a text report:
```python
results.GetTextFile(r'C:\path\analysis.TXT')
```

Parse the text with whatever pattern fits the analysis. Slow and brittle but always works.

## Units in analysis results

Numeric arrays from `XData.Data` / `YData.Data` / `Values` are bare numbers — the units are carried separately in label strings on each container. **Always read the labels before treating values as physical quantities** — the same analysis can mix units across series (FCD's series 0 is in lens units; series 1 is in percent), and "lens units" itself depends on the system setting.

### Unit labels on result containers

| Container | Label properties |
|---|---|
| `IAR_DataSeries` | `Description` (analysis name), `XLabel` (e.g. `"Spatial Frequency in cycles per mm"`), `SeriesLabels[]` (per-trace labels, often include units and wavelength) |
| `IAR_DataGrid` | `Description`, `XLabel`, `YLabel`, `ValueLabel` (units of the grid values) — plus numeric extent: `MinX`, `MinY`, `Dx`, `Dy`, `Nx`, `Ny` (always in lens units) |
| `IAR_DataScatterPoints` | `Description`, axis labels |
| `IAR_` (root) | `HeaderData.Lines[]`, `MetaData.Lines[]` — the multi-line text header the GUI shows above plots; contains units, wavelength weights, file path |

**Always-print-the-labels pattern** — costs nothing, makes downstream analysis self-documenting:
```python
results = analysis.GetResults()
print("Header:\n", "\n".join(results.HeaderData.Lines))
for i in range(results.NumberOfDataSeries):
    s = results.GetDataSeries(i)
    print(f"Series {i}: {s.Description!r} | X={s.XLabel!r} | series={list(s.SeriesLabels)}")
for i in range(results.NumberOfDataGrids):
    g = results.GetDataGrid(i)
    print(f"Grid {i}: {g.Description!r} | X={g.XLabel!r} Y={g.YLabel!r} | values={g.ValueLabel!r}")
```

### System-level unit context

These don't change per analysis but are the global frame of reference:

| Source | Units |
|---|---|
| `TheSystem.SystemData.Units.LensUnits` | enum: `Millimeters` / `Centimeters` / `Inches` / `Meters` — controls all lens-data lengths, spot sizes, encircled-energy radii, image-plane distances, footprint dimensions, `DataGrid` X/Y extents, image-simulation `PixelSize` |
| `TheSystem.SystemData.Wavelengths.GetWavelength(N).Wavelength` | always μm (regardless of LensUnits) |
| `TheSystem.SystemData.Environment.Temperature` | always °C |
| `TheSystem.SystemData.Environment.Pressure` | always atm |

### Per-analysis unit cheat sheet

Most surprises come from analyses that mix units within one result, or use waves/percent instead of lengths:

| Analysis | X-axis | Y / value | Notes |
|---|---|---|---|
| Standard Spot (`SpotData.GetRMSSpotSizeFor` / `GetGeoSpotSizeFor`) | n/a | **disputed / unverified** — may auto-scale with the GUI display (µm when `LensUnits=mm`); CHM does not document units | **Use `RSCE` / `RSCH` MFE operand for unit-strict spot size** (always lens units — see "Spot size with strict units" recipe below) |
| FFT/Geometric MTF | cycles per LensUnit (cycles/mm if mm) | dimensionless modulation | Y is 2D per series: tangential + sagittal |
| Ray Fan | normalized pupil [-1,1] | transverse aberration in **μm** (not lens units) | Y is 2D: one trace per wavelength |
| OPD Fan | normalized pupil | OPD in **waves at the reference wavelength** | not μm |
| Wavefront Map | grid index | **waves at reference λ** | `ValueLabel` confirms |
| FFT/Huygens PSF | grid index | normalized intensity (peak = 1) by default | grid extent in lens units |
| Encircled Energy | radius in lens units | fraction (0–1) | |
| Field Curvature & Distortion | field (lens units or deg) | **1 series, 5 columns**: tan FC, sag FC, real Y, paraxial Y, distortion (%) — FC columns in lens units, distortion in % | NOT 2 series — read `SeriesLabels` to confirm column meaning |
| Lateral Color | field | **μm** | independent of LensUnits |
| Longitudinal Aberration | normalized pupil | lens units | |
| Relative Illumination | field (lens units or deg) | fraction (0–1) | |
| Footprint | lens units | lens units | extent in `DataGrid.MinX/Dx/Nx` |
| Image Simulation | pixel index | RGB / intensity | `settings.PixelSize` is in lens units |
| Detector Viewer (NSC) | mm (detector grid) | W/cm² (incoherent) or W/cm² (coherent) — see `data-extraction.md` | NSC is always SI internally |
| POP | mm (beam grid) | W/mm² (irradiance) or radians (phase) | see `physical-optics.md` |

When in doubt, log the labels and the GUI header — the text shown in the GUI's analysis window comes from exactly the same `XLabel` / `ValueLabel` / `HeaderData` strings the API exposes.

## Common analyses, full recipes

### FFT MTF
```python
mtf = TheSystem.Analyses.New_FftMtf()
s = mtf.GetSettings()
s.MaximumFrequency = 50            # cycles/mm
s.SampleSize = ZOSAPI.Analysis.SampleSizes.S_256x256
mtf.ApplyAndWaitForCompletion()
results = mtf.GetResults()
# results.NumberOfDataSeries == 2 * NumberOfFields (tangential + sagittal per field)
```

### Standard Spot
```python
spot = TheSystem.Analyses.New_StandardSpot()
s = spot.GetSettings()
s.Field.SetFieldNumber(0)          # 0 = all fields
s.Wavelength.SetWavelengthNumber(0)
s.RayDensity = 15
s.ReferTo = ZOSAPI.Analysis.Settings.RMS.ReferTo.Centroid
spot.ApplyAndWaitForCompletion()
results = spot.GetResults()
# results.SpotData has the statistics; results.DataScatterPoints has the points
# WARNING: SpotData.GetRMSSpotSizeFor units are not documented and may match
# the GUI's auto-scaled display (often µm when LensUnits=mm). For unit-strict
# reporting, prefer the RSCE / RSCH MFE operand below.
```

### Spot size with strict units (RSCE / RSCH operand)

`SpotData.GetRMSSpotSizeFor` and `GetGeoSpotSizeFor` return numbers whose units the CHM does not document. In practice they appear to track the GUI's auto-scaled display — when `LensUnits = mm`, the GUI's Standard Spot plot shows µm and `GetRMSSpotSizeFor` has been observed to return µm (one report) but also lens units (other reports). Do not guess. If you need a value that is *guaranteed* to be in lens units, build it on the merit function:

| Operand | Reference | Computes |
|---|---|---|
| `RSCE` | Centroid | RMS spot radius (always lens units, all wavelengths) |
| `RSCH` | Chief ray | RMS spot radius referenced to chief ray |
| `RSRE` | — | RMS y-only spot radius (centroid) |

```python
MFE = TheSystem.MFE
op = MFE.AddOperand()
MOT = ZOSAPI.Editors.MFE.MeritOperandType
op.ChangeType(MOT.RSCE)
# RSCE cell layout: GetCellAt(2)=Surf, (3)=Wave, (4)=Hx, (5)=Hy, (6)=Px, (7)=Py
# Probe with operand_help.md if unsure — cell layout varies per operand.
op.GetCellAt(2).IntegerValue = 0           # 0 = image surface
op.GetCellAt(3).IntegerValue = 0           # 0 = all wavelengths (polychromatic)
op.GetCellAt(4).DoubleValue = 0.0          # Hx (normalized)
op.GetCellAt(5).DoubleValue = 1.0          # Hy = 1.0 → max field
rms_lens_units = op.Value                  # always in LensUnits — guaranteed
MFE.RemoveOperandAt(op.Row)                # cleanup (or DeleteAllRows if MFE was scratch)

# Convert to whatever output units you want, knowing the input units:
rms_um = rms_lens_units * 1000.0           # only valid if LensUnits == Millimeters
```

This pattern is the canonical way to report spot size from the API — it bypasses the analysis layer's auto-scale entirely. RSCE / RSCH are documented as returning RMS radius in lens units in the operand help (CHM `MeritOperandType.RSCE`).

### Ray Fan
```python
fan = TheSystem.Analyses.New_RayFan()
fan.ApplyAndWaitForCompletion()
results = fan.GetResults()
# Iterate results.NumberOfDataSeries (one series per field × wave × X/Y plane)
```

### Cardinal Points (EFL / FFL / BFL / principal planes)

Replaces the manual "insert lens, ray-trace PARY, reverse-lens, ray-trace PARY again" workaround for measuring focal lengths. One analysis call returns all cardinal points for a specified surface range and wavelength.

```python
cp = TheSystem.Analyses.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.CardinalPoints)
s = cp.GetSettings()
s.FirstSurface = first_lens_surf       # int — start of the lens (first glass surface)
s.LastSurface = last_lens_surf         # int — last glass surface (back vertex)
s.Wavelength.SetWavelengthNumber(1)    # IAS_Wavelength selector
cp.ApplyAndWaitForCompletion()

# CardinalPoints has no typed result container — use the text report
import os
report_path = os.path.join(TheApplication.SamplesDir, 'tmp_cardinal.txt')
cp.GetResults().GetTextFile(report_path)
with open(report_path, 'r') as f:
    text = f.read()
cp.Close()
# Text report lists: focal planes (Front, Back), principal planes (P, P'),
# anti-principal planes, nodal planes (N, N'), anti-nodal planes.
# Object-space distances are measured from FirstSurface (so Front Focal
# distance = FFL). Image-space distances from LastSurface (Back Focal
# distance = BFL). EFL is derivable from principal-plane positions; some
# versions also print it directly.
```

**When to use this instead of `MFE.GetOperandValue(EFFL, ...)` or PARY ray tracing:**
- You need FFL or principal-plane positions (no MFE operands for these).
- You're characterizing a catalog lens for `bfl_mm` / `ffl_mm` design parameters.
- You'd otherwise be tempted to reverse the lens to get FFL — `InsertLensSeq(reverseSurfGeom=True)` is silently ignored in v24.1 (see `system-and-application.md`) and manual reversal via reading-and-rebuilding surfaces only handles `Radius/Thickness/Material/Conic` (drops aspheric `ParN`, semi-diameters, coatings → wrong FFL for non-singlets).

**Caveat from the CHM:** results are unreliable if the surface range contains coordinate breaks or non-centered optics. For a CB-flipped lens (`sequential-design.md` § "Coordinate Break pairs"), compute the cardinal points of the *original* range before flipping; the flip just relabels front↔back, it doesn't change EFL.

### NSC 3D Layout (and any other analysis as an image)

The 3D layout is OpenGL-rendered, so `GetDataGridRgb(0)` returns `None` and you can't pull pixels through the data containers. **Use `analysis.ToFile()` instead** — it's the universal "save analysis output to a file" method on the `IA_` base interface, and it works on every analysis including layouts:

```python
la = TheSystem.Analyses.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.NSC3DLayout)
la.ApplyAndWaitForCompletion()
la.ToFile(r'C:\path\layout.JPG', False, False)         # image (JPG / BMP / EMF / WMF / PDF; PNG varies by version)
la.GetResults().GetTextFile(r'C:\path\layout.txt')      # text dump if you want it too
la.Close()
```

The `ToFile` path is fast and zero-config but uses **whatever camera angle / pixel size the user last left in the GUI** for that analysis. For programmatic control of view, image size, ray rendering, etc., use the dedicated layout-export tool below.

## NSC 3D Layout image export (programmatic, with view control)

**Requires Interactive Extension mode — does NOT work in Standalone.** The image-export tools depend on the GUI's render context; in Standalone they silently no-op (`IsValidFileName` may even return True, but no file is written). Connect via `ConnectAsExtension(0)` against a running OpticStudio with `Programming → Interactive Extension` enabled. See **`interactive-extension.md`** for the connection class, the agent ↔ user handoff prompt, and a "do most work in standalone, switch to IE only for the artifact pass" hybrid pattern.

Once connected via IE, use **`TheSystem.Tools.Layouts.OpenNSC3DLayoutExport()`** instead of `analysis.ToFile()` — set the camera angle, choose JPG/BMP/PNG, pick pixel resolution, dump straight to disk. This is a `ZOSAPI.Tools.Layouts.INSC3DLayoutExport` (a `ISystemTool`, not an `IA_` analysis), so the lifecycle is `Open → set props → RunAndWaitForCompletion → Close`. The image is written during `Run` if `SaveImageAsFile=True` and `OutputFileName` points somewhere valid (must be inside `TheApplication.ImagesDir` — see Gotchas below).

```python
import os
import shutil

def save_3d_layout(TheSystem, ZOSAPI, TheApplication, output_path, side_view=True,
                   pixel_width=1600, pixel_height=1000,
                   split_rays=False, scatter_rays=False, use_polarization=False):
    """Render and save the NSC 3D Layout as an image (PNG / JPG / BMP).

    Pass the same `ZOSAPI` and `TheApplication` handles you got from
    PythonStandaloneApplication (so enums resolve in the same .NET load context
    AND so we can find `ImagesDir`). side_view=True selects the XZ camera
    viewpoint (looking down +Y) — the standard optical-bench side view.

    Why `TheApplication`: OpticStudio's image-export tools restrict
    `OutputFileName` to paths inside `TheApplication.ImagesDir`. Trying to
    write anywhere else (project folder, OneDrive path, …) silently sets
    `IsValidFileName=False` with no error message. Workaround: render to
    `ImagesDir/basename(output_path)` then `shutil.copy2` to the requested
    `output_path`.
    """
    Layouts = ZOSAPI.Tools.Layouts                 # CameraViewpointOptions, etc. live here

    final_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(final_dir, exist_ok=True)
    images_dir = TheApplication.ImagesDir
    temp_path  = os.path.join(images_dir, os.path.basename(output_path))

    # NB: lives on TheSystem.Tools.Layouts (ILayouts), NOT TheSystem.Tools (IOpticalSystemTools)
    exp = TheSystem.Tools.Layouts.OpenNSC3DLayoutExport()
    try:
        # File output (must be inside ImagesDir or IsValidFileName is False)
        exp.SaveImageAsFile = True
        exp.OutputFileName  = temp_path            # extension picks format: .PNG / .JPG / .BMP
        exp.OutputPixelWidth  = pixel_width
        exp.OutputPixelHeight = pixel_height

        # Camera viewpoint — preset enum OR explicit angles
        if side_view:
            exp.SetCameraViewpoint(Layouts.CameraViewpointOptions.XZ)   # see XZ plane, look down +Y
        else:
            exp.SetCameraViewpoint(Layouts.CameraViewpointOptions.Isometric)
        # For an arbitrary angle (degrees), set the three properties directly instead:
        # exp.CameraViewpointAngleX = 0.0
        # exp.CameraViewpointAngleY = 90.0
        # exp.CameraViewpointAngleZ = 0.0

        # Ray rendering
        exp.RayTrace        = Layouts.RayTraceOptions.UseRays
        exp.UsePolarization = use_polarization
        exp.SplitNSCRays    = split_rays
        exp.ScatterNSCRays  = scatter_rays
        exp.ColorRaysBy     = Layouts.ColorRaysByNSCOptions.SourceNumber

        # Line thickness (Thinnest / Thin / Standard / Thick / Thickest)
        exp.SurfaceLineThickness = Layouts.LineThicknessOptions.Standard
        exp.RaysLineThickness    = Layouts.LineThicknessOptions.Thin

        # Configurations
        exp.ConfigurationCurrent = True            # render only the active config

        if not exp.IsValidFileName:
            raise RuntimeError(f"OpticStudio rejected output path even inside "
                               f"ImagesDir: {temp_path}")
        if not exp.RunAndWaitForCompletion():
            raise RuntimeError(f"NSC 3D Layout export failed: {exp.ErrorMessage}")
    finally:
        exp.Close()                                # always close — leaks handles otherwise

    if not os.path.isfile(temp_path):
        raise RuntimeError(f"Tool reported success but no file at {temp_path}")
    shutil.copy2(temp_path, output_path)            # copy out of ImagesDir to requested location
    return output_path
```

### Settings reference

| Property | Purpose | Notes |
|---|---|---|
| `SaveImageAsFile` (bool) | Must be `True` to actually write the file | default `False`; setting `OutputFileName` alone is silently a no-op |
| `OutputFileName` (str) | Absolute path; extension chooses format | `.PNG`, `.JPG`, `.BMP` all work; `.JPG` is the safest fallback |
| `OutputPixelWidth` / `OutputPixelHeight` (int) | Pixel size of the saved image | independent of GUI window size |
| `IsValidFileName` (bool, read-only) | Pre-check after setting `OutputFileName` | check before `Run` to fail fast on bad paths |
| `SetCameraViewpoint(CameraViewpointOptions)` | View preset: `Isometric`, `XY`, `YZ`, `XZ` | `XZ` = side view (look down +Y, see optical bench); `XY` = top; `YZ` = end-on |
| `CameraViewpointAngleX/Y/Z` (double, deg) | Arbitrary camera rotation | set after `SetCameraViewpoint` to override the preset |
| `RayTrace` (`RayTraceOptions`) | `UseRays` / `LightningTraceTrueColor` / `LightningTraceAvgWavelength` | `UseRays` uses the source's `NumberOfLayoutRays` |
| `UsePolarization` / `SplitNSCRays` / `ScatterNSCRays` (bool) | Match your `OpenNSCRayTrace` settings for consistency | rays drawn here are independent of any prior `RunAndWaitForCompletion` ray trace |
| `ColorRaysBy` (`ColorRaysByNSCOptions`) | `SourceNumber` / `WaveNumber` / `ConfigNumber` / `Wavelength` / `SegmentNumber` | `SourceNumber` is most legible for multi-source scenes |
| `SurfaceLineThickness` / `RaysLineThickness` (`LineThicknessOptions`) | `Thinnest`...`Thickest` | use `Thin` for rays + `Standard` for surfaces in busy scenes |
| `ConfigurationAll` / `ConfigurationCurrent` (bool) | What to draw in multi-config systems | mutually exclusive — set one |
| `RayDatabase` (str) | Path to a saved `.ZRD` to render exact rays | leave blank to ray-trace fresh from sources |
| `Filter` (str) | Standard NSC ray filter string | applies whether or not `RayDatabase` is set |

### Gotchas

- **`OutputFileName` must be inside `TheApplication.ImagesDir`.** Any other path (project folder, OneDrive folder, `C:\temp`, etc.) sets `IsValidFileName=False` with no diagnostic — the tool just no-ops. The recipe above renders to ImagesDir then `shutil.copy2`-s out. Don't try to be clever and pass an arbitrary path; the API silently rejects it.
- **Lives on `TheSystem.Tools.Layouts`**, not `TheSystem.Tools`. `Tools` returns `IOpticalSystemTools`, which has a `Layouts` property returning `ILayouts`, which has `OpenNSC3DLayoutExport()`. Same for `Open3DViewerExport`, `OpenShadedModelExport`, `OpenCrossSectionExport`, `OpenNSCShadedModelExport` — all on `Tools.Layouts`. Calling `Tools.OpenNSC3DLayoutExport()` directly raises `AttributeError`.
- **No `ToFile` here.** This is a `ISystemTool`, not an `IA_` analysis — the file is written by `RunAndWaitForCompletion()` because `SaveImageAsFile=True`. Calling `.ToFile(...)` would `AttributeError`.
- **Output directory must exist.** Both the ImagesDir temp file and the final copy destination — `os.makedirs(final_dir, exist_ok=True)` first.
- **Always `Close()`** the tool (use `try/finally`); each open tool holds a window handle in OpticStudio.
- **`SaveImageAsFile=False`** silently does nothing useful from a script. Default is `False`.
- **Camera presets are first**, angles override. Call `SetCameraViewpoint(...)` then optionally tweak `CameraViewpointAngleX/Y/Z` — the order matters; the preset resets the angles.
- **Side view = `XZ`.** The user-facing language "looking along Y, seeing the XZ plane" maps to `CameraViewpointOptions.XZ`. `YZ` would be looking down +X (end-on view).
- The shaded-model variant is **`Tools.Layouts.OpenNSCShadedModelExport()`** → `INSCShadedModelExport`, with the same lifecycle plus extra `BackgroundOptions`, `BrightnessOptions`, `OpacityOptions`, and `NumberSegmentsOptions` (cylinder/sphere tessellation). Use it when you want filled surfaces instead of wire-frame rays.
- Sequential equivalents: `Tools.Layouts.Open3DViewerExport()` → `I3DViewerExport`, `Tools.Layouts.OpenShadedModelExport()` → `IShadedModelExport`, `Tools.Layouts.OpenCrossSectionExport()` → `ICrossSectionExport`. All live under `Tools.Layouts` (= `ZOSAPI.Tools.ILayouts`) and follow the same `OpenX → set props → RunAndWaitForCompletion → Close` pattern.

For the simpler (but less controllable) `analysis.ToFile()` path on `AnalysisIDM.NSC3DLayout`, see the previous subsection. For pixel-exact custom rendering with matplotlib / plotly / pyvista (camera angle, ray colors, overlays not exposed by the export tool), `Tools.OpenShadedModelVisualizationExport` returns the scene as a triangle list — see `verification.md`.

## Detector Viewer (NSC irradiance map)

The Detector Viewer renders a 2D irradiance map of an NSC detector as an analysis (so you get a saveable image and the same `DataGrid` numeric grid you'd extract via `NCE.GetAllCoherentDataSafe`). Use it to verify uniformity / spot size at the target detector after a build script repositions lenses, **complementing** the raw-pixel `data-extraction.md` path with a visual artifact a human can review.

The interface is **`ZOSAPI.Analysis.Settings.RayTracing.IAS_DetectorViewer`** (verified — confusingly under `RayTracing`, not `Detector`). Confirmed properties: `Detector`, `Surface`, `DataType`, `ShowAs`, `Scale`, `Smoothing`, `PlotScaleMinimum`, `PlotScaleMaximum`, `RowCol`, `Filter`, `RayDatabaseFilename`, `Configuration`, `Contrast`, `MaxSpatialFrequency`, `OutFile`, `Zplane`, `AngleList`, `SymbolType`, `SuppressFrame`. Helper methods: `GetDetectorObjectNumber(idx)`, `GetDetectorName(idx)`, `IsValidDetector(N)`, `NumberOfDetectorsOnSurface`, `NumberOfShowAsTypes`.

Note that **after every parameter change you must run a fresh `OpenNSCRayTrace`** for the detector to actually contain data — the viewer reads whatever is currently on the detector object.

```python
def render_detector(TheSystem, ZOSAPI, zos, det_obj_num, output_path,
                    show_as='FalseColor', scale='Linear'):
    """Trace, render the detector as an image, and return the numeric grid."""
    import os, numpy as np

    DVSAT = ZOSAPI.Analysis.DetectorViewerShowAsTypes      # FalseColor / GreyScale / TrueColor / CrossSection / etc.
    DVSDT = ZOSAPI.Analysis.DetectorViewerShowDataTypes    # IncoherentIrradiance / CoherentIrradiance / CoherentPhase

    # 1) Fresh trace — the viewer shows whatever is currently on the detector
    rt = TheSystem.Tools.OpenNSCRayTrace()
    rt.SplitNSCRays = False; rt.ScatterNSCRays = False
    rt.UsePolarization = True; rt.IgnoreErrors = True
    rt.ClearDetectors(0); rt.RunAndWaitForCompletion(); rt.Close()

    # 2) Detector Viewer analysis
    dv = TheSystem.Analyses.New_Analysis(ZOSAPI.Analysis.AnalysisIDM.DetectorViewer)
    s = dv.GetSettings()
    s.Surface  = 1                                          # NSC group surface (1 if program mode is NSC)
    s.Detector = det_obj_num                                # object # of the detector
    s.DataType = DVSDT.IncoherentIrradiance                 # see caveat in data-extraction.md
    s.ShowAs   = getattr(DVSAT, show_as)                    # 'FalseColor' default; 'CrossSection' for 1D slice
    s.Smoothing = 0                                         # 0 = no smoothing
    # PlotScaleMinimum / PlotScaleMaximum default to 0 = auto-scale; set both to fix the colorbar
    dv.ApplyAndWaitForCompletion()

    # 3) Save the rendered image
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    dv.ToFile(output_path, False, False)                    # JPG / BMP / EMF / WMF / PDF

    # 4) Pull the numeric grid (same one the viewer is rendering)
    grid = dv.GetResults().GetDataGrid(0)
    arr = np.flipud(np.array(zos.reshape(grid.Values,
                                         grid.Values.GetLength(0),
                                         grid.Values.GetLength(1))))
    dv.Close()
    return arr                                              # 2D numpy array of irradiance
```

### When to use which path

| Goal | Path |
|---|---|
| Visual artifact for human review (PNG/JPG of irradiance map) | This recipe (`dv.ToFile(...)`) |
| Per-pixel numeric grid for numpy postprocessing | Either this recipe's `GetDataGrid(0)`, **or** the lower-level `NCE.GetAllCoherentDataSafe(...)` (faster, no analysis window) — see `data-extraction.md` |
| Coherent E-field (real / imag / phase) | `NCE.GetAllCoherentDataSafe` only — `DataType=CoherentIrradiance/CoherentPhase` on the viewer is broken in v24.1 (returns the same grid as `IncoherentIrradiance`); see `data-extraction.md` |
| Total power (single number) | `NCE.GetDetectorData(det, 0, 0, 0)` — pixel=0 = total (−1 = max pixel, not total); no analysis needed |

### Spot size / RMS at an NSC detector

OpticStudio doesn't expose a clean "Standard Spot for NSC" analysis (the spot tools target sequential systems). Two options to compute spot statistics from a target detector after the relay:

1. **NSDD operand readout** with the `Pix#=-9/-10/-11` and `Data#=0` rows from `references/optimization.md`'s NSC Operands table — these return weighted RMS radial / x / y distances of the flux distribution about its centroid. Add them to the MFE and read via `op.Value`, no analysis run needed.
2. **Compute in numpy from the `DataGrid`** above:
   ```python
   ny, nx = arr.shape
   x = (np.arange(nx) - nx/2 + 0.5) * grid.Dx
   y = (np.arange(ny) - ny/2 + 0.5) * grid.Dy
   X, Y = np.meshgrid(x, y)
   tot = arr.sum()
   xc = (X*arr).sum() / tot
   yc = (Y*arr).sum() / tot
   rms_r = np.sqrt(((((X-xc)**2 + (Y-yc)**2) * arr).sum()) / tot)
   ```

The numpy path is unambiguous and lets you mask the centroid region or apply a power threshold before computing RMS — useful when you want spot size of just the on-axis lobe and not the diffraction halo.

### NSC ray trace: tool vs. analysis

`Tools.OpenNSCRayTrace()` (`INSCRayTrace`, see `references/conventions.md`) is the **one-shot trace operation** — it populates the detectors and that's the only ray-trace path the API exposes. There is **no separate "NSC ray trace" analysis-window object** that visualizes individual rays through `Analyses.New_Analysis(...)`; ray visualization happens via the **NSC 3D Layout** analysis (which renders rays from the most recent trace) and via the `OpenNSC3DLayoutExport` tool covered above. If you need per-ray intersection lists, use the **ZRD ray database** (`references/ray-database.md`).

## Pattern: connect → load → analyze

For just inspecting an existing design without modifying it:
```python
zos = PythonStandaloneApplication()
TheSystem = zos.TheSystem
TheSystem.LoadFile(r'C:\path\design.zos', False)
mtf = TheSystem.Analyses.New_FftMtf()
mtf.ApplyAndWaitForCompletion()
# ... extract data ...
mtf.Close()
del zos; zos = None
```
