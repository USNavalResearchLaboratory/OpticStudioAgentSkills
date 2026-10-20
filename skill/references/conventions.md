# NSC Conventions: Tilts, Coatings, Materials, Ray Tracing

## Mirror tilt sign convention

Empirical, verified in v24.1 — does not match the naive right-hand-rule prediction.

```
+Z beam, TiltAboutY = +45°  →  reflects to -X
+Z beam, TiltAboutY = -45°  →  reflects to +X
```

For arbitrary tilts, the reflection formulas are:

```
+Z beam, TiltAboutY = θ  →  reflected direction = (-sin(2θ), 0, -cos(2θ))
-X beam, TiltAboutY = θ  →  reflected direction = (-cos(2θ), 0,  sin(2θ))
```

**Always sketch the beam path** before committing to a tilt. The most reliable way to get geometry right is to write a small probe script that places a source, a single tilted mirror, and a detector, then checks where the beam lands.

For non-trivial tilts (not multiples of 45°), use `np.degrees(np.arctan2(...))` to convert beam-direction vectors back into TiltAboutY values:

```python
# To align an object's local +Z with a desired direction d (in XZ plane):
tilt_y = np.degrees(np.arctan2(d[0], d[2]))
```

## Mirrors: use `Material = 'MIRROR'`

```python
m.Material = 'MIRROR'
```

This works for all tilt angles and is the reliable way to make a surface reflective. **Reflective coatings on bare air-to-air StandardSurfaces are silently ignored** — Zemax only evaluates coatings at material boundaries.

## Coatings: only at material transitions

Coatings (`I.50`, `I.99`, `CUBE_POL_45DEG_21L`, etc.) require a glass-air or glass-glass interface. They do nothing on a bare StandardSurface in air.

For a partial-reflection beam splitter, model the BS as a thin RectangularVolume of glass (e.g. `N-BK7`) and apply the coating to a face.

### RectangularVolume face numbering

