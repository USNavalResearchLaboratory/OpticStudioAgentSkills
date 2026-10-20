# NSC Object ObjectData Properties (v24.1)

Property names below were probed from a live ZOS-API session — they are the names actually exposed by `obj.get_ObjectData().__implementation__`. ParN cell numbers do **not** match the GUI column order for most types; use the typed properties unless explicitly noted.

For any object type not listed here, run `scripts/probe_object_properties.py` to discover its properties before guessing.

## SourceDiode — finite-aperture Gaussian beam (preferred for laser modeling)

```python
data = src.get_ObjectData().__implementation__
data.XMinusWidth = 1.5          # mm, 1/e² half-width (X waist)
data.YMinusWidth = 1.5          # mm, 1/e² half-width (Y waist)
data.XMinusDivergence = 0.043   # degrees, 1/e² half-angle
data.YMinusDivergence = 0.043   # degrees
data.Power = 0.2                # Watts
data.NumberOfLayoutRays = 100
data.NumberOfAnalysisRays = 10_000_000
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `NumberOfLayoutRays` | Int | 0 | Layout rays for 3D view |
| `NumberOfAnalysisRays` | Int | 0 | Rays traced for analysis |
| `Power` | Double | 1.0 | Source power (Watts) |
| `ColorNumber` | Int | 0 | Color/wavelength index |
| `WaveNumber` | Int | 0 | Wave number index |
| `XMinusWidth` | Double | 0.0 | X half-width at 1/e² (mm) |
| `YMinusWidth` | Double | 0.0 | Y half-width at 1/e² (mm) |
| `XMinusDivergence` | Double | 0.0 | X divergence half-angle (deg) |
| `YMinusDivergence` | Double | 0.0 | Y divergence half-angle (deg) |
| `XMinusSuperGauss` | Double | 0.01 | Super-Gaussian exponent X (raise for flat-top) |
| `YMinusSuperGauss` | Double | 0.01 | Super-Gaussian exponent Y |
| `NumberX` / `NumberY` | Int | 1 | Source grid points |
| `Astigmatism` | Double | 0.0 | Beam astigmatism |
| `DeltaX` / `DeltaY` | Double | 0.0 | Source point offset |

**Critical:** the property is `XMinusWidth`, **not** `XHalfWidth`. The latter does not exist on SourceDiode and silently creates a Python attribute. There are no `XPlus*` properties either — the "Minus" name covers the symmetric case.

## SourceGaussian — point source with angular Gaussian distribution

Avoid for coherent simulations. The angular spread introduces phase noise at the detector; SourceDiode's finite aperture gives clean coherent fringes via Huygens summation.

ParN access is reliable for SourceGaussian:

| Par | Type | Description |
|-----|------|-------------|
| 1 | Int | Layout Rays |
| 2 | Int | Analysis Rays |
| 3 | Double | Power (Watts) |
| 6 | Double | Beam Size — 1/e² radius (mm) |
| 7 | Double | Position — distance from virtual divergence point (mm); 0 = collimated |

## DetectorRectangle

```python
ddata = det.get_ObjectData().__implementation__
ddata.XHalfWidth = 0.25     # mm
ddata.YHalfWidth = 0.25     # mm
ddata.NumberXPixels = 500
ddata.NumberYPixels = 20
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `XHalfWidth` | Double | 1.0 | X half-width (mm) |
| `YHalfWidth` | Double | 1.0 | Y half-width (mm) |
| `NumberXPixels` | Int | 1 | Pixels in X (default is 1!) |
| `NumberYPixels` | Int | 1 | Pixels in Y |
| `DataType` | Int | 0 | Detector data type |
| `Polarization` | Int | 0 | Polarization mode |
| `Smoothing` | Int | 0 | Smoothing setting |

**Persistence quirk:** DetectorRectangle ObjectData setters sometimes don't write through to the saved `.zos` file. The session readback shows the correct values, but opening the saved file in OpticStudio shows defaults. Set both ObjectData AND ParN cells:

