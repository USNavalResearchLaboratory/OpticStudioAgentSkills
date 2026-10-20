# Patterns: Discovery, Sweeps, Debugging

## Two complementary discovery tools

When the skill's reference files don't cover what you need, you have two ways to figure things out before guessing:

| Tool | Answers | When |
|------|---------|------|
| `scripts/probe_object_properties.py` | **What does this object actually expose right now?** Lists typed property names, defaults, ParN cells. | When you have a known object/surface/analysis/tool type and need its real properties. |
| `chmseek` (CHM help reader) | **What interfaces, methods, enums, or concepts exist that I haven't heard of yet?** Searches the official CHM documentation. | When you don't know what to look for — e.g. "is there a lens-catalog API?" or "what does the Forbes merit function do?" |

Use the probe for live introspection of things you can name. Use chmseek to discover things you can't.

## Looking up the API with chmseek

OpticStudio ships two CHM (compiled HTML help) files. Default install paths:

```
ZOS-API:        C:\Program Files\Zemax OpticStudio\ZOS-API\Help\ZOS-API.chm
OpticStudio:    C:\Program Files\Zemax OpticStudio\Help\OpticStudio_Help_en.chm
```

Use **`ZOS-API.chm`** for interface/method/property/enum lookups (e.g. "what methods does `ILensCatalogLens` have?"). Use **`OpticStudio_Help_en.chm`** for optical-concept and GUI-feature questions (e.g. "what is the Forbes merit function?", "what's the difference between FFT MTF and Geometric MTF?", "how does Zemax compute coherent irradiance on a detector?").

### Use the wrapper, not raw `chmseek`

The skill bundles **`scripts/chmseek_zos.py`** — a thin wrapper that handles the Windows-only encoding problems (`PYTHONIOENCODING=utf-8` on the subprocess + `sys.stdout.reconfigure` on the wrapper itself), accepts `--chm zos` / `--chm gui` shortcuts so you don't type the full Windows path, and prints results in a compact text format that's easier for an agent to scan than the raw JSON dump. Use it for everything; only fall back to raw `chmseek` if you need a feature the wrapper doesn't expose.

> **`conda run` trap — always pass `--no-capture-output`.** If you invoke the wrapper from another project's directory via `conda run -n zemax python .../chmseek_zos.py ...`, **plain `conda run` crashes** on any non-ASCII CHM content (µ, λ, °, Doxygen bullets, or the `�` our own `errors='replace'` emits). `conda run` *captures* the child's stdout and re-`print()`s it through conda's own cp1252 stream, which can't encode those characters — and the wrapper's `reconfigure()` has no power over conda's re-encode step. The crash traceback points at `conda\cli\main_run.py`, not our script. **Fix: add `--no-capture-output`** so the child writes straight to the terminal and conda never re-encodes:
>
> ```bash
> conda run --no-capture-output -n zemax python <skill-path>/scripts/chmseek_zos.py read --chunk ch_001664 --chm zos
> ```
>
> If you've already `conda activate`d the env (so bare `python` resolves), this doesn't apply — the trap is specific to the `conda run` wrapper.

Recommended workflow:

```text
search (hybrid) → read chunk with neighbors → grep exact symbol if needed → read whole page
```

Concrete examples — these work as-is, no Windows path quoting needed:

```bash
# Conceptual search — when you don't know the exact name
python <skill-path>/scripts/chmseek_zos.py search "save NSC ray trace to ZRD"

# Exact-symbol search (no embeddings)
python <skill-path>/scripts/chmseek_zos.py grep "InsertLensSeq"

# Read a result with surrounding context (don't draw conclusions from one chunk)
python <skill-path>/scripts/chmseek_zos.py read --chunk ch_000712 --neighbors 2

# Read the whole page once you've found a good landing spot
python <skill-path>/scripts/chmseek_zos.py read --page p_001328

# Search the OpticStudio GUI/concepts help instead of the API help
python <skill-path>/scripts/chmseek_zos.py search "Forbes merit function" --chm gui

# Drop --json on any command to get raw chmseek JSON (for further parsing)
python <skill-path>/scripts/chmseek_zos.py search "lens catalog" --json
```