Faces on a RectangularVolume are indexed:
- **Face 0** = object default — applies to **all** faces simultaneously. Useful for setting a uniform property, but **not** for putting a single coating on the entry face (it'll appear on every face, causing parasitic splits at every internal interface).
- **Face 1** = front face (–Z in local frame, before tilt)
- **Face 2** = back face (+Z in local frame, before tilt)
- Faces 3–6 = side faces (±X, ±Y)

For a volume tilted +45° about Y, a +Z beam enters through what was the **back face (face 2)** in the local frame. A 50/50 coating on face 2 splits the entering beam: 50% reflects (going -X) and 50% transmits into the glass.

```python
bs.CoatScatterData.GetFaceData(0).Coating = ''         # clear default
bs.CoatScatterData.GetFaceData(2).Coating = 'I.50'     # coat entry face only
```

If the wrong face is coated, the reflected beam will go in an unexpected direction (often back along -Z toward the source) and the model will look "almost right" — the transmitted arm works but the reflected arm is missing or weak. When debugging, check the saved `.zos` in the GUI to see which face actually has the coating.

### Common built-in coatings

| Coating | Behavior |
|---------|----------|
| `I.0` | Perfect AR (100% transmit) |
| `I.50` | 50/50 beam splitter (intensity, polarization-independent) |
| `I.99` | Perfect mirror (use `Material = 'MIRROR'` instead for clarity) |
| `CUBE_POL_45DEG_21L` | Polarizing beam splitter at 45° AOI (transmits p, reflects s) — needs glass surface |

## Birefringent materials (waveplates)

Load the catalog before assigning a birefringent material:

```python
TheSystem.SystemData.MaterialCatalogs.AddCatalog("BIREFRINGENT")
obj.Material = 'QUARTZ'    # also CALCITE, LINBO3, etc.
```

The BIREFRINGENT catalog includes ordinary and extraordinary variants (e.g. `QUARTZ` and `QUARTZ-E`). For waveplate modeling, `QUARTZ` works.

For ordinary/extraordinary ray splitting at birefringent interfaces, the ray trace must have `SplitNSCRays = True` (see below).

To verify the catalog loaded and the material is accepted:

```python
tmp = NCE.GetObjectAt(1)
tmp.ChangeType(tmp.GetObjectTypeSettings(OT.CylinderVolume))
tmp.Material = 'QUARTZ'
print(tmp.Material)        # should print 'QUARTZ', not '' or 'N-BK7'
```

A waveplate's quarter-wave thickness is `t = λ / (4·Δn)`. For quartz at 473 nm: `Δn ≈ 0.0091`, so `t ≈ 13 µm`. Set this as `ZLength` on a CylinderVolume.

## NSC placement: `RefObject`, `InsideOf`, and nesting rules

NSC objects live in 3D space with two independent placement concepts that catch agents off-guard. Both are cells on `INCERow` (so `row.RefObject` / `row.InsideOf` for the integer, or `row.RefObjectCell` / `row.InsideOfCell` for the cell with its solve handles).

### `RefObject` — coordinate cascade

Each object's `XPosition` / `YPosition` / `ZPosition` / `TiltAboutX/Y/Z` are measured **relative to its `RefObject`** (default `0` = the NSC group vertex). Changing one object cascades to every downstream object that references it. Two flavors:

- **Absolute reference**: `RefObject = N` (N > 0) means "coordinates of this object are in the frame of object N." Object N must precede this object in the editor.
- **Relative reference**: `RefObject = -k` (negative) means "reference object is `(this_object_number - k)`." E.g. on object 8 with `RefObject = -3`, the reference is object 5. Useful for copy/pasting object groups — relative refs stay valid when the group is moved or duplicated.

**Why this bites:** if you move a lens by editing its `ZPosition`, every downstream object whose `RefObject` chains back to that lens shifts too. Apparent symptoms: "I moved the input lens by 5 mm and now the detector reports nothing" — because the detector's `RefObject` was the lens (directly or via chain), and the detector physically moved 5 mm with it.

**Defensive pattern:** before editing positions, walk the `RefObject` chain to see who depends on what:
```python
for i in range(1, NCE.NumberOfObjects + 1):
    o = NCE.GetObjectAt(i)
    print(f"#{i} {o.TypeName!r}  Z={o.ZPosition:.3f}  RefObject={o.RefObject}  InsideOf={o.InsideOf}")
```

#### Reading true positions back: `ZPosition` is parent-relative, not global

The same `RefObject` rule that bites on writes also bites on **reads**, and it's worse for converted seeds. **`ZPosition` is the offset in the `RefObject` parent's frame — raw `ZPosition` values from different objects are NOT in a common frame and cannot be compared or differenced directly.**

`OpenConvertToNSCGroup` makes this concrete: a `.zmx` with a **leading flat dummy surface** (very common — vendors add an N mm shoulder in front of the first real surface) converts to a `RefObject` chain with an offset null in front. Example: AC508-180 has a 5 mm leading dummy, so the converter writes the crown referenced through a −5 mm null and the flint at a *relative* offset. An agent that reads raw `ZPosition` (e.g. crown=12, flint=7) and treats them as a common frame places the flint at local 7 mm — **buried 5 mm inside the 12 mm crown.** The trace runs; the doublet shape is wrong; the spot is garbage.

Two ways to get the **true global position** of an object:

1. **`GetMatrix()` — canonical, robust.** Returns the rotation matrix and global offset of an object relative to the NSC group origin, with the whole `RefObject` chain already resolved. No manual summing.
   ```python
   # Python: out-params come back as a tuple; pass placeholders for each out arg.
   res = NCE.GetMatrix(obj_num, 0,0,0, 0,0,0, 0,0,0, 0.0,0.0,0.0)
   ok, R11,R12,R13, R21,R22,R23, R31,R32,R33, Xo,Yo,Zo = res
   # Xo, Yo, Zo are the object's TRUE global coordinates (chain already applied).
   ```
2. **Sum `ZPosition` up the chain manually** — only if you can't use `GetMatrix` (e.g. you also need to rewrite the chain). Walk `RefObject` to the root, accumulating each link's `ZPosition` (and, if any link is tilted, composing the rotation — at which point just use `GetMatrix`).

**Also whitelist lens-bearing object types when iterating a converted seed.** Converters emit more than lenses — stray `Source`, `Detector`, and dummy objects appear in the seed too. Cloning "every object" as a lens mis-clones those. Match against an explicit allow-list (`Standard Lens` / `Even Asphere Lens` / whatever the seed actually contains), not a blocklist.

### `InsideOf` — refractive-index parent

`InsideOf` declares which volume's refractive material the object lives in. **Default `0` means "the NSC group's global medium" (usually air).** Set it when:
- You place a **source inside a refractive volume** (e.g. an LED die embedded in encapsulant). Without setting `InsideOf`, rays leave the source in air, then "refract" entering the encapsulant from inside, which is physically wrong.
- You **nest a smaller volume inside a larger one** to create a hole or composite (e.g. an air bubble inside glass). The inner object's `InsideOf` must point to the outer one for the index calculation to track correctly.

`InsideOf` and `RefObject` are independent — placing an object inside another for index purposes is a separate concept from placing its coordinate frame relative to another.

### Grouping multi-element parts under a Null Object parent

**The recurring failure:** an agent loads an achromat doublet seed (two singlets — crown + flint), then tries to "move the doublet" by setting `ZPosition` on one of the singlets. The other singlet stays put. The two glasses separate. Spot diagram collapses to garbage. Same failure for any multi-element NSC seed: cemented triplets, beam-shaper assemblies, prism+lens packages, anything converted via `OpenConvertToNSCGroup` from a `.zmx` (see `sequential-design.md`).

**The fix is the standard NSC grouping pattern: insert a Null Object as the coordinate parent and point every child at it via `RefObject`.** Null Object is a non-geometric placeholder; its only job is to act as a coordinate origin. Move the parent → every child whose `RefObject` chains to it moves rigidly with it.

```python
OT = ZOSAPI.Editors.NCE.ObjectType

def group_under_null_parent(NCE, child_indices, parent_z=0.0,
                            parent_x=0.0, parent_y=0.0,
                            parent_comment='group parent'):
    """Insert a Null Object before the first child and make every child reference it.

    child_indices: list of 1-based object numbers to be grouped (must be contiguous,
                   or all numerically greater than the parent's insertion point).
    Returns the parent's object number.
    """
    parent_idx = min(child_indices)                  # parent must precede children in the editor

    # 1) Insert the parent at the group's position. InsertNewObjectAt shifts everything down by 1.
    NCE.InsertNewObjectAt(parent_idx)
    parent = NCE.GetObjectAt(parent_idx)
    parent.ChangeType(parent.GetObjectTypeSettings(OT.NullObject))
    parent.Comment = parent_comment
    # The parent itself is referenced to whatever the first child WAS referenced to (default 0)
    parent.XPosition = float(parent_x)
    parent.YPosition = float(parent_y)
    parent.ZPosition = float(parent_z)
    parent.TiltAboutX = 0.0; parent.TiltAboutY = 0.0; parent.TiltAboutZ = 0.0

    # 2) For each child (now at index+1 because of the insert), rebind its frame:
    #    - RefObject -> parent
    #    - Absolute coords in the parent's local frame (i.e. relative to the group's origin)
    for old_idx in child_indices:
        new_idx = old_idx + 1                        # everything shifted by the insert
        child = NCE.GetObjectAt(new_idx)
        # Capture the child's absolute Z (from the .zmx prescription, before grouping):
        child_z_abs = float(child.ZPosition)
        # Re-express the child's frame relative to the parent's origin:
        child.RefObject = parent_idx
        child.ZPosition = child_z_abs - parent_z     # local Z in parent's frame
        # X/Y/tilts handled the same way if the parent has non-zero offsets

    return parent_idx

# Usage: after converting an AC508-080-A .zmx (which produces 2 Standard Lens objects):
parent = group_under_null_parent(NCE, child_indices=[1, 2],
                                 parent_z=0.0, parent_comment='AC508-080-A doublet')
# Now move the whole doublet 50 mm downstream with a single edit:
NCE.GetObjectAt(parent).ZPosition = 50.0
```

**Why this works:** the CHM rule from above — coordinates are evaluated relative to `RefObject`. A child with `RefObject = parent` and `ZPosition = +5` sits 5 mm in front of the parent's origin, in the parent's tilted/rotated frame. Editing the parent's `ZPosition` shifts both children together; editing `TiltAboutY` rotates the whole assembly about the parent's local Y.

**Common gotchas:**
- **Insertion shifts indices.** After `InsertNewObjectAt(parent_idx)`, every object at or after `parent_idx` shifts down by 1. The helper above accounts for this; don't try to keep the old indices.
- **Parent must precede children in the editor.** CHM rule: "the reference object must precede in the object list the object whose coordinates are being referenced." If your child indices include something *before* the planned parent insertion point, group them by inserting the parent at the lowest index of the set.
- **Re-express coords in the parent's frame.** When you reparent, the child's `XPosition/YPosition/ZPosition` numbers don't change meaning automatically — they're now interpreted in the parent's frame. Subtract the parent's absolute offset from each child's absolute position to keep the geometry visually identical after the reparent. (Tilts compose multiplicatively — if the parent has no tilt, child tilts are unchanged.)
- **Negative-relative refs are an alternative for templated groups.** `RefObject = -1` on each child means "previous object" — useful when you'll copy/paste the group repeatedly. Less explicit than naming a Null Object parent; pick based on whether the group will be cloned or whether agents will edit it by name.
- **A child cannot be the parent's `RefObject` ancestor.** No cycles; the API will reject `RefObject` values that create a loop.

This pattern is also the right answer for: prism + folding mirror assemblies that pivot together, a lens + iris stack that translates as a unit, telescope tubes containing a primary + secondary that align as a rigid body.

### Volume/surface nesting at shared boundaries

When two objects share a boundary (touch or overlap at the same point in space), Zemax's deterministic tie-breaker is: **the last object listed in the NCE wins.** Order in the editor is geometry-meaningful, not cosmetic. Two specific rules from the CHM:

1. **Volumes**: "if a ray strikes more than one object at the exact same point in space, the last object listed determines the properties of the surface or volume at that point." So to model an air bubble inside glass: glass first, air-volume second; the shared boundary at the bubble's surface acts as glass→air. Reversing the order makes it act as air→glass at the inner boundary, with confusing index tracking.
2. **Surfaces vs. volumes**: "Surface objects may not share boundaries with volume objects **unless** the surface is reflective or absorbing, **or** the volume is listed after the surface." Practical case: a mirror surface flush against a window face — either mark the mirror reflective (so the mirror "wins" the boundary by virtue of being a hard interface), or list the window volume *after* the mirror so the volume's boundary properties dominate.
3. **Only Standard Surface** supports nesting today; other surface types may not nest cleanly with volumes.

### Glue distance and "Maximum Nested/Touching Objects"

Two `SystemData.NonSequentialData` knobs control how forgiving the trace is at shared boundaries:

```python
NSD = TheSystem.SystemData.NonSequentialData       # ISDNonSeqData
NSD.GlueDistanceInLensUnits = 1e-6                  # default; below this, two objects are "in contact"
NSD.MaximumNestedTouchingObjects = 4                # default; must be >= number sharing a common point
NSD.MaximumIntersectionsPerRay = 4000               # default 100; raise for high-bounce-count scenes
NSD.MaximumSegmentsPerRay = 4000                    # default 4000; raise when ray-split trees are deep
```

- **GlueDistance**: object spacings *near* this value cause geometry errors. If two objects should touch, set their separation **much smaller** than glue distance (or exactly equal). If they should be separate, set the spacing **much larger**. Spacings within 2-3× the glue distance produce inconsistent traces.
- **MaximumNestedTouchingObjects**: must be at least the count of objects sharing a single point in space. A common scene with a window between two media (air → glass → coating → air) needs at least 3-4. The default 4 covers most setups; raise when you have many touching boundaries (mounts, multi-layer stacks).

### Geometry-error recovery in the 3D Layout

When NSC 3D Layout shows "Geometry error" instead of rendering, ray tracing has aborted on an invalid geometry but the editor data is fine. To diagnose:

| Approach | API path | Purpose |
|---|---|---|
| Set source's `NumberOfLayoutRays = 0` | `src_data.NumberOfLayoutRays = 0` on each source object | No rays are traced for layout → no trace errors → renders the geometry only, so you can see where objects collide |
| `IgnoreErrors = True` on the ray-trace tool | `rt.IgnoreErrors = True` (see ray-trace section below) | Doesn't help the layout itself, but lets `OpenNSCRayTrace` complete past failing rays — combined with detector data extraction this confirms whether the design works geometrically even if the layout won't render |
| Use NSC Shaded Model export instead | `Tools.Layouts.OpenNSCShadedModelExport()` (see `analyses.md`) | More robust than the 3D Layout; renders filled surfaces and tolerates many geometry conditions that crash the layout |
| Force a system update | `TheSystem.UpdateStatus()` returns any error text | Equivalent to `Ctrl+Shift+U` in the GUI; flushes cached state |
| Save and reopen | `SaveAs(...)` + visual review in GUI | Last resort; sometimes the editor sees the truth that the layout cache doesn't |

The GUI also has a "Create Error Ray" diagnostic that inserts a SourceRay at the exact failure coordinates and zeroes other rays — accessible interactively, not via the API. If a build script's layout export is failing, switch to the shaded-model export for the artifact pass and use `OpenNSCRayTrace` (with `IgnoreErrors=True`) for the data pass; the two are independent.

## NSC ray-trace settings

```python
rt = TheSystem.Tools.OpenNSCRayTrace()
rt.SplitNSCRays = True       # required for partial-reflection coatings AND birefringent splitting
rt.ScatterNSCRays = False    # set True only if any object has scatter properties
rt.UsePolarization = True    # required for polarization-aware tracing (Jx/Jy, QWPs, PBS coatings)
rt.IgnoreErrors = True       # don't abort on individual ray failures
rt.SaveRays = False          # set True to dump all rays to .ZRD (large!)
rt.ClearDetectors(0)         # zero all detectors before tracing (essential for sweeps)
rt.RunAndWaitForCompletion()
rt.Close()
```

| Setting | When to enable |
|---------|----------------|
| `SplitNSCRays` | Coatings on glass surfaces (Fresnel + coating split rays); birefringent o/e splitting |
| `ScatterNSCRays` | Diffuse scatter (any `CoatScatterData.GetFaceData(n).CreateScatterModelSettings(...)`) |
| `UsePolarization` | Anything involving Jx/Jy, waveplates, PBS coatings, polarization-dependent transmission |
| `IgnoreErrors` | Almost always — otherwise one bad ray aborts the entire trace |
| `ClearDetectors(0)` | Always before a trace if you've run before; pass `0` to clear all detectors |

For a polarization-sensitive interference setup (PBS + QWPs): `SplitNSCRays = True`, `UsePolarization = True`, `ScatterNSCRays = False`, `IgnoreErrors = True`.

**Stronger one-instance restriction for NSC ray traces** (per the `INSCRayTrace` interface page in `ZOS-API.chm`): only **one `INSCRayTrace` instance can exist at a time across ALL `IOpticalSystem` instances**, not just within a single system. The first `OpenNSCRayTrace()` succeeds; subsequent calls return `null` until that instance is closed. If you're orchestrating multiple systems in the same process (e.g. comparing two NSC designs), serialize the NSC trace calls — open, run, close, then move to the next system.

Other NSC-trace properties worth knowing about (also from the interface page; not currently used in this skill's examples):
- `SavePaths` / `SavePathsFile` — separate from `SaveRays`; persists path data, not ray segments
- `Filter` — ZRD filter string applied during the trace itself (not just at playback)
- `ZRDFormat` / `ZRDFormatType` — choose ZRD format variant
- `IsRunning`, `RunStatus`, `HPCRunState`, `RunAndWaitWithTimeout` — finer-grained run control
- random-seed methods — set or clear an explicit seed for reproducible traces

## Casting numpy values

`pythonnet` rejects `numpy.float64` and `numpy.int64` for `XPosition`, `YPosition`, `TiltAboutY`, etc. Cast explicitly:

```python
obj.XPosition = float(pos[0])
obj.TiltAboutY = float(theta_deg)
```

This bites whenever positions/tilts are computed in numpy and assigned directly.