```python
OC = ZOSAPI.Editors.NCE.ObjectColumn
det.GetObjectCell(OC.Par1).DoubleValue = DET_HALF_WIDTH
det.GetObjectCell(OC.Par2).DoubleValue = DET_HALF_WIDTH
det.GetObjectCell(OC.Par3).IntegerValue = DET_NX
det.GetObjectCell(OC.Par4).IntegerValue = DET_NY
ddata = det.get_ObjectData().__implementation__
ddata.XHalfWidth = DET_HALF_WIDTH
ddata.YHalfWidth = DET_HALF_WIDTH
ddata.NumberXPixels = DET_NX
ddata.NumberYPixels = DET_NY
```

**Orientation:** the detector's active face is in the XY plane (normal = +Z) by default. A beam traveling in the XY plane (e.g. ±X direction) grazes the face and registers zero power. Tilt to face the beam — `TiltAboutY = 90°` for a +X beam, `TiltAboutY = -45°` for a beam traveling along (-1,0,1)/√2.

**A detector interacts with rays according to its `Material`, so it can double as a mirror or an absorber.** Per the Detector Rectangle Object help: *"Detector rectangles may be reflective, transparent, or absorbing if the material is set to `MIRROR`, blank, or `ABSORB`, respectively."* The same rule is documented verbatim for the Surface, Color, and Polar detectors — set `det.Material` exactly as for any other NSC object:

```python
det.Material = ''         # blank (default) → transparent: rays record AND pass through
det.Material = 'MIRROR'   # detector records the hit AND reflects the ray (fold mirror + tap)
det.Material = 'ABSORB'   # detector records the hit AND terminates the ray (beam dump / baffle)
```

Why this matters:
- **Transparent (blank)** is the default and the usual choice — an in-line probe that samples the beam without disturbing downstream optics. If you drop a detector mid-beam and downstream objects go dark, the detector is likely absorbing/reflecting; check its `Material`.
- **`MIRROR`** lets one object both fold the beam and tap the irradiance at the fold — no separate mirror needed.
- **`ABSORB`** makes the detector a measuring beam dump or baffle that reads the flux it kills.

The **Front Only** flag (Par10) is applied *before* materials are considered. Per the help: a detector with Front Only = 1 and a `MIRROR` material "would reflect rays from the front and ignore all rays from the back side," where "back" faces the positive local Z axis. So Front Only + `MIRROR` gives a one-sided mirror-tap.

## StandardSurface — flat or curved (mirrors, refracting surfaces, beam splitters)

```python
mdata = m.get_ObjectData().__implementation__
mdata.Radius = 0.0            # 0 = flat
mdata.MaxAperture = 25.0      # mm — DEFAULT IS 1mm
m.Material = 'MIRROR'         # makes it reflective
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `Radius` | Double | 0.0 | Radius of curvature (0 = flat / infinite) |
| `Conic` | Double | 0.0 | Conic constant |
| `MaxAperture` | Double | **1.0** | Max aperture (mm) — **default is only 1 mm!** |
| `MinAperture` | Double | 0.0 | Min aperture (mm, for annular shapes) |

The 1mm default aperture is the most common cause of "no rays make it through" in NSC scenes. Always set `MaxAperture` explicitly.

For a mirror, set `obj.Material = 'MIRROR'` after configuring the surface — this is the reliable way to make a surface reflective. Reflective coatings on bare air-to-air StandardSurfaces are silently ignored.

## RectangularVolume — beam splitter plates, PBS cubes, glass blocks

```python
bsdata = bs.get_ObjectData().__implementation__
bsdata.X1HalfWidth = 25.0
bsdata.Y1HalfWidth = 25.0
bsdata.ZLength = 0.5
bsdata.X2HalfWidth = 25.0
bsdata.Y2HalfWidth = 25.0
bs.Material = 'N-BK7'
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `X1HalfWidth` | Double | 1.0 | Front X half-width (mm) |
| `Y1HalfWidth` | Double | 1.0 | Front Y half-width (mm) |
| `ZLength` | Double | 1.0 | Thickness/length (mm) |
| `X2HalfWidth` | Double | 1.0 | Back X half-width (mm) |
| `Y2HalfWidth` | Double | 1.0 | Back Y half-width (mm) |
| `FrontXAngle` / `FrontYAngle` | Double | 0.0 | Front face tilt (deg) |
| `RearXAngle` / `RearYAngle` | Double | 0.0 | Rear face tilt (deg) |

