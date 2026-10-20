# TheApplication and TheSystem: Top-Level Entry Points

`TheApplication` is the running OpticStudio process. `TheSystem` (a.k.a. `IOpticalSystem`) is one optical design loaded into it. A single `TheApplication` can hold multiple `TheSystem` instances. The `boilerplate.md` connection class gives you `TheApplication` and `TheApplication.PrimarySystem` as `TheSystem`.

## Connection modes — pick one

There are four ways for external code to talk to OpticStudio. Only the first two are how you write a Python ZOS-API script; the others involve compiled extensions (see `user-extensions.md`).

| Mode | What it does | When to use |
|------|--------------|-------------|
| **Standalone** | `TheConnection.CreateNewApplication()` launches a hidden OpticStudio process for the script's lifetime. No GUI. The default in our boilerplate. | Batch automation, CI, headless servers. Fastest startup. |
| **Interactive Extension** | `TheConnection.ConnectAsExtension(0)` attaches to a *running* OpticStudio with the GUI visible. Requires the user to enable Programming → Interactive Extension in the GUI menu first. | **Required** for any image export (`Tools.Layouts.Open*Export`, `analysis.ToFile`) — those tools need the GUI render context and silently no-op in Standalone. Also use for live debugging / design iteration with the GUI visible. Full pattern + agent ↔ user handoff in `interactive-extension.md`. |
| **User Extension** | C#/C++ executable launched from the OpticStudio menu. Python cannot author. | (See `user-extensions.md`.) |
| **User Analysis** | C# DLL that appears as a custom analysis. Python cannot author. | (See `user-extensions.md`.) |

### Interactive Extension: the UpdateMode trap

When you connect via `ConnectAsExtension`, the system defaults to `UpdateMode = LensUpdateMode.EditorsOnly` for performance. Edits show up in the LDE/NCE/MCE/MFE/TDE editors immediately, but **analysis windows do not refresh** when you change the lens via the API. There are two ways to force them to refresh:

```python
# Option A — refresh every open analysis window after every edit
for i in range(1, TheSystem.Analyses.NumberOfAnalyses + 1):
    TheSystem.Analyses.Get_AnalysisAtIndex(i).ApplyAndWaitForCompletion()

# Option B — switch update mode for the whole session
TheSystem.UpdateMode = ZOSAPI.LensUpdateMode.AllWindows
TheSystem.UpdateStatus()
```

Option B is convenient but slower (every edit triggers a full GUI refresh). Option A keeps the editors fast and only refreshes when you ask. Standalone mode doesn't have this problem because there's no GUI to refresh.

The `Connect-to-OpticStudio-from-Python-with-the-ZOS-API-Interactive-Extension.html` and `Interactive-Extension-FAQ.html` Ansys articles cover this in more detail.

## TheApplication members

### Multi-system management
```python
TheApplication.PrimarySystem            # the default IOpticalSystem
TheApplication.NumberOfOpticalSystems
TheApplication.GetSystemAt(i)           # returns IOpticalSystem
TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)  # or .Sequential
TheApplication.LoadNewSystem(path)      # opens a .zos/.zmx into a new system slot
TheApplication.CloseSystemAt(i)
TheApplication.CloseApplication()       # called by the boilerplate __del__
```

### Catalog directories
Catalogs in OpticStudio are *files in directories*, not API collections. `TheApplication` exposes those directories so you can list/load them:

| Property | What's in there |
|----------|----------------|
| `GlassDir` | `.AGF` glass catalogs (SCHOTT, OHARA, BIREFRINGENT, ...) |
| `LensDir` | Vendor lens catalogs (Edmund, Thorlabs, ...) and saved `.zmx` files |
| `CoatingDir` | Coating definition files (`.DAT`, `COATING.DAT`) |
| `ScatterDir` | Scatter profile files |
| `ObjectsDir` | NSC object files (`.STP`, `.IGS`, `.STL`, `.SRC`, etc.) |
| `POPDir` | Physical Optics Propagation source/data files |
| `SamplesDir` | Bundled example code (~25 Python scripts ship with OpticStudio — read these!) |
| `ZemaxDataDir` | Per-user data folder. Hosts subfolders including `\BlackBoxes\` (for `.ZBB` proprietary lens "playback" files — see `sequential-design.md` § "Black Box Lens surfaces"), `\Configs\`, `\Macros\`, plus the per-user `Glasscat/Coatings/Scatter/Objects/POP/Images/...` mirrors of the system catalogs |
| `ZPLDir` | ZPL macro files |
| `ImagesDir`, `MATLABFilesDir`, `AutodeskInventorFilesDir`, `CreoParametricFilesDir` | Various import/export folders |

To use a glass catalog in a system: `TheSystem.SystemData.MaterialCatalogs.AddCatalog("SCHOTT")`. To discover what catalogs exist, call **`MaterialCatalogs.GetAvailableCatalogs()`** — do **not** glob `GlassDir` yourself: catalog files are mixed-case (`SCHOTT.AGF` but also lowercase names), so a case-sensitive `*.agf` listing silently drops most of them (a real install has ~45, not the handful a naive glob finds). See `sequential-design.md` § "Material catalogs" for the full API and the case-sensitivity trap. **For searching glasses by index/Abbe/transmission, use the dedicated tools below — far easier than parsing `.AGF` files.**

### Searching the stock lens catalogs (`Tools.OpenLensCatalogs`)

OpticStudio ships with stock-lens catalogs from Edmund, Thorlabs, Newport, etc. **Do NOT try to hand-load raw `.zmx` files from `LensDir`** — Zemax stores stock catalogs in an opaque format and the loose `.zmx` files you'd expect aren't always there. The `ILensCatalogLens` returned by the search tool has dedicated methods that handle all of this for you.

#### Step 1: search

```python
cat = TheSystem.Tools.OpenLensCatalogs()

# Discover available vendors
vendors = list(cat.GetAllVendors())     # ['EDMUND', 'THORLABS', 'NEWPORT', ...]

# Pick one, then optionally filter
cat.SelectedVendor = 'EDMUND'
print(cat.LensesForVendor)              # total count for this vendor

# Filter by EFL, EPD, element count, shape, type
cat.UseEFL = True; cat.MinEFL = 50.0;  cat.MaxEFL = 100.0
cat.UseEPD = True; cat.MinEPD = 10.0;  cat.MaxEPD = 25.4
cat.NumberOfElements = 2                # exactly 2; or cat.SetNumberOfElementsAny()
cat.IncShapeBi = True; cat.IncShapeMeniscus = True; cat.IncShapeEqui = False
cat.IncTypeSpherical = True; cat.IncTypeAspheric = False; cat.IncTypeGRIN = False

cat.RunAndWaitForCompletion()           # apply filters
```

`ILensCatalogs` properties: `SelectedVendor`, `UseEFL`/`MinEFL`/`MaxEFL`, `UseEPD`/`MinEPD`/`MaxEPD`, `NumberOfElements` (set 0 or call `SetNumberOfElementsAny()`), shape filters (`IncShapeEqui`/`Bi`/`Plano`/`Meniscus`), type filters (`IncTypeSpherical`/`GRIN`/`Aspheric`/`Toroidal`). Methods: `GetAllVendors()`, `SetNumberOfElementsAny()`, `GetResult(i)`, plus the inherited `RunAndWaitForCompletion()` / `Close()` from `ISystemTool`.

#### Step 2: inspect results

```python
for i in range(cat.MatchingLenses):
    lens = cat.GetResult(i)             # ILensCatalogLens
    print(f'{lens.Vendor} {lens.LensName}: EFL={lens.EFL:.1f}mm, EPD={lens.EPD:.1f}mm, '
          f'shape={lens.Shape}, type={lens.Type}, N={lens.NumberOfElements}, '
          f'telecentric={lens.Telecentric}')
