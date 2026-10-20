# pythonnet 3.0+ / ZOS-API Interop Pitfalls

The Python ↔ .NET bridge does not behave like ordinary Python. The five traps below are responsible for almost every "the script ran without errors but the model is wrong" bug in ZOS-API automation.

## 1. `ObjectData` requires `__implementation__` to expose typed properties

```python
data = obj.ObjectData                 # IObject — only generic methods
dir(data)
# ['Equals', 'GetHashCode', 'GetType', 'Id', 'IsValid', 'Row', 'ToString', 'Type', ...]

data = obj.get_ObjectData().__implementation__   # concrete .NET class
dir(data)
# ['XMinusWidth', 'XMinusDivergence', 'Power', 'NumberOfAnalysisRays', ...]
```

**Why:** pythonnet returns the interface (`IObject`) by default, not the concrete `ZOSAPI_SourceDiodeObject` (or whatever the type happens to be). The typed setters/getters live on the concrete class. The `.__implementation__` attribute exposes it.

**The trap:** `obj.ObjectData.XMinusWidth = 1.5` does not error. pythonnet creates a Python attribute `XMinusWidth` on the wrapper object. The Zemax model never receives the value. The script logs "set XMinusWidth = 1.5" but the source still has waist 0.

**Always** access typed properties through `obj.get_ObjectData().__implementation__`. The one notable exception is some properties on a few object types (e.g. `SourceDiode.ObjectData.XMinusDivergence`) work without it — but you cannot reliably tell which without testing, so just use `__implementation__` everywhere.

## 2. `SourcesData.set_Jx` etc. need `System.Double()` wrapping

```python
import System
src.SourcesData.RandomPolarization = False     # required first; default is True
src.SourcesData.set_Jx(System.Double(1.0))     # OK
src.SourcesData.set_Jy(1.0)                    # silently ignored — wrong overload
```

**Why:** The .NET method `set_Jx(double)` is one of several overloads. pythonnet 3.0+ doesn't auto-convert Python `float` to `System.Double` for these specific signatures (the auto-conversion was tightened across the 2.x → 3.x boundary). Without the explicit wrap, pythonnet picks a no-op overload or silently drops the call.

**Fix:** wrap every numeric argument to `set_*` polarization setters in `System.Double(...)`.

**Also:** `RandomPolarization = True` (the default!) overrides Jx/Jy — the source emits unpolarized light no matter what you set. Always set it to `False` explicitly before configuring polarization.

## 3. Integer-to-Enum conversion is not implicit

```python
# Wrong — TypeError or silent misbehavior
settings.DataType = 1

# Right
DVSDT = ZOSAPI.Analysis.DetectorViewerShowDataTypes
settings.DataType = DVSDT.CoherentIrradiance

# If you only have an integer value (e.g. from a lookup):
settings.DataType = DVSDT(1)               # construct enum from int
settings.DataType = DVSDT(99, True)        # second arg = allow out-of-range
```

**Why:** pythonnet 3.0+ stopped implicitly converting integers to .NET enums. You must construct the enum explicitly.

### The same conversion-tightening hits booleans, doubles, and selector objects