For a tilted beam splitter, lateral displacement of the transmitted beam scales with thickness — keep `ZLength` small (0.05 mm) for thin-plate approximations. See `conventions.md` for face numbering when applying coatings.

## CylinderVolume — waveplates, cylindrical optics

```python
qdata = q.get_ObjectData().__implementation__
qdata.FrontR = 12.5     # front radius (mm)
qdata.BackR = 12.5      # back radius (mm)
qdata.ZLength = 0.013   # thickness (mm)
```

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `FrontR` | Double | 1.0 | Front radius (mm) |
| `BackR` | Double | 1.0 | Back radius (mm) |
| `ZLength` | Double | 1.0 | Thickness (mm) |

**Trap:** the GUI/ParN order is *not* `FrontR, BackR, ZLength`. The actual cell mapping is **Par1=FrontR, Par2=ZLength, Par3=BackR**. Setting `Par2 = thickness` puts the thickness in the wrong slot and silently builds a "waveplate" with thickness in the back-radius slot. Always use the typed `FrontR`/`BackR`/`ZLength` properties — never ParN for this type.

## Freeform / asphere / illumination objects (collimators, concentrators, far-field)

The objects below build refractive/TIR collimators and non-imaging optics, plus
the angular detector and the Lambertian-style source they need. **Property names
here are probe-verified against v24.1** (`scripts/probe_object_properties.py`) —
the GUI CHM only documents Par# layouts, and the typed names do NOT follow the
Par# order or the CHM's "α1–α8" labels. Defaults/types weren't exhaustively
probed, so the tables list Property / Meaning only; set every property
explicitly (same discipline as the `MaxAperture`=1mm trap above). The full
object set is 121 types — enumerate with
`for v in System.Enum.GetValues(ZOSAPI.Editors.NCE.ObjectType): print(v)`.

**Enum-spelling traps (verified v24.1):** the NSC lens object is
`ObjectType.EvenAsphereLens` ("Asphere"), but the annular collar is
`AnnularAsphericLens` and the bare surface is `AsphericSurface` ("Aspheric") —
inconsistent, so don't pattern-match. The figure-of-revolution objects carry API
typos: `TabulatedFactedRadial` / `TabulatedFactedToroid` ("Facted") and
`TabulatedFrenselRadial` ("Frensel"). Probe or run `check_namespace.py` if a name
fails.

**TIR needs no configuration.** In NSC, rays past the critical angle reflect
automatically; with ray splitting OFF (the default) the transmitted path is
taken at a refractive boundary *unless* the ray TIRs — exactly what a TIR
collimator wants. Turn splitting on (System Explorer → Non-sequential) only to
quantify Fresnel/ghost losses, and note it then requires polarization ray
tracing. Make a collar a solid dielectric (`IsVolume`/glass material) for the
TIR bounce.

### EvenAsphereLens — aspheric central collimator lens (`ObjectType.EvenAsphereLens`)

Solid lens, even-asphere on both faces. Suffix `1` = front, `2` = rear.
`Coeff1OnRPowerN` is the front coefficient on rⁿ (N = 2,4,6,…,16); `Coeff2OnRPowerN` the rear.

| Property | Meaning |
|----------|---------|
| `Radius1` / `Radius2` | Front / rear radius of curvature (0 = flat) |
| `Conic1` / `Conic2` | Front / rear conic constant |
| `Coeff1OnRPower2` … `Coeff1OnRPower16` | Front even-asphere coeffs on r², r⁴, … r¹⁶ |
| `Coeff2OnRPower2` … `Coeff2OnRPower16` | Rear even-asphere coeffs on r², … r¹⁶ |
| `Clear1` / `Clear2` | Front / rear clear semi-diameter |
| `Edge1` / `Edge2` | Front / rear edge radial aperture |
| `Thickness` | Center thickness |

### StandardLens — spherical/conic central lens (`ObjectType.StandardLens`)

Simpler central lens (no asphere terms). Same `1`=front / `2`=rear convention.

| Property | Meaning |
|----------|---------|
| `Radius1` / `Radius2` | Front / rear radius (0 = flat) |
| `Conic1` / `Conic2` | Front / rear conic |
| `Clear1` / `Clear2` | Front / rear clear semi-diameter |
| `Edge1` / `Edge2` | Front / rear edge radial aperture |
| `Thickness` | Center thickness |

