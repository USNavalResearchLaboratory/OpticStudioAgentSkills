# Sequential Mode: LDE, SystemData, Surfaces

Sequential mode (Lens Data Editor, LDE) is for systems where light travels through a defined sequence of surfaces, each one in order. Use it for lens design, telescope/microscope objectives, spectrometers, and most imaging optics. Use NSC mode (`nsc-objects.md`) only when the geometry has fold mirrors, multiple beam paths, scattering, or a free-form 3D arrangement.

The same `PythonStandaloneApplication` boilerplate works — just create the system as `SystemType.Sequential` (or call `TheSystem.New(False)` which defaults to sequential).

## LDE basics

```python
TheLDE = TheSystem.LDE
TheLDE.InsertNewSurfaceAt(2)              # insert new surface BEFORE index 2
surf = TheLDE.GetSurfaceAt(2)             # 1-based; image plane is at NumberOfSurfaces
TheLDE.NumberOfSurfaces                   # total count
TheLDE.RemoveSurfaceAt(idx)
```

Surface indexing: 1 is the object (or stop, depending on the system); the image plane is the last surface (index `NumberOfSurfaces`). Surfaces are inserted *before* the given index.

### Surface properties

The most-used properties on `ISurface` (set them directly — these are real .NET properties, no `__implementation__` dance needed for these particular ones):

```python
surf.Thickness = 5.0           # mm
surf.Radius = 100.0            # mm; 0 = flat
surf.Material = 'N-BK7'        # any glass in a loaded catalog
surf.Conic = 0.0
surf.SemiDiameter = 12.5
surf.Comment = 'Front of crown'
surf.IsStop = True             # set this surface as the stop — boolean, NOT 1 (pythonnet 3.0+ rejects int → bool conversion)
```

To make a property variable for optimization, work through the *cell*:
```python
surf.RadiusCell.MakeSolveVariable()
surf.ThicknessCell.MakeSolveVariable()
```

### Surface types

By default, an inserted surface is `Standard`. To change type:
```python
OT_LDE = ZOSAPI.Editors.LDE.SurfaceType
settings = surf.GetSurfaceTypeSettings(OT_LDE.EvenAspheric)
surf.ChangeType(settings)
```

Common surface types (v24.1 — verify with `check_namespace.py --audit` if a name fails): `Standard`, `EvenAspheric`, `OddAsphere`, `ExtendedAsphere`, `ExtendedOddAsphere`, `Toroidal`, `Paraxial`, `CoordinateBreak`, `DiffractionGrating`, `Binary1`/`Binary2`/`Binary3`/`Binary4`, `Fresnel`/`CylinderFresnel`/`ExtendedFresnel`/`GeneralizedFresnel` (no `Fresnel1`/`Fresnel2` — flat namespace), `GridSag`, `ZernikeStandardSag`/`ZernikeFringeSag`/`ZernikeAnnularPhase`/etc., `UserDefined`. **API-name traps**: `EvenAspheric` (not `EvenAsphere`); `Binary1` (not `BinaryOptic1`); `ChebyShv` is an actual API spelling (no `e` after `y`); both `CylinderFresnel` and `CylinderFrensel` exist as aliases. Each surface type has its own typed parameter properties — discover them on a fresh surface with `dir(surf.get_SurfaceData().__implementation__)` (same trick as for NSC objects).

**Integer-typed parameter cells.** Most surface parameter cells store doubles (radii, thicknesses, coefficients), but a few are integer-typed and reject `DoubleValue`. Notably **the CoordinateBreak surface's "Order" cell** (controls whether the CB applies before or after the surface) — set with `cell.IntegerValue = 0` (decenter then tilt) or `1` (tilt then decenter), not `DoubleValue`. Same defensive try/fallback pattern as MCE cells (see `multi-config.md` § "Cell value type depends on the operand"). When in doubt, read `cell.DoubleValue` first; if it raises, the cell is integer-typed.

### Black Box Lens surfaces (`.ZBB` files — proprietary "playback" prescriptions)

Vendors and design houses often distribute optimized designs as **Zemax Black Box (.ZBB)** files — encrypted prescription data that traces correctly as a sequence of surfaces but hides the internal radii, thicknesses, glass, asphere coefficients, and parameters. Rays go in, rays come out as if the original surfaces were there; the user (or your script) cannot inspect or modify the hidden data. Common for off-the-shelf complex assemblies (zoom lenses, machine-vision objectives, OEM imaging systems).

**Loading a .ZBB into a sequential design** uses the `BlackBoxLens` surface type. Two non-obvious bugs to avoid:

1. **`ISurfaceTypeSettings.Filename` does NOT work for BlackBoxLens** — assigning to it throws `NullReferenceException`. The typed setter is on the **`ISurfaceBlackBoxLens` surface-data implementation** (`BlackBoxLensFilename`), reachable only after `ChangeType`.
2. **The surface `Comment` field is load-bearing, not cosmetic.** Zemax persists the BB filename through the comment (inspect any vendor `.ZMX`: `SURF 2 COMM VendorLens.ZBB`). **Do not overwrite `surf.Comment`** with descriptive text — the next `LoadFile` will look for a `.ZBB` named after whatever string you put there and fail. Either leave the comment alone, or set it to exactly the filename.