```

`ILensCatalogLens` properties (read-only): `Vendor`, `LensName`, `EFL`, `EPD`, `Shape` (LensShape enum: Unknown/Equi/Bi/Plano/Meniscus), `Type` (LensType enum: Other/Spherical/GRIN/Aspheric/Toroidal), `NumberOfElements`, `Telecentric`.

#### Step 3: USE the lens — `ILensCatalogLens` has four loader methods

This is the part that bites agents who try to construct file paths manually. The `lens` object knows how to load itself:

```python
chosen = cat.GetResult(0)

# A) Replace the current system entirely with this lens
chosen.LoadLens(False)                  # arg = saveIfNeeded (save current first)

# B) Create a NEW sequential system from this lens (returns IOpticalSystem)
new_sys = chosen.LoadNewLensSeq()       # current system is left untouched

# C) Create a NEW non-sequential system from this lens
new_nsc_sys = chosen.LoadNewLensNonSeq()

# D) Insert into the CURRENT sequential system at a specific surface
ok = chosen.InsertLensSeq(atSurface=2,
                          ignoreObject=False,
                          reverseSurfGeom=False)  # see "reverseSurfGeom trap" below

# E) Convert to non-sequential components and append to the CURRENT NSC system
ok = chosen.InsertLensNonSeq()          # returns False if current system isn't NSC
```

`InsertLensSeq` is the typical "I want to add a stock doublet to my design" path — it places the lens's surfaces starting at `atSurface` in the current LDE without touching anything else. Use `LoadLens` only when you really want to replace the entire current design with the catalog lens, and `LoadNewLensSeq`/`LoadNewLensNonSeq` when you want a parallel system you can compare against.

#### Two `InsertLensSeq` traps (verified v24.1)

1. **Leading-shoulder Thickness = ∞.** The first surface `InsertLensSeq` inserts is a **leading shoulder dummy** whose `Thickness` defaults to `Infinity` (inherited from the new-system convention where OBJ is at infinity). Leaving it pushes every downstream surface to Z ≈ ∞ — the layout shows a ~1e10 mm-long stretch and POP/spot fail catastrophically. **The caller must explicitly set the leading shoulder's `Thickness = 0.0` after insertion:**

   ```python
   at_idx = 2
   ok = chosen.InsertLensSeq(atSurface=at_idx, ignoreObject=False, reverseSurfGeom=False)
   if not ok: raise RuntimeError("InsertLensSeq returned False (system not sequential?)")

   # MUST clear the leading-shoulder Thickness=inf or every downstream surface goes to Z=infinity
   TheSystem.LDE.GetSurfaceAt(at_idx).Thickness = 0.0

   # Then validate as usual
   err = TheSystem.UpdateStatus()
   if err: raise RuntimeError(f"system invalid after lens insert: {err}")
   ```

   Symptoms when you forget: `TheSystem.UpdateStatus()` may or may not flag it (depends on glass/aperture state), but the next ray trace returns NaN or zero intensity. Inspect the inserted-surface thicknesses with a quick loop right after `InsertLensSeq` to confirm everything is finite.

2. **`reverseSurfGeom=True` is silently ignored for catalog lens inserts.** The parameter is exposed and the call returns `True`, but in v24.1 the lens comes out with identical surface radii regardless of the flag. Verified: inserting AC254-040-A both ways gives radii 23.66 / -20.09 / -57.68 in both runs. **Do not rely on `reverseSurfGeom=True` to flip a catalog lens.**

   The canonical pattern for "flip this catalog lens" in sequential mode is the `build_reversed_lens` helper below — used both at build time and inside FFL/BFL probes that need a temporarily-reversed copy. It is preferred over the CB-pair pattern (`sequential-design.md` § "Coordinate Break pairs") for the common case of one rotationally symmetric lens flipped once: no coordinate-frame Z-shift to compensate for, no broken GUI rendering, no pickup-solve enum traps. Use CB pairs only when you need a runtime-toggleable flip via an MCE operand, a non-180° tilt/decenter, or a non-rotationally-symmetric element where radius reversal alone is geometrically wrong.

   ```python
   def build_reversed_lens(LDE, at_idx, n_surfaces):
       """After InsertLensSeq has placed n_surfaces at at_idx, replace them with
       the geometrically reversed lens (radii negated, surface order reversed,
       materials shifted by one to track the 'medium after' convention)."""
       fwd = []
       for i in range(at_idx, at_idx + n_surfaces):
           s = LDE.GetSurfaceAt(i)
           fwd.append(dict(
               radius=s.Radius, thickness=s.Thickness, material=s.Material,
               conic=s.Conic, semi_diam=s.SemiDiameter, comment=s.Comment,
           ))
       # Remove the forward-inserted surfaces, re-insert reversed
       for _ in range(n_surfaces):
           LDE.RemoveSurfaceAt(at_idx)
       for k, src in enumerate(reversed(fwd)):
           LDE.InsertNewSurfaceAt(at_idx + k)
           dst = LDE.GetSurfaceAt(at_idx + k)
           dst.Radius     = -src['radius']                  # negate radii
           dst.Conic      =  src['conic']
           dst.SemiDiameter = src['semi_diam']
           dst.Comment    =  src['comment']
       # Shift materials by one and thicknesses correspondingly
       # (material on surface N describes the medium between surface N and N+1)
       for k in range(n_surfaces):
           dst = LDE.GetSurfaceAt(at_idx + k)
           src_idx_in_fwd = (n_surfaces - 1) - (k + 1)      # material was after the previous surface in fwd
           if 0 <= src_idx_in_fwd < n_surfaces:
               dst.Material = fwd[src_idx_in_fwd]['material']
               dst.Thickness = fwd[src_idx_in_fwd]['thickness']
   ```

   For a simple singlet (3 surfaces: leading shoulder + 2 glass surfaces) the reversal is mechanical; for cemented doublets and triplets test the radii printout against the forward version to confirm the material indices align.

   **Do NOT also apply the trap-1 leading-shoulder `Thickness = 0.0` cleanup after `build_reversed_lens`.** In the forward lens the first inserted surface is a dummy shoulder in air, so zeroing its thickness is correct. In the reversed lens the first surface carries the **original last-element glass** (flint in a doublet) shifted in by the material-shift step — zeroing its thickness silently collapses the doublet into a singlet with the flint reduced to a zero-thickness layer. The trace still runs but the prescription is wrong. The leading-shoulder cleanup belongs only to forward `InsertLensSeq` output; once `build_reversed_lens` has shuffled the thicknesses, every position now carries a real value and should be left alone.

   Caveat: `build_reversed_lens` as written copies `Radius`, `Conic`, `SemiDiameter`, `Comment`, `Material`, `Thickness` — it does **not** carry over aspheric `ParN` coefficients, coating assignments, or surface-aperture data. If the catalog lens has any of those (most stock aspheres do), extend the per-surface dict to capture them too, or stop using this helper for that lens and use a CB-pair flip instead so the surfaces are not modified.

Don't forget to close the catalog tool when done browsing:
```python
cat.Close()
```

### Searching the materials catalogs (`Tools.OpenMaterialsCatalog`)

Same idea for searching glasses across loaded catalogs (Schott, Ohara, etc.) by index, Abbe number, transmission range, etc. Open the tool with `Tools.OpenMaterialsCatalog()` and run the probe script (or `dir(impl)`) to discover its filter properties — same `Tools.Open* → set filters → RunAndWaitForCompletion → iterate results → Close` lifecycle.

For other tools (CAD export, ZAR archive, QuickAdjust, FindBestAsphere, RayAimingWizard, etc.) see `optimization.md` § "Other system tools."

### Licensing and version
```python
TheApplication.IsValidLicenseForAPI       # bool — check before doing anything
TheApplication.LicenseStatus              # LicenseStatusType enum
TheApplication.IsSubscriptionLicense
TheApplication.IsSTARModuleEnabled        # required for some NSC features
TheApplication.OpticStudioVersion         # full version string
TheApplication.ZOSMajorVersion / ZOSMinorVersion / ZOSSPVersion
```

The boilerplate raises `LicenseException` when `IsValidLicenseForAPI` is False. In CI, also check `IsSTARModuleEnabled` if your script depends on it — the failure mode otherwise is silent.

### Preferences
```python
TheApplication.Preferences                # IPreferences
TheApplication.Preferences.General.Language   # enum, e.g. for UI localization
```

The Preferences tree mirrors the GUI Preferences dialog. Useful for forcing a specific language or units mode in automated runs.

### Logging and callbacks
```python
TheApplication.BeginMessageLogging()
# ... run things that produce status messages ...
msgs = TheApplication.RetrieveLogMessages()
TheApplication.EndMessageLogging()
TheApplication.RegisterNETOperandCallback(callback)   # see user-extensions.md
TheApplication.RunCommand(cmd)                        # limited command interface
```

## TheSystem members

### Mode and conversion
```python
TheSystem.Mode                    # ZOSAPI.SystemType.Sequential or NonSequential
TheSystem.MakeSequential()        # convert NSC → sequential (lossy)
TheSystem.MakeNonSequential()     # convert sequential → NSC
TheSystem.IsNonAxial              # True for tilted/decentered sequential systems
```

### File operations
```python
TheSystem.New(False)              # blank system (sequential by default)
TheSystem.LoadFile(path, False)   # second arg = make a project copy
TheSystem.Save()
TheSystem.SaveAs(path)
TheSystem.Close(False)            # arg = save before close
TheSystem.CopySystem()            # returns a new IOpticalSystem
TheSystem.NeedsSave               # bool
TheSystem.SystemFile, SystemName, SystemID
```

### Subobjects — pointers to dedicated reference files

| Property | What it controls | See |
|----------|------------------|-----|
| `LDE` | Lens Data Editor — sequential surfaces | `sequential-design.md` |
| `NCE` | Non-sequential Component Editor | `nsc-objects.md`, `conventions.md` |
| `MCE` | Multi-Configuration Editor | `multi-config.md` |
| `MFE` | Merit Function Editor | `optimization.md` |
| `TDE` | Tolerance Data Editor | `optimization.md` (tolerancing section) |
| `SystemData` | Aperture, Fields, Wavelengths, Environment, Polarization, MaterialCatalogs | `sequential-design.md` |
| `Tools` | OpenLocalOptimization, OpenQuickFocus, OpenNSCRayTrace, OpenBatchRayTrace, OpenScale, OpenTolerancing, OpenRayDatabaseReader, ... | `optimization.md`, `ray-database.md` |
| `Analyses` | New_Analysis, New_StandardSpot, New_FftMtf, ... | `analyses.md` |
| `STARSubsystem` | STAR (structural-thermal-analysis-results) integration | (specialized) |
| `TheApplication` | Back-reference to the parent IZOSAPI_Application | (this file) |

### UpdateMode and refresh

```python
TheSystem.UpdateMode              # LensUpdateMode: None, EditorsOnly, AllWindows
```

In Standalone mode the default is fine. In Interactive Extension mode, see the trap above.

### `UpdateStatus()` and `GetCurrentStatus()` — system-validity check

```python
status = TheSystem.UpdateStatus()       # forces re-evaluation; returns a string
status = TheSystem.GetCurrentStatus()   # cached; returns the same string without re-evaluating
```

**Both methods return a string. An empty string means the system has no errors. Any other string is a diagnostic** — missing material at a surface, undefined aperture, sequential validity issues, conflicting solves, etc. This is the canonical post-edit validation hook and the most undersold method in the entire API.

It catches things that otherwise produce silent failures (zero-power detectors, broken optimizations) without any exception:

```python
status = TheSystem.UpdateStatus()
if status:
    raise RuntimeError(f"System invalid: {status}")
```

Wrap it around `LDE` mutations, `lens.InsertLensSeq` calls from the catalog tool, `MaterialCatalogs.AddCatalog`, mode conversions, and post-`SaveAs`+`LoadFile` round-trips. Full motivation and the list of mutations to wrap is in `patterns.md` § "System-validity check."