### AnnularAsphericLens — outer TIR collar (`ObjectType.AnnularAsphericLens`)

Annular solid, even-asphere on both faces, independent inner/outer aperture per
face. The natural outer ring of a TIR collimator: wide rays enter the inner wall,
TIR off the outer wall, exit collimated. Note `Front*`/`Rear*` naming here (not
`1`/`2`), and coefficients are `FrontRPowerN` / `RearRPowerN`.

| Property | Meaning |
|----------|---------|
| `FrontRadius` / `RearRadius` | Front / rear radius of curvature |
| `FrontConic` / `RearConic` | Front / rear conic |
| `FrontRPower2` … `FrontRPower16` | Front even-asphere coeffs on r² … r¹⁶ |
| `RearRPower2` … `RearRPower16` | Rear even-asphere coeffs on r² … r¹⁶ |
| `MinFrontAperture` / `MaxFrontAperture` | Front inner / outer radial aperture (the annulus) |
| `MinBackAperture` / `MaxBackAperture` | Rear inner / outer radial aperture |
| `Thickness` | Thickness (at `ThkAperture`) |
| `ThkAperture` | Radial height at which `Thickness` is defined |
| `Edge1` / `Edge2` | Front / rear edge radial aperture |

### CPC — compound parabolic concentrator / collimator collar (`ObjectType.CPC`)

Rotationally symmetric Winston cone. As-built it concentrates rays ≤ `AngleDegrees`
into the small end; run in reverse it collimates. `VolumeIndex` rescales the
acceptance angle via Snell and thereby sets the shape — **it does not auto-pick-up
from the assigned material**, so set it to the material index at your wavelength.

| Property | Meaning |
|----------|---------|
| `RadialAperture` | Radial aperture at z = 0 |
| `AngleDegrees` | Max acceptance/exit half-angle (deg) |
| `Length` | Length along local Z |
| `IsVolume` | 0 = hollow reflective shell; ≠0 = closed solid dielectric (TIR) |
| `VolumeIndex` | Index used to compute the shape (set to material n at λ) |

(`CPCRectangular` is the rectangular variant: `XAperture`/`XAngleDegrees`,
`YAperture`/`YAngleDegrees`, `Length`, `IsVolume`, `VolumeIndex`.)

### AsphericSurface — single asphere surface / reflector (`ObjectType.AsphericSurface`)

A surface, not a solid (use standalone as a mirror, or as a Compound Lens parent).
Coefficients are accessed by index via methods, not numbered properties.

| Property / method | Meaning |
|----------|---------|
| `Radius` | Radius of curvature |
| `Conic` | Conic constant |
| `MaxAperture` / `MinAperture` | Outer / inner radial aperture (annulus if Min > 0) |
| `NumberOfTerms` | # polynomial terms in use |
| `GetRPowerI(i)` / `SetRPowerI(i, v)` | Get/set the i-th polynomial coefficient |

(`CompoundLens` — general lens with different front/back parent surfaces — exposes
`FrontSurface`/`RearSurface` parent object numbers, `Thickness`,
`Front/RearClearRadius`, `Front/RearChipRadius`, `Front/RearEdgeRadius`,
`IsRectangle`. `TabulatedFactedRadial` — arbitrary profile-of-revolution from a
`.TOB` file — exposes `Scale`, `IsVolume`, `StartAngle`, `StopAngle`,
`Get/SetZoneIFacets(i)`.)

### DetectorPolar — far-field / angular (intensity-vs-angle) detector (`ObjectType.DetectorPolar`)

Faceted spherical-cap detector that records the **angle** of each ray (polar θ from
local +Z, azimuth φ), independent of where it lands — the detector for collimation
and far-field energy-in-cone. Read it with the `NSDP` operand (see
`nsc-illumination-design.md`).

| Property | Meaning |
|----------|---------|
| `MaxAngle` | Maximum polar half-angle captured (deg) |
| `RadialSize` | Physical detector size (must enclose the beam) |
| `NumberPPixels` | # polar (θ) pixels — the angular resolution |
| `NumberAPixels` | # azimuthal (φ) pixels |
| `Mirroring` | Symmetry-mirroring flag (0 = none) |