```python
ST = ZOSAPI.Editors.LDE.SurfaceType

# 1) Insert a fresh surface where the black box belongs
N = some_index_between_two_real_surfaces
TheLDE.InsertNewSurfaceAt(N)
surf = TheLDE.GetSurfaceAt(N)

# 2) Convert to BlackBoxLens first (do NOT set Filename on the bare settings —
#    it throws NRE for this surface type).
bb_settings = surf.GetSurfaceTypeSettings(ST.BlackBoxLens)
surf.ChangeType(bb_settings)

# 3) Set the .ZBB via the typed surface-data implementation (resolved from
#    <TheApplication.ZemaxDataDir>\BlackBoxes\ — filename only, no path).
filename = 'MyVendorLens.ZBB'                            # .ZBB extension required
surf.get_SurfaceData().__implementation__.BlackBoxLensFilename = filename

# 4) Do NOT rewrite surf.Comment with descriptive text — Zemax persists the
#    .ZBB filename through Comment and the next LoadFile will fail. Leave it
#    alone or set it to the filename verbatim:
# surf.Comment = filename   # safe — matches what BlackBoxLensFilename wrote

# 5) Validate. UpdateStatus() returns '' on success, diagnostic string otherwise.
err = TheSystem.UpdateStatus()
if err: raise RuntimeError(f"BB load failed: {err}")
```

**Discovery:** `surf.get_SurfaceData().__implementation__.GetBlackBoxLensFilenameAt(i)` enumerates available `.ZBB` files in the BlackBoxes folder — useful for verifying availability before assigning. Both methods live on `ISurfaceBlackBoxLens` (probe with the script for full property list).

**The BlackBoxes folder** is `<TheApplication.ZemaxDataDir>\\BlackBoxes` (per-user). Drop the vendor's `.ZBB` there before scripting — paths are filename-only and OpticStudio resolves them from that folder.

**Constraints when using a BB surface** (CHM rules — the API will not enforce all of these but the trace silently misbehaves if violated):

| Rule | Why it matters |
|---|---|
| Cannot be the object (surface 0) or image (last surface) | Insert a Standard dummy in front if the BB is the first real surface and the object is at infinity |
| Cannot have a glass type on the BB surface itself | `surf.Material = ''` (the surrounding air); the surrounding surfaces may have catalog glasses but **not** Model or Table glasses |
| Thickness / aperture type / aperture size are baked into the file | Setting `surf.Thickness`, `surf.SemiDiameter`, etc. has no effect after `ChangeType`; the values are read from the encrypted prescription |
| The stop may BE the BB but cannot live INSIDE it | Use two consecutive Black Boxes split at the stop if the original design's stop was internal |
| BB only works at the mirror-count parity it was created for | Don't add fold mirrors before a BB unless the BB was made with that mirror parity — the trace returns wrong results silently. Avoid `OpenAddFoldMirror` / `OpenMakeDoublePass` near a BB. |
| Physical Optics Propagation, Skew Gaussian Beam, and thermal analysis don't work through BB | The encrypted surfaces don't expose the per-surface data those features need. Ray-based features (spot, MTF, PSF, ray fan, OPD fan, image simulation) all work. **Workaround for POP:** start POP past the BB via `StartSurface` + a vendor-supplied or synthesized `.ZBF` of the post-BB beam. Four-strategy table in `physical-optics.md` § "Propagating POP past unsupported surfaces". |
| Coatings inside a BB must be standard or **encrypted (.ZEC)** | Ideal/table coatings unsupported. The exporter auto-prepends `ZEC_` to coating names. The `.ZEC` files must accompany the `.ZBB` (typically shipped together in a ZAR archive). |
| Only the current configuration is exported | Multi-config systems need one BB per config; switch them per config via an `MCOM` operand in the MCE |

**Export is GUI-only.** The API has no `OpenExportToBlackBox` tool — black-box creation is done interactively from File → Export → Zemax Black Box. The API can only *consume* existing `.ZBB` files. (There is an `OpenExportToSpeosWhitebox` tool for the Speos format, which is unrelated.)

### Using a .ZBB in non-sequential mode

**There is no NSC `BlackBoxLens` object type.** NSC has no native `.ZBB` loader. To use a BB design inside an NSC scene, build a sequential system with the BB surface, then embed it as an NSC group:

```python
# 1) Build a sequential playback system around the BB
TheSystem = TheApplication.CreateNewSystem(ZOSAPI.SystemType.Sequential)
# ... insert standard surfaces + a BlackBoxLens surface as above ...

# 2) Convert the BB-containing surface range into an NSC group (preserves prescription)
n_surf = TheSystem.LDE.NumberOfSurfaces
tool = TheSystem.Tools.OpenConvertToNSCGroup()
tool.FirstSurface, tool.LastSurface = 1, n_surf - 2     # exclude OBJ + IMA
tool.ConvertFileToNSC = True                             # pure NSC, OR False for a group inside sequential
tool.RunAndWaitForCompletion(); tool.Close()
```