Each `search` / `grep` result line shows `page=<id> chunk=<id>` and the exact `READ:` command to read that result with its neighbors — copy/paste it.

Tips:
- **Default to hybrid search.** Semantic alone misses exact symbol names; keyword alone misses concept queries. The wrapper's `search` defaults to hybrid.
- **Read neighboring chunks** before deciding what an interface does. A single chunk often misses key qualifiers in adjacent prose. The wrapper defaults to `--neighbors 2`.
- A missing search hit does NOT mean the API doesn't exist. Try synonyms, switch CHMs (an optical-concept question won't be in `ZOS-API.chm`), or use exact `grep` variants.
- The first run on a new CHM auto-indexes; if the embedding model isn't cached, run `chmseek index <chm> --allow-model-download` once. Use `chmseek diagnose` if results look stale or empty.

## Property discovery — always probe before guessing

The single most-common source of silent bugs is making up a property name (`XHalfWidth`, `Radius1Front`, etc.) that doesn't exist on the .NET class. The setter creates a Python attribute, the readback succeeds, and the model is wrong.

Before writing setters for any unfamiliar type, run the probe:

```bash
python <skill-path>/scripts/probe_object_properties.py
```

The script probes four parts of the API where the `__implementation__` trick is needed:

| Section | What it dumps | When you need this |
|---------|--------------|---------------------|
| **NCE object types** | `obj.get_ObjectData().__implementation__` properties + ParN cells | Adding any NSC object (sources, detectors, surfaces, volumes) |
| **LDE surface types** | `surf.get_SurfaceData().__implementation__` properties + universal surface props | Sequential design — when you `ChangeType` a surface to EvenAspheric, Toroidal, CoordinateBreak, etc. |
| **Analyses** | `analysis.GetSettings().__implementation__` properties; flags `HasAnalysisSpecificSettings` | Configuring any analysis (FFT MTF, Spot, Wavefront, Detector Viewer, ...) |
| **Tools** | `tool.__implementation__` properties on each `Tools.Open*` result | Configuring optimization, tolerancing, batch ray trace, ZRD reader, etc. |

Each section iterates a configurable list at the top of the script (`NCE_TYPES`, `LDE_SURFACE_TYPES`, `ANALYSIS_TYPES`, `TOOL_TYPES`) — edit the lists to add types you specifically need. Output for each type:

- The interface type returned by the typed accessor
- All typed properties (filtered to meaningful ones, with default values)
- Setter methods (`set_*`)
- ParN cell values (NCE objects and LDE surfaces only — settings/tools don't have cells)
- For analyses: whether `HasAnalysisSpecificSettings` is True (if False, you must use `ModifySettings` + `.cfg` instead)

Use the typed property names from the printout in your code. If a property you expected doesn't appear, it doesn't exist — check `set_*` methods or look at the GUI to see if there's a different name. This takes 30 seconds and saves hours of "why is the model wrong" debugging.

## System-validity check: `TheSystem.UpdateStatus()`

**Use this everywhere you make an edit you don't fully trust.** It's the single most useful safety net in the whole API and Zemax doesn't surface it in any of the obvious places.

```python
status = TheSystem.UpdateStatus()      # forces re-evaluation; returns a string
if status:                              # empty string == no errors
    raise RuntimeError(f"System invalid: {status}")
```

`TheSystem.GetCurrentStatus()` returns the same string without forcing a re-evaluation — use it as a cheap re-check after `UpdateStatus()` has already run.

The diagnostic string covers far more than you'd guess from its name. Things `UpdateStatus()` reports include:

- **Missing material at any surface** — including the silent-failure case where you inserted a stock lens whose glass catalog isn't loaded (`AC508-075-A` uses `E-BAF11` from `HIKARI`; if `HIKARI` isn't in `MaterialCatalogs`, the surface ends up with a missing-glass material and **every ray dies at that interface with no exception thrown**)
- Undefined or invalid system aperture
- Field/wavelength configuration problems
- Sequential validity issues (e.g. negative thickness in invalid contexts, conflicting solves)
- Surface aperture conflicts
- Stop placement issues
- NSC object placement / overlap problems