Like the other detectors, a DetectorPolar obeys its `Material`: blank = transparent (default), `MIRROR` = reflective, `ABSORB` = absorbing (see the DetectorRectangle note above).

### SourceRadial — Lambertian / custom angular-profile source (`ObjectType.SourceRadial`)

Models an LED with an arbitrary radial intensity-vs-angle profile (the way to get
a Lambertian/cosine LED). The profile is a table of sub-angles set by index.

| Property / method | Meaning |
|----------|---------|
| `NumberOfAnalysisRays` | Rays per trace — set high (1e6+); angular metrics are noisy |
| `NumberOfLayoutRays` | Rays drawn in layout views |
| `Power` | Source flux |
| `WaveNumber` / `ColorNumber` | Wavelength / color assignment |
| `MinAngle` / `MaxAngle` | Angular extent of emission (deg) |
| `NumberOfPoints` | # points in the radial intensity profile |
| `GetSubAngleI(i)` / `SetSubAngleI(i, v)` | Get/set the i-th profile sub-angle (build the cosine/Lambertian falloff here) |
| `XHalfWidth` / `YHalfWidth` | Emitting-area half-widths (étendue) |

### Slide — bitmap transparency for imaging tests (USAF target, scenes) (`ObjectType.Slide`)

A Slide is a color-RGB transparency loaded from a **BMP, JPG, or PNG** file — the
standard way to put a resolution target (USAF 1951) or any test scene into an NSC
system. It's a transmission mask, not a source: **place a source behind it** to
make a radiant scene, then image it onto a `DetectorRectangle`. Only two geometry
properties (probe-verified v24.1):

| Property | Meaning |
|----------|---------|
| `XFullWidth` | Width of the image in lens units (Par1) |
| `AspectRatio` | Pixel aspect ratio = height/width (Par2, usually 1.0); image height follows from width × pixel count × aspect ratio |

**The image filename is the load-bearing `Comment` field — not a typed property.**
Same trap as `BlackBoxLens` (see `pythonnet-gotchas.md` § "Load-bearing strings on
cosmetic-looking fields"): there is no `Filename` property; you put the filename
*with its extension* in `obj.Comment`, and the file must live in the **IMAFiles**
folder (`TheApplication.ImagesDir`). Overwriting `Comment` with descriptive text
breaks the image load.

```python
OT = ZOSAPI.Editors.NCE.ObjectType
sl = NCE.GetObjectAt(2)
sl.ChangeType(sl.GetObjectTypeSettings(OT.Slide))
sd = sl.get_ObjectData().__implementation__
sd.XFullWidth  = 10.0          # mm across the image
sd.AspectRatio = 1.0           # square pixels
sl.Comment = 'USAF1951.BMP'    # filename WITH extension; must be in TheApplication.ImagesDir
# Put a source behind it (e.g. a collimated SourceRectangle just upstream in -Z),
# then image onto a DetectorRectangle downstream.
err = TheSystem.UpdateStatus()
if err: raise RuntimeError(err)
```

Notes from the CHM: for a Lambertian radiant scene, back the slide with a
collimated `SourceRectangle` and give the slide a Lambertian scattering property.
**Sampling:** when imaging a slide onto a detector, use **≥ 2 detector pixels per
graphic-file pixel** (Nyquist) or the target aliases. Large images cost memory —
optimization copies the whole system, so a big slide multiplies that — and the
Shaded Model preview caps displayed pixels.

## General workflow

```python
NCE = TheSystem.NCE
NCE.InsertNewObjectAt(idx)                              # add row
obj = NCE.GetObjectAt(idx)
obj.ChangeType(obj.GetObjectTypeSettings(OT.SourceDiode))   # set type
obj.XPosition = 0.0; obj.YPosition = 0.0; obj.ZPosition = -100.0
obj.TiltAboutX = 0.0; obj.TiltAboutY = 45.0; obj.TiltAboutZ = 0.0
obj.Material = 'N-BK7'                                  # if applicable
data = obj.get_ObjectData().__implementation__
# ... set typed properties ...
```

Cast positions and tilts to `float()` if they came from numpy — pythonnet rejects `numpy.float64` and `numpy.int64` for these properties:

```python
obj.XPosition = float(pos[0])    # pos is a numpy array
obj.TiltAboutY = float(theta)
```