The BB's encrypted prescription is preserved through the conversion — the resulting NCE will show a single object that traces correctly without exposing the design. Group it under a Null Object parent if you need to move it as a unit (see `conventions.md` § "Grouping multi-element parts under a Null Object parent"). This is the same pattern as the `.zmx` → NSC seed conversion above, with a Black Box surface in the middle instead of a vendor prescription.

### Coordinate Break pairs: the sequential analog of NSC grouping

Sequential mode has no native `RefObject`-style grouping, but a **pre-CB / lens / post-CB pair** is the functional equivalent for rigid-body manipulations (tilt, decenter, flip). The pre-CB transforms the coordinate frame into the lens-local frame; the surfaces between them inherit that transformation; the post-CB optionally restores the original axis for downstream surfaces.

**Default to manual radius reversal — not CB pairs — for the common case of flipping one rotationally symmetric catalog lens.** See `system-and-application.md` § "Two InsertLensSeq traps" for the `build_reversed_lens` helper. That helper is the canonical pattern: the geometry comes out at the expected Z range, the 3D Layout renders cleanly, and there are no pythonnet enum traps. The CB-pair pattern below is for the narrower cases listed in the next paragraph.

**When the CB pair IS the right tool:**
- You need a **runtime-toggleable** flip driven by an MCE PRAM operand (forward-vs-reversed lens characterization in one file, alignment-tolerance studies, zoom alignment).
- You need a **non-180° tilt** or **decenter** of a rigid surface group — radius reversal only handles the 180° flip case; CBs handle arbitrary rigid-body transforms.
- The element is **non-rotationally-symmetric** (toroidal, biconic, cylindrical) — radius reversal alone is wrong; the surface must be physically rotated.
- The surfaces between the CBs **must remain unmodified** for some other reason (e.g. they're variables in an optimization, or they carry coatings/apertures that the rebuild path drops).

**Known failure modes of the CB-pair flip** (verified v24.1):
- **Z-shift trap.** With pre-CB TiltY = 180°, the lens propagates along the rotated local +Z axis, occupying `[z_anchor − CT, z_anchor]` in *global* Z rather than `[z_anchor, z_anchor + CT]`. Downstream spacings end up off by `CT` (the lens center thickness) unless explicitly compensated — typically by reducing the post-CB's Thickness by `CT`, or by adjusting the pre-CB's Thickness anchor. Verify by tracing a chief ray and printing the global Z of each surface; do not trust the LDE-relative numbers.
- **3D Layout rendering.** When a user toggles the pre-CB's Par4 in the GUI, the renderer often draws the flipped element as a distorted or misplaced shape — the ray trace is still correct, but the visualization misleads anyone debugging in the GUI. Document the expected behavior in the surface Comments so a human reader doesn't chase a phantom bug.
- **`_S_SurfacePickup.Column` is enum-typed, not int.** Under pythonnet 3.0+, setting `sp.Column = 6` raises `TypeError: int can not be converted to Enum implicitly`. The property expects a `ZOSAPI.Editors.SurfaceColumn` enum value (or whatever the install names it — probe to confirm). See the pickup-solve example below for the wrapped form.

For the simple "flip a rotationally symmetric catalog lens once at build time" case, skip this section entirely and use `build_reversed_lens`.

The CB-pair pattern, when you actually need it:

```python
ST = ZOSAPI.Editors.LDE.SurfaceType

def insert_flipped_lens(TheSystem, chosen, at_idx, ignoreObject=False):
    """Insert a catalog lens with a pre-CB tilt of 180° so the lens traces reversed.

    Layout after this call:
        at_idx        : pre-CB  (TiltAboutY = 180.0)
        at_idx+1..M   : the lens surfaces (radii unchanged, but the trace
                        sees them reversed because the frame is flipped)
        M+1           : post-CB (TiltAboutY = -180.0, undoes the flip for
                        downstream surfaces)
    """
    LDE = TheSystem.LDE

    # 1) Pre-CB
    LDE.InsertNewSurfaceAt(at_idx)
    pre = LDE.GetSurfaceAt(at_idx)
    pre.ChangeType(pre.GetSurfaceTypeSettings(ST.CoordinateBreak))
    # ParN cell layout on CoordinateBreak: Par1=DecX, Par2=DecY,
    # Par3=TiltX, Par4=TiltY, Par5=TiltZ, Par6=Order
    pre.GetCellAt(7).DoubleValue = 180.0          # Par4 = TiltAboutY
    pre.Comment = 'flip pre-CB'

    # 2) Insert the catalog lens immediately after
    ok = chosen.InsertLensSeq(atSurface=at_idx + 1, ignoreObject=ignoreObject,
                              reverseSurfGeom=False)
    if not ok: raise RuntimeError("InsertLensSeq returned False")
    LDE.GetSurfaceAt(at_idx + 1).Thickness = 0.0  # clear leading-shoulder Thickness=inf

    # 3) Post-CB to undo the flip for whatever follows
    last_lens_idx = LDE.NumberOfSurfaces - 2       # last surface before IMA
    LDE.InsertNewSurfaceAt(last_lens_idx + 1)
    post = LDE.GetSurfaceAt(last_lens_idx + 1)
    post.ChangeType(post.GetSurfaceTypeSettings(ST.CoordinateBreak))
    post.GetCellAt(7).DoubleValue = -180.0         # cancel the pre-CB tilt
    post.Comment = 'flip post-CB'

    err = TheSystem.UpdateStatus()
    if err: raise RuntimeError(f"flipped-lens system invalid: {err}")
```

CB `Order` cell defaults to `0` (decenter then tilt) which is what you want here. Same pattern works for tilting/decentering a multi-element catalog part as a unit — much cleaner than computing per-surface coordinates by hand, and it preserves *every* attribute of the original surfaces (aspheres, conic, coating, semi-diameter, ParN data) because the surfaces themselves are unchanged. **This is the equivalent of NSC's Null Object parent in sequential mode.**

The 180°-flip case is geometrically correct for rotationally symmetric lenses and matches what happens physically when you unscrew a lens cell and reinsert it backwards. For non-rotationally-symmetric elements (toroidal, biconic, cylindrical), test the result against expected behavior before trusting it.

**Tie post-CB to pre-CB with a pickup solve so the two never drift.** Setting `pre.Par4 = 180` and `post.Par4 = -180` by hand means both cells have to be updated together — easy to flip one and forget the other, especially when a downstream agent or a human editing in the GUI changes only the pre-CB. Wire the post-CB's TiltY as a `SurfacePickup` from the pre-CB with scale factor `-1` so it tracks automatically. After this, flipping the lens is one cell edit; the GUI shows a `P` flag on the post-CB cell indicating it's a pickup.

```python
SolveType        = ZOSAPI.Editors.SolveType
SurfaceColumn    = ZOSAPI.Editors.LDE.SurfaceColumn    # PICKUP source-column enum — see note below

post_par4 = post.GetCellAt(7)                                  # Par4 = TiltAboutY
solve = post_par4.CreateSolveType(SolveType.SurfacePickup)
sp = solve._S_SurfacePickup
sp.Surface = pre.SurfaceNumber                                 # source surface = pre-CB
sp.ScaleFactor = -1.0                                          # negate
sp.Column = SurfaceColumn.Par4                                 # enum-typed — bare int raises TypeError
sp.Offset = 0.0
post_par4.SetSolveData(solve)
```

**`_S_SurfacePickup.Column` is enum-typed under pythonnet 3.0+** — assigning a bare integer (`sp.Column = 6`) raises `TypeError: int can not be converted to Enum implicitly` and the solve never gets installed. The enum value is what binds; the underlying integer index is whatever the build assigns and you should not assume it. Probe the enum to find the right member if the name above isn't right for your install:

```python
import System
for v in System.Enum.GetValues(ZOSAPI.Editors.LDE.SurfaceColumn):
    print(int(v), str(v))
```

After installing the solve, sanity-check by writing the pre-CB and reading the post-CB: set `pre.GetCellAt(7).DoubleValue = 45.0` and confirm `post.GetCellAt(7).DoubleValue` reads `-45.0`. If it reads `0` or stale data, the enum value didn't match the Par4 column for this surface type — re-probe.

For a toggle a human will flip repeatedly (forward-vs-reversed lens characterization, alignment-tolerance studies), promote the pre-CB's Par4 to a multi-config operand (`MCOT.PRAM`, `Param1 = pre.SurfaceNumber`, `Param2 = 4`) with values `0.0` and `180.0` per config — see `multi-config.md`. The pickup carries the post-CB along automatically across configuration switches.

### Coatings

Each sequential surface has a coating field. Two equivalent ways to set it:

```python
surf = LDE.GetSurfaceAt(2)
surf.Coating = 'AR'                        # the convenient shortcut
surf.CoatingData.Coating = 'AR'            # equivalent; CoatingData also exposes more
```

The second form gives access to the full `ILDECoatingData` interface:

```python
cd = surf.CoatingData
list(cd.GetAvailableCoatings())            # all coatings in the loaded COATING.DAT
cd.NumberOfLayers                          # for inspecting a stacked coating
cd.GetLayerSettings(layer_idx)             # per-layer details
cd.SetAllExtinctionVariable()              # mark extinction coefs variable for optimization
```

For analyzing coating performance (R / T / A vs wavelength or angle) once it's applied:

```python
perf = surf.GetCoatingPerformanceData()    # ICoatingPerformanceData
# plus the Coatings Analyses framework. In v24.1 the combined "RTA" analysis
# was split into six separate AnalysisIDM values — R, T, A each vs angle and
# vs wavelength. Run the ones you need; the legacy names RTAvsWavelength /
# RTAvsAngle no longer exist.
AIDM = ZOSAPI.Analysis.AnalysisIDM
TheSystem.Analyses.New_Analysis(AIDM.ReflectionvsWavelength)
TheSystem.Analyses.New_Analysis(AIDM.TransmissionvsWavelength)
TheSystem.Analyses.New_Analysis(AIDM.AbsorptionvsWavelength)
TheSystem.Analyses.New_Analysis(AIDM.ReflectionvsAngle)
TheSystem.Analyses.New_Analysis(AIDM.TransmissionvsAngle)
TheSystem.Analyses.New_Analysis(AIDM.AbsorptionvsAngle)
# Also available: AIDM.InternalTransmissionvsWavelength (bulk material only).
```

**Default `COATING.DAT` only contains generic coatings**, not vendor-specific ones:

| Coating | Description |
|---------|-------------|
| `AR` | Single quarter-wave MgF2 — generic AR (~1.5% R) |
| `HEAR1`, `HEAR2` | High-efficiency multilayer AR (narrower band, lower R) |
| `WAR` | "W" broadband AR (half-wave LA2O3 + quarter-wave MgF2) |
| `METAL` | Thin aluminum, used to make 50/50 splitters |
| `NULL` | Zero-thickness placeholder (debugging) |
| `GAP` | Small air gap (for evanescent propagation studies) |

**Vendor coatings (Thorlabs A-type, B-type, V-coats; Edmund VIS-NIR; Newport AR.16; etc.) are NOT shipped with Zemax.** Three options when you need one:

1. **Approximate with the closest built-in.** For a Thorlabs A-coat (350-700 nm AR, R<0.5% per surface): `WAR` is the closest match qualitatively (broadband AR), though performance differs. Document the approximation in your design notes.

2. **Define the coating manually.** Edit `COATING.DAT` (text format; lives in `TheApplication.CoatingDir`) to add a `COAT` block listing the layer materials and quarter-wave-relative thicknesses, plus any new `MATE` material entries with index models. The format is documented in OpticStudio's "Coating File Data Syntax" help page. Reload via `MaterialCatalogs.AddCatalog` is NOT the right pattern — coatings reload when the `COATING.DAT` file changes; you may need to restart the OpticStudio process.

3. **Use a vendor-supplied coating file.** Some vendors publish coating definitions for OpticStudio (rare); if you have one, paste its `COAT`/`MATE` sections into your `COATING.DAT`.

**Validate after setting a coating:** typo'd coating names and missing layer materials are caught by `TheSystem.UpdateStatus()` (see `patterns.md` § "System-validity check"). A surface with an unrecognized coating name will report an error there rather than silently doing nothing — but only if you check.

NSC counterpart: `obj.CoatScatterData.GetFaceData(face_idx).Coating = 'AR'` for non-sequential objects (see `conventions.md` § "Coatings: only at material transitions").

### Surface apertures

Apertures clip rays at a surface (separate from `SemiDiameter`, which is the aperture used for layout drawing).

```python
SAT = ZOSAPI.Editors.LDE.SurfaceApertureTypes
ap = surf.ApertureData.CreateApertureTypeSettings(SAT.RectangularAperture)
ap._S_RectangularAperture.XHalfWidth = 0.1
ap._S_RectangularAperture.YHalfWidth = 0.1
surf.ApertureData.ChangeApertureTypeSettings(ap)
```

Aperture types: `CircularAperture`, `CircularObscuration`, `RectangularAperture`, `RectangularObscuration`, `EllipticalAperture`, `EllipticalObscuration`, `Spider`, `UserAperture` (UDA file). Each has its `_S_<TypeName>` settings sub-object — same `_S_*` pattern as solves.

### Solves on cell properties

Cells (`RadiusCell`, `ThicknessCell`, `ConicCell`, ...) can hold a solve in addition to a numeric value. The pattern:

```python
SolveType = ZOSAPI.Editors.SolveType
solver = surf.RadiusCell.CreateSolveType(SolveType.FNumber)
solver._S_FNumber.FNumber = 10
surf.RadiusCell.SetSolveData(solver)
```

Common SolveTypes:

| SolveType | What it does | Settings via `_S_*` |
|-----------|--------------|---------------------|
| `Variable` | Mark variable for optimization | (use `MakeSolveVariable()` shortcut instead) |
| `Pickup` | Copy from another surface's cell | `_S_Pickup.PickupSurface, PickupColumn, ScaleFactor, Offset` |
| `FNumber` | Set radius from desired F/# | `_S_FNumber.FNumber` |
| `Position` | Constrain by position relative to another surface | `_S_Position.FromSurface, Length` |
| `Marginal` / `Chief` | Marginal/chief ray angle solve | `_S_Marginal.Angle` |
| `ParaxialMagnification` | Magnification target | `_S_ParaxialMagnification.Magnification` |
| `ElementPower` | Constrain element optical power | `_S_ElementPower.Power` |

`PickupColumn`: 0 = Radius, 1 = Thickness, 2 = Conic, 3+ = parameter columns. (Confirm with the CHM for the surface type — it varies for non-Standard surfaces.)

## System Explorer (`TheSystem.SystemData`)

The System Explorer in the GUI = these subobjects in the API.

### Aperture
```python
SD = TheSystem.SystemData
SD.Aperture.ApertureType = ZOSAPI.SystemData.ZemaxApertureType.EntrancePupilDiameter
SD.Aperture.ApertureValue = 20                  # mm (units depend on ApertureType)
SD.Aperture.ApodizationType = ZOSAPI.SystemData.ZemaxApodizationType.Gaussian   # also .Uniform, .CosineCubed
SD.Aperture.ApodizationFactor = 1                                                # raw integers no longer auto-convert to enums
```

#### `ApertureType` enum reference

The aperture mode controls **what is pinned (= `ApertureValue`) and what floats during ray tracing**. This has direct consequences for what the optimizer is allowed to change — see `optimization.md` § "Aperture mode and the silent-resize trap" for the optimization-specific implications and a decision tree.

| `ApertureType` enum | Pinned | Floats |
|---|---|---|
| `EntrancePupilDiameter` (default) | EPD | Stop semi-diameter (auto-recomputed) |
| `ImageSpaceFNum` | Image-space working F/# | EPD and stop |
| `ObjectSpaceNA` | Object-space NA | EPD and stop |
| `ParaxialWorkingFNum` | Paraxial working F/# (ignores aberrations) | EPD and stop |
| `ObjectConeAngle` | Half-angle of object-space cone (degrees) | EPD and stop |
| `FloatByStopSize` | Stop semi-diameter (set on the stop surface) | EPD |

### Fields
```python
field1 = SD.Fields.GetField(1)                  # 1-based
new_field = SD.Fields.AddField(0.0, 5.0, 1.0)   # x, y, weight
SD.Fields.SetFieldType(ZOSAPI.SystemData.FieldType.Angle)   # Angle / ObjectHeight / ParaxialImageHeight / RealImageHeight
SD.Fields.NumberOfFields
SD.Fields.DeleteFieldAt(idx)
```

The `IField` returned by `GetField` exposes `X`, `Y`, `Weight`, `VDX`, `VDY`, `VCX`, `VCY`, `VAN` (vignetting factors and angle).

### Wavelengths
```python
SD.Wavelengths.SelectWavelengthPreset(ZOSAPI.SystemData.WavelengthPreset.FdC_Visible)
# or set custom values:
SD.Wavelengths.GetWavelength(1).Wavelength = 0.473      # um
SD.Wavelengths.GetWavelength(1).Weight = 1.0
SD.Wavelengths.AddWavelength(0.633, 1.0)
SD.Wavelengths.NumberOfWavelengths
```

Common presets: `d_0p587`, `FdC_Visible`, `FdC_Reduced_Visible`, `RGB_Display`, `Mercury_e_F_C`. Presets *replace* the current wavelength list.

### Environment, Polarization, Units, Title
```python
SD.Environment.Temperature = 20.0               # °C
SD.Environment.Pressure = 1.0                   # atm
SD.Environment.AdjustIndexToEnvironment = True

SD.Polarization.Jx = 1.0; SD.Polarization.Jy = 0.0
SD.Polarization.XPhase = 0.0; SD.Polarization.YPhase = 0.0
SD.Polarization.IsConvertThinFilm = False

SD.Units.LensUnits        # enum: Millimeters, Centimeters, Inches, Meters
SD.TitleNotes.Title = 'My design'
```

For thermal sweeps across multiple temperature/pressure values, use multi-config (see `multi-config.md`) rather than mutating Environment between traces.

## Material catalogs

Catalogs are `.AGF` files in `TheApplication.GlassDir`. The `ISDMaterialCatalogData` interface (`SD.MaterialCatalogs`) gives you full programmatic control:

```python
mc = TheSystem.SystemData.MaterialCatalogs
in_use = list(mc.GetCatalogsInUse())              # currently loaded in this system
available = list(mc.GetAvailableCatalogs())       # everything on disk under GlassDir
mc.IsCatalogInUse('SCHOTT')                        # bool — quick check
mc.AddCatalog('SCHOTT')                            # load (returns bool)
mc.RemoveCatalog('SCHOTT')                         # unload (returns bool)
materials = list(mc.GetMaterialsInCatalog('SCHOTT'))   # ['N-BK7', 'F2', ...]
```

Once loaded, any glass name in the catalog (e.g. `'N-BK7'`, `'F2'`, `'QUARTZ'`) is valid as a `surf.Material` value.

**Use `GetAvailableCatalogs()` — never glob the Glasscat directory yourself.** A fresh system loads only **SCHOTT** by default, but a typical install has **~45** catalogs available (`C:\ProgramData\Zemax\Glasscat`). Listing the folder by hand with a case-sensitive `*.agf` pattern silently drops every uppercase `.AGF` file — which is most of them, including all the big ones (SCHOTT, OHARA, HOYA, CDGM, HIKARI, SUMITA, NIKON, CORNING, INFRARED, MISC where fused silica lives, BIREFRINGENT, the polymers ZEON/TOPAS/APEL/ARTON/SABIC, and the IR/specialty set AMTIR/IRPHOTONICS/UMICORE/HERAEUS/…). The agent then concludes it has 7 catalogs when it has 45. `GetAvailableCatalogs()` returns the real list regardless of filename case and is the only reliable source. If you must touch the filesystem, match case-insensitively (`*.[aA][gG][fF]`).

Key distinction: **available ≠ in use.** `GetAvailableCatalogs()` is everything on disk; `GetCatalogsInUse()` is what *this system* has loaded (just SCHOTT in a fresh file). A glass in an available-but-not-loaded catalog is a missing-glass error until you `AddCatalog()` it — see the stock-lens trap below for how that fails silently.

### Silent-failure trap: stock lenses pull glasses from catalogs you may not have loaded

This bites every script that uses `Tools.OpenLensCatalogs` (see `system-and-application.md`). For example, **Edmund AC508-075-A uses E-BAF11**, which lives in the **HIKARI** catalog. If `HIKARI` isn't in `MaterialCatalogs.GetCatalogsInUse()`, the GUI prompts to add it but **the API silently leaves the surface with a missing-glass material**. Every ray dies at the glass interface; the trace runs, completes, and reports zero detector hits — no exception, no warning to stderr.

The defense is a tiny pre-flight that loads any vendor catalog before inserting their stock lens:

```python
def _ensure_glass_catalogs(TheSystem, names):
    """Load each glass catalog if not already in use. Returns the list of newly added."""
    mc = TheSystem.SystemData.MaterialCatalogs
    in_use = set(mc.GetCatalogsInUse())
    available = set(mc.GetAvailableCatalogs())
    added = []
    for name in names:
        if name in in_use:
            continue
        if name not in available:
            raise RuntimeError(f"Glass catalog '{name}' is not in {TheApplication.GlassDir}")
        if not mc.AddCatalog(name):
            raise RuntimeError(f"AddCatalog('{name}') failed")
        added.append(name)
    return added

# Common stock-lens vendor catalogs
_ensure_glass_catalogs(TheSystem, ('SCHOTT', 'OHARA', 'HOYA', 'CORNING', 'HIKARI', 'CDGM'))
```

Call this **before** `InsertLensSeq` / `LoadLens`, and again **after any `SaveAs` + `LoadFile`** round-trip (the catalog list does not always survive serialization in the GUI workflow; safer to re-assert).

**Two more `InsertLensSeq` traps verified in v24.1** beyond missing-glass: (1) the leading-shoulder surface comes out with `Thickness = ∞` — must explicitly set to `0.0` after insertion or every downstream surface goes to Z = ∞; (2) `reverseSurfGeom=True` is silently ignored, so you cannot get a flipped catalog lens through the API flag — must read the forward-inserted surfaces and rebuild manually. Full recipes and the `build_reversed_lens` helper in `system-and-application.md` § "Two InsertLensSeq traps".

**Backstop:** missing glass is just one failure mode. After any LDE mutation you don't fully trust, validate with `TheSystem.UpdateStatus()` — empty string means OK, any other string is a diagnostic that includes missing-glass warnings, undefined apertures, sequential-validity issues, and more. See `patterns.md` § "System-validity check."

For per-surface glass diagnosis, **`LDE.GetClosestGlass(surface_number)`** returns the closest catalog glass to whatever's on that surface — a missing or unrecognized glass returns an empty string or an obviously-wrong nearest match.

## Converting a .zmx vendor file to an NSC seed

When a vendor part is not in `Tools.OpenLensCatalogs` (common for Thorlabs, custom optics, OEM parts) but the vendor ships a `.zmx` prescription file, you can pull the real surface data into your NSC scene via `Tools.OpenConvertToNSCGroup`. This is the **correct** path — `TheSystem.MakeNonSequential()` exists but is lossy (just flips the editor mode, drops surface data; see `pythonnet-gotchas.md` § 4).

```python
ZOSAPI = zos.ZOSAPI

# 1) Load the .zmx (a sequential prescription file)
TheSystem.LoadFile(r'C:\path\ACL2520U-A.zmx', False)

# 2) Verify it loaded as sequential — TheSystem.Mode is the right check
#    (IsSequential does NOT exist on IOpticalSystem — getattr with default
#    silently lies about it; use Mode.)
assert TheSystem.Mode == ZOSAPI.SystemType.Sequential, "expected sequential .zmx"

# 3) Convert. FirstSurface/LastSurface use 1-based indexing, exclude OBJ + IMA
n_surf = TheSystem.LDE.NumberOfSurfaces
tool = TheSystem.Tools.OpenConvertToNSCGroup()
try:
    tool.FirstSurface     = 1                  # skip OBJ (surface 0)
    tool.LastSurface      = n_surf - 2         # skip IMA (last surface)
    tool.ConvertFileToNSC = True               # True = pure NSC system; False = NSC group inside sequential
    if not tool.RunAndWaitForCompletion():
        raise RuntimeError(f"convert failed: {tool.ErrorMessage}")
finally:
    tool.Close()

# 4) Save as the NSC seed you'll load from build scripts
TheSystem.SaveAs(r'C:\path\ACL2520U-A_NSC.zos')
```

**Key properties on `IConvertToNSCGroup`** (full list: probe with `scripts/probe_object_properties.py`):

| Property | Purpose |
|---|---|
| `FirstSurface` / `LastSurface` (int) | 1-based surface range to convert; exclude OBJ (0) and IMA (n_surf-1) |
| `ConvertFileToNSC` (bool) | `True` → entire system becomes NSC. `False` → sequential system with a single NSC group covering the surface range |
| `ConvertStopToNSCAperture` (bool) | Wrap the stop surface in an NSC aperture object |
| `ConvertToGlobalCoordinates` (bool) | Express NSC objects in global vs. local-to-prior-surface coords |
| `CreateSourcesAndDetectors` (bool) | Auto-add a SourceRay + DetectorRectangle around the converted group |
| `IgnoreErrors` (bool) | Skip surfaces that fail to convert (e.g. unsupported surface types) instead of aborting |
| `OverfillFactor` (double) | Multiplier on auto-created source aperture vs. lens clear aperture |

**Leading-dummy-surface trap — and `ConvertToGlobalCoordinates`.** If the `.zmx` has a leading flat/dummy shoulder (common — vendors put an N mm spacer before the first real surface), the converter emits a `RefObject` chain with an offset null in front, so the resulting objects' `ZPosition` values are in **different frames**, not a common one. Any seed-reader that compares or differences raw `ZPosition` will mis-place cemented elements (the classic symptom: the flint of a doublet ends up buried inside the crown). Two defenses: (1) set **`tool.ConvertToGlobalCoordinates = True`** so objects come out in the group's global frame instead of local-to-prior-surface chains; (2) when reading an already-converted seed, get true positions via **`GetMatrix()`**, never raw `ZPosition`. Full explanation in `conventions.md` § "Reading true positions back."

**When this is the right approach:**
- Vendor ships a `.zmx` but the part isn't in `LensCatalogs` (Thorlabs is the common case)
- You need real aspheric / cemented / multi-element prescriptions in an NSC bench scene
- One-time setup: run the conversion, check the `.zos` in the GUI to verify the NCE looks correct (Even Asphere Lens for a single asphere, two singlets for a cemented achromat), then commit the `.zos` as a build-time input

**Don't** use `MakeNonSequential()` for this — it's lossy. Don't use `OpenLensCatalogs` first either if you've already tried and the part isn't there; that just adds latency.

**For multi-element parts (cemented doublets, triplets, beam-shaper assemblies), group the converted objects under a Null Object parent immediately after conversion.** A doublet emerges from `OpenConvertToNSCGroup` as two independent singlets — moving "the doublet" by editing one singlet's `ZPosition` separates the glasses and breaks the design. See `conventions.md` § "Grouping multi-element parts under a Null Object parent" for the `group_under_null_parent` helper that wires children's `RefObject` to a shared parent so the whole assembly moves rigidly. Apply this once per converted part during the seed-building phase; the resulting `.zos` then exposes a single object to move per part.

## Worked example: a simple singlet

```python
from boilerplate import PythonStandaloneApplication

zos = PythonStandaloneApplication()
ZOSAPI = zos.ZOSAPI
TheApplication = zos.TheApplication
TheSystem = TheApplication.PrimarySystem  # default sequential

TheSystem.New(False)
SD = TheSystem.SystemData
SD.MaterialCatalogs.AddCatalog('SCHOTT')
SD.Aperture.ApertureValue = 20                          # 20mm EPD
SD.Wavelengths.SelectWavelengthPreset(ZOSAPI.SystemData.WavelengthPreset.d_0p587)
SD.Fields.AddField(0.0, 5.0, 1.0)                       # 5° off-axis field

LDE = TheSystem.LDE
LDE.InsertNewSurfaceAt(2)
LDE.InsertNewSurfaceAt(2)
LDE.GetSurfaceAt(1).IsStop = True
LDE.GetSurfaceAt(1).Thickness = 50.0
front = LDE.GetSurfaceAt(2)
front.Radius = 100.0; front.Thickness = 10.0; front.Material = 'N-BK7'
rear = LDE.GetSurfaceAt(3)
rear.Comment = 'rear of lens'

# Solve: set rear radius for image-space F/10
solver = rear.RadiusCell.CreateSolveType(ZOSAPI.Editors.SolveType.FNumber)
solver._S_FNumber.FNumber = 10
rear.RadiusCell.SetSolveData(solver)

# Auto-focus
qf = TheSystem.Tools.OpenQuickFocus()
qf.Criterion = ZOSAPI.Tools.General.QuickFocusCriterion.SpotSizeRadial
qf.RunAndWaitForCompletion(); qf.Close()

TheSystem.SaveAs(r'C:\path\singlet.zos')
del zos; zos = None
```

For optimization beyond QuickFocus (variables + merit function + DLS), see `optimization.md`. For pulling spot/MTF/wavefront data out, see `analyses.md`.