Pythonnet 3.0+ also stopped auto-converting `int → bool`, `int → System.Double` for many setters, and `int → IAS_Surface/IAS_Field/IAS_Wavelength` selector objects. Symptoms vary — sometimes `TypeError`, sometimes silent no-op via the Python-attribute trap (#5 below). Patterns observed in real runs:

- **Boolean properties want `True` / `False`, not `1` / `0`.** `surf.IsStop = 1` no-ops on pythonnet 3.0+; use `surf.IsStop = True`. Likewise any `Is*` / `Use*` / `Has*` / `Save*` / `Compute*` flag.
- **Enum properties want the enum member, not the int.** `SD.Aperture.ApodizationType = 1` is wrong; use `SD.Aperture.ApodizationType = ZOSAPI.SystemData.ZemaxApodizationType.Gaussian`. Pattern applies to every typed enum property in the API — and **some enum properties are named like they should take ints**. The Optimization Wizard's `Rings` and `Arms` properties are typed as `PupilRingsCount` / `PupilArmsCount` enums; `wiz.Rings = 3` raises an enum-coercion error in pythonnet 3 even though "3 rings" is the literal meaning. The fix is to use the enum member (`ZOSAPI.Wizards.PupilRingsCount.Ring_3` or whatever the convention is) — or, when the default is what you want, **just don't set it**. Probe the interface first; don't assume a count-ish property is `int`-typed.
- **Surface / field / wavelength "selectors" on analysis settings need `.SetSurfaceNumber(N)` / `.SetFieldNumber(N)` / `.SetWavelengthNumber(N)`, NOT direct assignment.** `pop_settings.EndSurface = 5` no-ops; use `pop_settings.EndSurface.SetSurfaceNumber(5)`. The typed object is `IAS_Surface` (or `IAS_Field`, etc.) — assignment rebinds the Python attribute and never touches the underlying selector. This bites POP, MTF, Spot, Wavefront — anywhere field/wavelength/surface gets selected on analysis settings.
- **Cell value type matters.** Most editor cells (`MFE.GetCellAt(i)`, `MCE.GetOperandCell(c)`, `surf.GetCellAt(i)`) accept `DoubleValue`, but **integer-typed cells** (notably MCE `IGNR`, the CoordinateBreak `Order` parameter, and several others) only accept `IntegerValue`. Use the try/fallback pattern:

  ```python
  def set_cell(cell, value):
      """Defensive: try DoubleValue, fall back to IntegerValue."""
      try:
          cell.DoubleValue = float(value)
      except Exception:
          cell.IntegerValue = int(value)
  ```

**General rule:** whenever a setter looks like it succeeded but the model didn't update, suspect a type mismatch and check the property's expected type (`dir(...)` plus the CHM via `chmseek`). The default Python coercions you'd expect from pythonnet 2.x are gone.

**Naming-collision sub-trap: `Header` vs `HeaderData`.** `IEditorCell` (every cell in LDE/NCE/MCE/MFE/TDE) exposes the column label as **`cell.Header`** — no "Data" suffix. There is a separately-named `HeaderData` property but it lives on `IAR_` (analysis results), not on editor cells. Writing `cell.HeaderData` doesn't crash — `getattr` raises `AttributeError` and a defensive `try/except` silently returns an empty string, so a probe loop that uses `cell.HeaderData` just shows blank labels for every cell and the agent thinks the labels are missing from the API. They're not — the name is wrong. Same trap shape (similar-looking property on a different interface) appears in a few other places; always confirm property names against the exact interface, not by analogy with another container's API.

## 4. `CreateNewSystem` for a fresh system; `MakeNonSequential` is lossy

```python
# Right (fresh empty system)
TheSystem = TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)

# Right (proper conversion with surface data preserved)
tool = TheSystem.Tools.OpenConvertToNSCGroup()
tool.FirstSurface = 1; tool.LastSurface = TheSystem.LDE.NumberOfSurfaces - 2
tool.ConvertFileToNSC = True
tool.RunAndWaitForCompletion(); tool.Close()

# Lossy — exists but DROPS surface data, just flips the editor mode
TheSystem.MakeNonSequential()
TheSystem.MakeSequential()
```

**Verdict:** `MakeSequential()` and `MakeNonSequential()` are real methods on `IOpticalSystem` (verified in CHM). They flip the editor mode but do not port surface/object data — calling `MakeNonSequential()` on a loaded lens leaves you with an empty NSC and discarded LDE. For an empty system, use `CreateNewSystem(SystemType.X)`. For a real conversion of an existing lens (e.g. loading a vendor `.zmx` file and turning it into an NSC seed), use `Tools.OpenConvertToNSCGroup()` — full recipe in `sequential-design.md` § "Converting a .zmx vendor file to an NSC seed."

## 5. The silent-Python-attribute trap (general form)

This is the most insidious one because it's the consequence of mistakes 1–4 combined with Python's dynamic attribute model. **Any** attempt to set an attribute on a pythonnet wrapper object that isn't a real .NET property succeeds silently — Python just creates a normal Python attribute. Reading it back returns what you set, so even readback verification looks correct.

```python
data = src.get_ObjectData().__implementation__
data.XHalfWidth = 1.5            # XHalfWidth doesn't exist! (correct name is XMinusWidth)
print(data.XHalfWidth)            # prints 1.5 — but it's a Python attribute, not Zemax
# The actual XMinusWidth in the model remains 0.
```

**Defenses:**

1. **Probe before guessing.** Run `scripts/probe_object_properties.py` (in this skill) for any unfamiliar object type. It prints all real typed properties.

2. **Verify in OpticStudio when in doubt.** Save the file with `TheSystem.SaveAs(...)` and open it in the Zemax GUI. The Component Editor will show actual values, not Python attribute shadows.

3. **For DetectorRectangle: use cell-based access too.** Even with correct property names, DetectorRectangle's ObjectData setters sometimes do not persist to the saved `.zos` file (the readback still shows the right values during the session, but the file on disk is wrong). Belt-and-suspenders pattern:

   ```python
   OC = ZOSAPI.Editors.NCE.ObjectColumn
   det.GetObjectCell(OC.Par1).DoubleValue = 1.0      # XHalfWidth
   det.GetObjectCell(OC.Par2).DoubleValue = 1.0      # YHalfWidth
   det.GetObjectCell(OC.Par3).IntegerValue = 100     # NumberXPixels
   det.GetObjectCell(OC.Par4).IntegerValue = 100     # NumberYPixels
   ddata = det.get_ObjectData().__implementation__   # ALSO set via ObjectData
   ddata.XHalfWidth = ddata.YHalfWidth = 1.0
   ddata.NumberXPixels = ddata.NumberYPixels = 100
   ```

   For DetectorRectangle, ParN is reliable: Par1=`XHalfWidth`, Par2=`YHalfWidth`, Par3=`NumberXPixels`, Par4=`NumberYPixels`. This is **not** generally true for other object types.

4. **Load-bearing strings on "cosmetic-looking" fields.** A few free-form text fields are not just labels — Zemax persists structural data through them and reads them back on `LoadFile`. Most notable: **`surf.Comment` on a `BlackBoxLens` surface stores the `.ZBB` filename**. Overwriting it with descriptive text ("input stage") doesn't error, but the next time the lens loads, OpticStudio looks for a `.ZBB` named after whatever string is now in the comment and fails. Treat the comment field as load-bearing on BB surfaces — leave it alone, or write the filename verbatim. Inspect any vendor `.ZMX` (e.g. `VendorLens_BB.ZMX`) to see the pattern: `SURF 2  COMM VendorLens.ZBB`. Other surface types treat Comment as cosmetic; this is BB-specific.

## Bonus: `dir()` doesn't enumerate .NET properties cleanly

`dir(obj)` on a pythonnet wrapper returns a noisy mix of Python methods, .NET getters/setters (`get_X`, `set_X`), and the typed properties — but only some of them, and the listing isn't reliable. For probing, prefer `dir(obj.__implementation__)` filtered to entries that don't start with `_`, `get_`, `set_`, or `Par` and are capitalized. The probe script does exactly this.

## 6. 2D `System.Double[,]` arrays: don't trust `list()` / `np.reshape` order

```python
ym = series.YData                           # IMatrixData with 2D .Data (System.Double[,])
flat = list(ym.Data)                        # WRONG — pythonnet's flatten order is not documented and varies
arr = np.array(flat).reshape(ym.Rows, ym.Cols)   # may transpose, may interleave columns
```

**Why:** A pythonnet `System.Double[,]` is enumerated by the .NET CLR, not by numpy. `list(arr_2d)` and `np.reshape` both rely on the iteration order being row-major contiguous, but the pythonnet 3.x bridge does not guarantee that — agents have seen the resulting numpy arrays come back transposed, with columns interleaved, or just plain wrong. The flat order silently changes between operands (`IMatrixData`, `IAR_DataGrid.Values`, batch ray-trace output) and sometimes between pythonnet versions.

**The trap:** the array shape is right, the dtype is right, no error is raised. Only the values are scrambled — and the scramble is usually a permutation that *looks* like real data (smooth, monotonic in places), so it passes a casual sanity check.

**Fix:** use the explicit `(row, col)` indexer that every 2D ZOS-API container exposes:

| Container | Indexer |
|---|---|
| `IMatrixData` (DataSeries `YData`) | `m.GetValueAt(row, col)` |
| `IAR_DataGrid` | `g.XYZ(row, col)` (returns `(x, y, z)` tuple) — or pull each row with `g.X(r)` / `g.Y(c)` and `g.Values[r, c]` indexed via `m.GetValueAt` style |
| Detector grid (NSC) | use `NCE.GetCoherentDataSafe(det, x_pix, y_pix, ...)` per pixel, or read sequentially via the `NCE.GetAllCoherentDataSafe` 1D buffer with the documented row-major stride |

```python
# Safe pattern:
ym = series.YData
arr = np.array([[ym.GetValueAt(r, c) for c in range(ym.Cols)] for r in range(ym.Rows)])
```

For very large 2D outputs (POP grids, Detector Viewer at high sampling), the per-cell loop is slow. The `zos.reshape(...)` helper in `boilerplate.md` *does* handle the flatten correctly (it uses the .NET `GetLength` / `GetValue` API rather than Python iteration) — pass `transpose=True` and verify against a known-shape test grid before trusting it on real data. When in doubt, `GetValueAt` per-cell is the only path that's verified safe.

## Loud failures: look it up, don't catch

The first five gotchas above are about **silent** failures — the script "succeeds" but the model is wrong. The opposite class of bug is **loud** failure: a `System.ArgumentException`, `TypeError`, or `AttributeError` fires. Loud failures are *gifts* — the API is telling you which assumption is wrong. The recurring antipattern is to wrap the failing call in `try/except` and try the alternative setter, treating the exception as noise to be suppressed.

```python
# WRONG — antipattern
def _set_cell(cell, value):
    """Tolerant of Int-vs-Double cell type."""
    try:
        cell.IntegerValue = int(value)
    except Exception:
        cell.DoubleValue = float(value)
```

**Why this is wrong, even though it "works":**

1. **The cell type is documented.** Every editor cell (MFE operand cell, LDE surface parameter, NCE ParN, MCE operand cell) has a defined type per the operand/object/surface. The `MeritOperandType.RSCE` operand has `Surf=int, Wave=int, Hx=double, Hy=double, Px=double, Py=double` — verifiable in the CHM via `chmseek_zos.py search "MeritOperandType.RSCE"`. There is no ambiguity to defend against.
2. **The wrapper hides real bugs.** A typo in cell index, a stale assumption about an operand's layout, or passing the wrong variable silently gets retried with the alternative setter and may succeed (truncating `0.7` to `0`, setting a surface number to `1` from a `1.5` you meant to fix). The original exception was the signal that something was wrong.
3. **Heuristics on the value type are backward.** "If `value.is_integer()` use `IntegerValue`" gets it wrong for any cell that wants `0.0` on a Double-typed input (Hx=0, Py=0, Wavelength=0.473, etc.). The right type is determined by the **cell**, not by what value you happen to be passing.

**Right response when an exception fires:**

| Exception | What to look up |
|---|---|
| `System.ArgumentException: Expected Integer, got 'Double'` (or reverse) | The cell's expected type. `chmseek_zos.py search "<MeritOperandType / object / surface name>"` returns per-cell layout. |
| `AttributeError` on a setter | Real property name. `dir(obj.__implementation__)` after the `__implementation__` cast (gotcha #1), then `chmseek` to confirm. |
| `System.NullReferenceException` | A required prerequisite (variable not marked, surface not stop, file not loaded). Trace back to what you set last. |
| Silent attribute creation (#5 above — loud in spirit, not in form) | Probe the type. `chmseek` for the documented name. |

**The genuinely-undocumented exceptions** — the only places try/fallback is the right answer:
- MCE `IGNR` cell (integer-typed, undocumented)
- Coordinate Break `Order` parameter cell (integer-typed in an otherwise-double row)
- A handful of NSC ParN cells where the int/double split varies by object type

For those three corners, the try/fallback is a defense against an undocumented edge case. **Everywhere else**, an exception is a debugging tool — `chmseek_zos.py` is the lookup. See `SKILL.md` "Bundled tooling" → chmseek for the discovery-vs-debugging framing.