**Wrap any of these with an `UpdateStatus()` post-condition:**

- `LDE.InsertNewSurfaceAt`, surface property edits, `surf.ChangeType`
- `lens.InsertLensSeq`, `lens.LoadLens`, `lens.LoadNewLensSeq` (stock-lens insertions from the catalog tool — and **immediately after `InsertLensSeq`, set the leading-shoulder surface's `Thickness = 0.0`** to clear the inherited `Thickness = ∞` default, see `system-and-application.md` § "Two InsertLensSeq traps")
- `MaterialCatalogs.AddCatalog` / `RemoveCatalog`
- `SystemData.Aperture` / `Fields` / `Wavelengths` mutations
- `MakeSequential()` / `MakeNonSequential()`
- After any `SaveAs` + `LoadFile` round-trip (some state — including loaded catalog list — does not always survive serialization)
- Before kicking off a long ray trace or optimization

**Why this matters:** without it, Zemax fails the way the GUI never lets it fail. The GUI prompts the user when an edit produces an invalid system; the API does not. The trace just runs and produces empty output. Wrapping every suspicious edit with `assert TheSystem.UpdateStatus() == ""` (or a richer error) turns silent failures into immediate, debuggable exceptions with a useful message.

For per-surface glass diagnosis (when `UpdateStatus()` says something's wrong but doesn't pinpoint the surface), `LDE.GetClosestGlass(surface_number)` returns the closest catalog match — empty or wrong-looking output flags the offender.

## In-place parameter sweeps (sensitivity analysis)

When sweeping a parameter, **don't reconnect to Zemax for each sweep value** — connection setup takes ~2 seconds per call. Build the system once, then modify parameters in place and re-run the trace:

```python
# Build system once
zos = PythonStandaloneApplication()
TheSystem = zos.TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)
NCE = TheSystem.NCE
# ... build sources, detectors, optics ...

results = []
for value in sweep_values:
    # Modify a parameter in place
    src.SourcesData.set_YPhase(System.Double(value))    # e.g. polarization sweep
    # Or: src.GetObjectCell(OC.Par3).DoubleValue = new_power
    # Or: src.XPosition = new_x; src.TiltAboutY = new_angle

    # Reset and re-trace
    rt = TheSystem.Tools.OpenNSCRayTrace()
    rt.SplitNSCRays = True; rt.UsePolarization = True
    rt.IgnoreErrors = True
    rt.ClearDetectors(0)            # CRITICAL — otherwise detector accumulates
    rt.RunAndWaitForCompletion()
    rt.Close()

    # Extract from same detector (pixel=0 → total flux; -1 would be MAX pixel)
    _, power = NCE.GetDetectorData(det_idx, 0, 0, 0)
    results.append((value, power))

del zos; zos = None
```

Parameters that work well for in-place modification:
- `SourcesData.set_*` for polarization
- `GetObjectCell(OC.Par3).DoubleValue` for source power
- `XPosition`, `YPosition`, `ZPosition`, `TiltAboutX/Y/Z` for placement
- ObjectData typed properties for dimensions

The Detector Viewer can also be reused via `dv.ApplyAndWaitForCompletion()` — it re-reads whatever is in the detector buffer.

## Debugging checklist: "no power on the detector"

When a ray trace runs without errors but the detector reads zero or near-zero power, work through these in order. They're listed by frequency of being the actual cause.

0. **Did you call `TheSystem.UpdateStatus()` after the last edit?** Returns `""` if the system is valid; any other string is a diagnostic (missing glass, undefined aperture, bad sequential ordering, ...). This is the canonical "did Zemax accept what I just did" check and catches several of the silent-failure modes below before you ever run a trace. See § "System-validity check" above.

1. **`MaxAperture` defaults to 1 mm.** Every StandardSurface, including mirrors, defaults to a 1mm-radius disk. A 3mm beam mostly misses. Set `MaxAperture = 25.0` or whatever matches your physical optics. This is easily the #1 cause.

2. **Detector orientation.** Default detector normal is +Z. A beam traveling in the XY plane (e.g. ±X) skims across the face and registers nothing. Tilt the detector to face the incoming beam: `TiltAboutY = 90°` for +X beam, `TiltAboutY = -45°` for a beam traveling along (-1, 0, 1)/√2.

3. **`UsePolarization` not enabled** but the design uses polarization-sensitive elements (PBS coatings, waveplates, polarizers). Without it, polarization-dependent transmission/reflection is ignored, but more importantly birefringent splitting at QWPs requires `SplitNSCRays = True` AND `UsePolarization = True`.

4. **`SplitNSCRays` not enabled** but the design has a beam splitter coating. Without it, the coating's reflection branch never gets traced — only the transmitted beam reaches anything downstream. Enable it for any partial-reflection coating or birefringent material.

5. **Coating on the wrong face of a RectangularVolume.** Especially for tilted plates: face 0 = all faces (causes parasitic splits everywhere); the entry face for a +Z beam on a +45°-tilted plate is face 2 (back face in local frame). If the reflected arm is missing, suspect the coating face. See `conventions.md`.

6. **Mirror tilt sign error.** `+45°` reflects +Z to **-X**, not +X. If a beam goes the opposite direction from what you expected, flip the tilt sign.

7. **`ClearDetectors(0)` not called.** If you're rerunning the trace, the detector still holds old data. The new trace might have low signal compared to the residual.

7b. **Previous tool not closed.** Only one `ISystemTool` can be open at a time. If a previous `Tools.Open*()` call was never followed by `Close()` (often because the script errored out before reaching `Close`), the next `Tools.Open*()` returns a stale or non-functional tool. After an exception, restart the connection cleanly. To check whether a tool result actually worked, capture `RunAndWaitForCompletion()`'s return value — it's a `RunStatus` enum (`Completed` / `FailedToStart` / `TimedOut` / `InvalidTimeout`).

8. **ObjectData property name typo.** Check the readback against the .zos file in OpticStudio — if the readback reports `XHalfWidth = 1.5` but the GUI shows the source aperture is still 0, the property name is wrong (it's `XMinusWidth`, not `XHalfWidth`). Run the probe script.

9. **CylinderVolume ParN order.** If a "QWP" seems to act like a thick block of glass, check its dimensions — Par2 is `ZLength`, not `BackR`. Use the typed properties.

10. **numpy-typed positions.** If `obj.XPosition = pos[0]` raises `'numpy.int64' value cannot be converted to System.Double`, cast to `float()`.

## Verify in OpticStudio when in doubt

After building the system, save it and open in the GUI:

```python
TheSystem.SaveAs(r'C:\path\to\design.zos')
```

Then open `design.zos` in OpticStudio. The Component Editor shows actual values (not Python-attribute shadows), and the NSC 3D Layout (Analyze → NSC 3D Layout) renders the geometry visually. If a property doesn't match what your script set, that's the silent-attribute trap — check the property name.

The `NSCShadedModel` analysis is also useful for checking surface coverage and beam paths.

## Bundling small probes with your design scripts

When developing a design, it helps to keep a tiny diagnostic script in the same folder that:
1. Loads the saved `.zos` file
2. Runs a short trace (1M rays)
3. Prints power on each detector and the first few rays' positions

This lets you re-verify a design quickly without re-running the full simulation. The probe script in this skill is the template for this kind of utility.
