"""Coherent/incoherent projector -- ZOS-API example (solis_plossl_achromat_full).

A single-file reconstruction of the projector project's headline incoherent
build, `solis_plossl_achromat_full`:

  SOLIS-455D bare die -> ACL25416U-A collimator -> ACL2520U-A focus asphere
  -> tapered glass light pipe (4x4 -> 8x8 mm, 50 mm, N-BK7 TIR homogenizer)
  -> AC508-075-A + ACT508-250-A illumination relay -> SLM plane (USAF-1951 slide)
  -> two Plossls (4x AC508-300-A) forming a 1:1 4f relay with a Fourier annulus
  -> substrate detector.

The illumination lenses are cloned from real Thorlabs vendor prescriptions
(NSC seed .zos files under examples/optics/); the Plossl imaging lenses are
pulled from the installed Thorlabs catalog. Lens back-focal-lengths measured at
455 nm are hard-coded (see BFL_455) so the geometry is deterministic.

VENDOR LENSES (Thorlabs) used -- download the .zmx/.zar from thorlabs.com and
convert to NSC seeds if you want to regenerate examples/optics/*_NSC.zos:
    ACL25416U-A  (f=16 mm asphere)   -- SOLIS die collimator   [seed]
    ACL2520U-A   (f=20 mm asphere)   -- focus die into rod      [seed]
    AC508-075-A  (f=75 mm achromat)  -- rod collimator          [seed, flipped]
    ACT508-250-A (f=250 mm achromat) -- SLM-side condenser       [seed]
    AC508-300-A  (f=300 mm achromat) -- Plossl imaging relay x4  [catalog]

Target result (reference build, traced at high ray count):
    transport efficiency ~10.5%,  CV ~64%,  ANSI uniformity ~68%.
Fewer rays here (fast demo) give the same efficiency with a noisier CV.

Requires: Windows, Zemax OpticStudio (v24.x) with the Thorlabs lens catalog and
the SCHOTT/HIKARI glass catalogs, pythonnet (`clr`), numpy, the seed files in
examples/optics/, and USAF-1951.bmp (auto-copied into the Zemax ImaFiles folder).

Run:  python coherent_incoherent_projector.py
"""

import math
import os
import shutil
import winreg

import clr  # pythonnet
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OPTICS = os.path.join(HERE, "optics")
OUT_ZOS = os.path.join(HERE, "coherent_incoherent_projector.zos")

WAVELENGTH_UM = 0.455
LED_ANALYSIS_RAYS = 1_500_000   # reference used 2e6; fewer rays inflate CV (shot noise)

# Back focal / effective focal lengths measured at 455 nm (lens_probe_cache.json).
BFL_455 = {
    "ACL25416U-A": 7.036743,
    "ACL2520U-A": 11.829024,
    "AC508-075-A": 61.558433,
    "ACT508-250-A": 241.565801,
}
EFL_455 = {"AC508-075-A": 74.803032, "ACT508-250-A": 250.189377}

SEED = {p: os.path.join(OPTICS, f"{p}_NSC.zos")
        for p in ("ACL25416U-A", "ACL2520U-A", "AC508-075-A", "ACT508-250-A")}

# Rod material: the reference build hard-codes N-BK7 (needed to reproduce the
# 10.5% result). Switch to "F_SILICA" for a fused-silica pipe (needs the MISC
# catalog; slightly different throughput because of the lower index).
ROD_MATERIAL = "N-BK7"


# --------------------------------------------------------------------------- #
# ZOS-API connection boilerplate (standalone mode).
# --------------------------------------------------------------------------- #
class PythonStandaloneApplication(object):
    class LicenseException(Exception): pass
    class ConnectionException(Exception): pass
    class InitializationException(Exception): pass
    class SystemNotPresentException(Exception): pass

    def __init__(self, path=None):
        aKey = winreg.OpenKey(winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER),
                              r"Software\Zemax", 0, winreg.KEY_READ)
        zemaxData = winreg.QueryValueEx(aKey, 'ZemaxRoot')
        NetHelper = os.path.join(os.sep, zemaxData[0],
                                 r'ZOS-API\Libraries\ZOSAPI_NetHelper.dll')
        winreg.CloseKey(aKey)
        clr.AddReference(NetHelper)
        import ZOSAPI_NetHelper
        if path is None:
            isInitialized = ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize()
        else:
            isInitialized = ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize(path)
        if not isInitialized:
            raise self.InitializationException("Unable to locate Zemax OpticStudio.")
        zdir = ZOSAPI_NetHelper.ZOSAPI_Initializer.GetZemaxDirectory()
        clr.AddReference(os.path.join(os.sep, zdir, "ZOSAPI.dll"))
        clr.AddReference(os.path.join(os.sep, zdir, "ZOSAPI_Interfaces.dll"))
        import ZOSAPI
        self.ZOSAPI = ZOSAPI
        self.TheConnection = ZOSAPI.ZOSAPI_Connection()
        if self.TheConnection is None:
            raise self.ConnectionException("Unable to initialize .NET connection.")
        self.TheApplication = self.TheConnection.CreateNewApplication()
        if self.TheApplication is None:
            raise self.InitializationException("Unable to acquire ZOSAPI application.")
        if not self.TheApplication.IsValidLicenseForAPI:
            raise self.LicenseException("License is not valid for ZOSAPI use.")
        self.TheSystem = self.TheApplication.PrimarySystem

    def close(self):
        if getattr(self, "TheApplication", None) is not None:
            self.TheApplication.CloseApplication()
            self.TheApplication = None
        self.TheConnection = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Generic NCE helpers (ported from the project's zemax/shared/nce.py).
# --------------------------------------------------------------------------- #
def insert(NCE, OT, type_enum):
    idx = NCE.NumberOfObjects + 1
    NCE.InsertNewObjectAt(idx)
    obj = NCE.GetObjectAt(idx)
    obj.ChangeType(obj.GetObjectTypeSettings(type_enum))
    return obj


def check_status(TheSystem, label):
    status = TheSystem.UpdateStatus() or ""
    if status:
        raise RuntimeError(f"[UpdateStatus after {label}] system invalid: {status!r}")


def ensure_glass_catalogs(TheSystem, required):
    sysCat = TheSystem.SystemData.MaterialCatalogs
    in_use = list(sysCat.GetCatalogsInUse())
    available = list(sysCat.GetAvailableCatalogs())
    for name in required:
        if name in in_use:
            continue
        if name in available:
            sysCat.AddCatalog(name)


# --------------------------------------------------------------------------- #
# Seed-clone: copy the lens-bearing NSC objects out of a vendor _NSC.zos into
# the live build (ported from zemax/illumination_incoherent/lib/nsc_seed.py).
# --------------------------------------------------------------------------- #
_LENS_KINDS = ("Even Asphere Lens", "Standard Lens")
_TYPED_PROPS = ("Radius1", "Conic1", "Radius2", "Conic2", "Thickness", "Edge1", "Edge2")


def _resolved_global_z(nce, idx):
    z, seen, cur = 0.0, set(), int(idx)
    while cur and cur not in seen and len(seen) < 128:
        seen.add(cur)
        o = nce.GetObjectAt(cur)
        z += float(o.ZPosition)
        try:
            cur = int(o.RefObject)
        except Exception:
            cur = 0
    return z


def _scan_nonzero_par_cells(o, OC, max_par=30):
    out = []
    for n in range(1, max_par + 1):
        try:
            cell = o.GetObjectCell(getattr(OC, f"Par{n}"))
            v = cell.DoubleValue
        except Exception:
            continue
        if v not in (None, 0, 0.0):
            out.append((f"Par{n}", v))
    return out


def insert_nsc_lens_from_seed(zos, target_system, seed_path, z_anchor, flip=False,
                              comment=""):
    """Clone lens object(s) from seed_path into target_system. Returns body extent."""
    ZOSAPI = zos.ZOSAPI
    OT = ZOSAPI.Editors.NCE.ObjectType
    OC = ZOSAPI.Editors.NCE.ObjectColumn
    seed_abs = os.path.abspath(seed_path)
    if not os.path.exists(seed_abs):
        raise FileNotFoundError(f"NSC seed not found: {seed_abs}")

    aux = zos.TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)
    try:
        if not aux.LoadFile(seed_abs, False):
            raise RuntimeError(f"LoadFile failed for seed: {seed_abs}")
        aux_nce = aux.NCE
        records, z_values = [], []
        for i in range(1, aux_nce.NumberOfObjects + 1):
            o = aux_nce.GetObjectAt(i)
            tn = (getattr(o, "TypeName", "") or "").strip()
            if tn not in _LENS_KINDS:
                continue
            z = _resolved_global_z(aux_nce, i)
            z_values.append(z)
            typed = {}
            try:
                impl = o.get_ObjectData().__implementation__
                for name in _TYPED_PROPS:
                    if hasattr(impl, name):
                        typed[name] = float(getattr(impl, name))
            except Exception:
                pass
            records.append(dict(TypeName=tn,
                                Material=(getattr(o, "Material", "") or "").strip(),
                                Z=z, typed=typed,
                                cells=_scan_nonzero_par_cells(o, OC)))
        if not records:
            raise RuntimeError(f"no lens-bearing object in seed {seed_abs}")
        body_min = min(z_values)
        body_extent = max(z_values) - body_min
        for rec in records:
            t = float(rec["typed"].get("Thickness", 0.0) or 0.0)
            body_extent = max(body_extent, (rec["Z"] - body_min) + t)
    finally:
        try:
            aux.Close(False)
        except Exception:
            pass

    tgt = target_system.NCE
    multi = len(records) > 1
    parent_idx = None
    if multi:
        parent = insert(tgt, OT, OT.NullObject)
        parent_idx = tgt.NumberOfObjects
        if flip:
            parent.ZPosition = float(z_anchor + body_extent)
            parent.TiltAboutY = 180.0
        else:
            parent.ZPosition = float(z_anchor)
        parent.Comment = comment or "[seed clone]"

    for rec in records:
        obj = insert(tgt, OT, getattr(OT, rec["TypeName"].replace(" ", "")))
        rel_z = rec["Z"] - body_min
        if multi:
            obj.RefObject = int(parent_idx)
            obj.ZPosition = float(rel_z)
        elif flip:
            obj.ZPosition = float(z_anchor + (body_extent - rel_z))
            obj.TiltAboutY = 180.0
        else:
            obj.ZPosition = float(z_anchor + rel_z)
        if rec["Material"]:
            obj.Material = rec["Material"]
        try:
            impl = obj.get_ObjectData().__implementation__
            for name, val in rec["typed"].items():
                if hasattr(impl, name):
                    setattr(impl, name, float(val))
        except Exception:
            pass
        for par_name, val in rec["cells"]:
            try:
                obj.GetObjectCell(getattr(OC, par_name)).DoubleValue = float(val)
            except Exception:
                pass
    check_status(target_system, f"seed clone {os.path.basename(seed_path)}")
    return body_extent


# --------------------------------------------------------------------------- #
# Catalog lens (Plossl doublets) -- OpenLensCatalogs + optional flip.
# --------------------------------------------------------------------------- #
def insert_catalog_lens(TheSystem, part, focal_length, z_anchor, body_extent, flip,
                        vendor="THORLABS", efl_tol=5.0):
    NCE = TheSystem.NCE
    z_insert = (z_anchor + body_extent) if flip else z_anchor
    n_before = NCE.NumberOfObjects
    cat = TheSystem.Tools.OpenLensCatalogs()
    chosen = None
    try:
        cat.SelectedVendor = vendor
        cat.UseEFL = True
        cat.MinEFL = float(focal_length - efl_tol)
        cat.MaxEFL = float(focal_length + efl_tol)
        cat.RunAndWaitForCompletion()
        for i in range(cat.MatchingLenses):
            lens = cat.GetResult(i)
            if lens.LensName == part:
                chosen = lens
                break
        if chosen is None or not chosen.InsertLensNonSeq():
            raise RuntimeError(f"catalog insert failed for {part} "
                               f"(is the {vendor} catalog installed?)")
    finally:
        try:
            cat.Close()
        except Exception:
            pass
    parent = NCE.GetObjectAt(n_before + 1)
    parent.ZPosition = float(z_insert)
    if flip:
        parent.TiltAboutY = 180.0
    parent.Comment = f"{part} ({'flipped' if flip else 'default'})"


AC508_300_EXTENT = 8.0  # AC508-300-A glass body extent (mm), probed


def add_plossl(TheSystem, OT, z_front, part, f, body_extent, intra_gap_mm, prefix):
    """One Plossl: doublet reversed + gap + doublet default. Returns z_back."""
    insert_catalog_lens(TheSystem, part, f, z_front, body_extent, True)
    check_status(TheSystem, f"{prefix} L1")
    z_l1_back = z_front + body_extent
    z_l2_front = z_l1_back + intra_gap_mm
    insert_catalog_lens(TheSystem, part, f, z_l2_front, body_extent, False)
    check_status(TheSystem, f"{prefix} L2")
    return z_l2_front + body_extent


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def build_projector(zos):
    ZOSAPI = zos.ZOSAPI
    TheSystem = zos.TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)
    zos.TheSystem = TheSystem
    TheSystem.SystemData.Wavelengths.GetWavelength(1).Wavelength = WAVELENGTH_UM
    ensure_glass_catalogs(TheSystem, ("SCHOTT", "HIKARI", "MISC", "INFRARED"))

    nsd = TheSystem.SystemData.NonSequentialData
    nsd.MaximumNestedTouchingObjects = 8
    nsd.MaximumIntersectionsPerRay = 4000

    NCE = TheSystem.NCE
    OT = ZOSAPI.Editors.NCE.ObjectType
    OC = ZOSAPI.Editors.NCE.ObjectColumn

    # --- SOLIS die (object #1) -> collimator -> focus asphere --------------- #
    src = NCE.GetObjectAt(1)
    src.ChangeType(src.GetObjectTypeSettings(OT.SourceRectangle))
    src.ZPosition = 0.0
    sd = src.get_ObjectData().__implementation__
    sd.XHalfWidth = sd.YHalfWidth = 1.5      # 3x3 mm die
    sd.CosineExponent = 1.0                   # Lambertian
    sd.Power = 1.0
    sd.NumberOfLayoutRays = 100
    sd.NumberOfAnalysisRays = LED_ANALYSIS_RAYS
    src.SourcesData.RandomPolarization = True
    check_status(TheSystem, "SOLIS die")

    z_col = 0.0 + BFL_455["ACL25416U-A"]      # die at collector short-WD conjugate
    col_ext = insert_nsc_lens_from_seed(zos, TheSystem, SEED["ACL25416U-A"],
                                        z_col, flip=True, comment="ACL25416U-A collimator")
    z_col_back = z_col + col_ext
    z_foc = z_col_back + 10.0                  # collimated gap
    foc_ext = insert_nsc_lens_from_seed(zos, TheSystem, SEED["ACL2520U-A"],
                                        z_foc, flip=False, comment="ACL2520U-A focus")
    z_foc_back = z_foc + foc_ext
    z_rod_in = z_foc_back + BFL_455["ACL2520U-A"]

    # --- Tapered glass light pipe (holder baffle + RectangularVolume) ------- #
    holder = insert(NCE, OT, OT.Annulus)
    holder.ZPosition = float(z_rod_in - 0.6)
    holder.Material = "ABSORB"
    holder.GetObjectCell(OC.Par1).DoubleValue = 25.0    # outer half
    holder.GetObjectCell(OC.Par2).DoubleValue = 25.0
    holder.GetObjectCell(OC.Par3).DoubleValue = 2.4     # inner half (rod clearance)
    holder.GetObjectCell(OC.Par4).DoubleValue = 2.4
    check_status(TheSystem, "rod holder")

    rod = insert(NCE, OT, OT.RectangularVolume)
    rod.ZPosition = float(z_rod_in)
    rod.Material = ROD_MATERIAL
    rod.GetObjectCell(OC.Par1).DoubleValue = 2.0        # X in half
    rod.GetObjectCell(OC.Par2).DoubleValue = 2.0        # Y in half
    rod.GetObjectCell(OC.Par3).DoubleValue = 50.0       # length
    rod.GetObjectCell(OC.Par4).DoubleValue = 4.0        # X out half
    rod.GetObjectCell(OC.Par5).DoubleValue = 4.0        # Y out half
    for n in range(6, 10):
        rod.GetObjectCell(getattr(OC, f"Par{n}")).DoubleValue = 0.0
    check_status(TheSystem, "tapered light pipe")
    z_rod_out = z_rod_in + 50.0

    # --- Rod -> SLM relay: AC508-075-A (flipped) + ACT508-250-A ------------- #
    z_l1 = z_rod_out + BFL_455["AC508-075-A"]
    ext1 = insert_nsc_lens_from_seed(zos, TheSystem, SEED["AC508-075-A"],
                                     z_l1, flip=True, comment="AC508-075-A rod collimator")
    z_l1_back = z_l1 + ext1
    z_l2 = z_l1_back + 75.0                    # L1->L2 compact gap
    ext2 = insert_nsc_lens_from_seed(zos, TheSystem, SEED["ACT508-250-A"],
                                     z_l2, flip=False, comment="ACT508-250-A condenser")
    z_l2_back = z_l2 + ext2
    z_slm = z_l2_back + BFL_455["ACT508-250-A"]

    # --- SLM aperture (StandardSurface) + USAF-1951 slide ------------------ #
    slm = insert(NCE, OT, OT.StandardSurface)
    slm.ZPosition = float(z_slm)
    sm = slm.get_ObjectData().__implementation__
    sm.Radius = 0.0
    sm.MaxAperture = math.hypot(26.6, 20.0) / 2.0
    slm.Comment = "LC2002 SLM aperture"

    slide = insert(NCE, OT, OT.Slide)
    slide.ZPosition = float(z_slm)
    slide.GetObjectCell(OC.Par1).DoubleValue = 26.6    # full width
    slide.GetObjectCell(OC.Par2).DoubleValue = 1.0     # aspect
    slide.Comment = "USAF-1951.bmp"                     # file read from ImaFiles dir
    check_status(TheSystem, "SLM + slide")

    # --- Plossl 4f imaging relay (2 Plossls of AC508-300-A) + Fourier stop -- #
    z_p1_back = add_plossl(TheSystem, OT, z_slm + 143.7, "AC508-300-A", 300.0,
                           AC508_300_EXTENT, 5.0, "Plossl A")
    z_stop = z_p1_back + 143.7
    stop = insert(NCE, OT, OT.Annulus)
    stop.ZPosition = float(z_stop)
    stop.Material = "ABSORB"
    stop.GetObjectCell(OC.Par1).DoubleValue = 25.0     # outer half (Ø50)
    stop.GetObjectCell(OC.Par2).DoubleValue = 25.0
    stop.GetObjectCell(OC.Par3).DoubleValue = 12.0     # inner half (Ø24)
    stop.GetObjectCell(OC.Par4).DoubleValue = 12.0
    stop.Comment = "Fourier stop"
    check_status(TheSystem, "Fourier stop")

    z_p2_back = add_plossl(TheSystem, OT, z_stop + 143.7, "AC508-300-A", 300.0,
                           AC508_300_EXTENT, 5.0, "Plossl B")
    z_substrate = z_p2_back + 143.7

    det = insert(NCE, OT, OT.DetectorRectangle)
    det.ZPosition = float(z_substrate)
    det.GetObjectCell(OC.Par1).DoubleValue = 12.5
    det.GetObjectCell(OC.Par2).DoubleValue = 12.5
    det.GetObjectCell(OC.Par3).IntegerValue = 500
    det.GetObjectCell(OC.Par4).IntegerValue = 500
    dd = det.get_ObjectData().__implementation__
    dd.XHalfWidth = dd.YHalfWidth = 12.5
    dd.NumberXPixels = dd.NumberYPixels = 500
    det.Comment = "Substrate detector"
    det_idx = NCE.NumberOfObjects
    check_status(TheSystem, "substrate detector")

    print(f"SLM plane   @ Z={z_slm:.2f} mm")
    print(f"Substrate   @ Z={z_substrate:.2f} mm  (throw {z_substrate - z_slm:.1f} mm)")
    return TheSystem, det_idx


def ensure_slide_image(zos):
    """Copy USAF-1951.bmp into the Zemax ImaFiles folder if it isn't there."""
    try:
        images_dir = zos.TheApplication.ImagesDir
    except Exception:
        return
    dst = os.path.join(images_dir, "USAF-1951.bmp")
    src = os.path.join(OPTICS, "USAF-1951.bmp")
    if os.path.exists(src) and not os.path.exists(dst):
        try:
            shutil.copy(src, dst)
            print(f"copied USAF-1951.bmp -> {images_dir}")
        except Exception as exc:
            print(f"[warn] could not copy slide into ImaFiles: {exc}")


def main():
    zos = PythonStandaloneApplication()
    try:
        ensure_slide_image(zos)
        TheSystem, det_idx = build_projector(zos)
        TheSystem.SaveAs(OUT_ZOS)

        rt = TheSystem.Tools.OpenNSCRayTrace()
        rt.SplitNSCRays = False
        rt.ScatterNSCRays = False
        rt.UsePolarization = True
        rt.IgnoreErrors = True
        rt.ClearDetectors(0)
        rt.RunAndWaitForCompletion()
        rt.Close()

        raw = TheSystem.NCE.GetAllDetectorDataSafe(det_idx, 0)
        arr = np.array(list(raw)).reshape(500, 500)
        TheSystem.Save()

        total = float(arr.sum())
        lit = arr[arr > 0]
        cv = float(100.0 * lit.std() / lit.mean()) if lit.size else float("nan")
        print(f"\nLED power            : 1.000 W")
        print(f"Substrate flux       : {total:.4e} W")
        print(f"Transport efficiency : {100 * total:.2f} %   (target ~10.5%)")
        print(f"Uniformity CV        : {cv:.1f} %            (target ~64%)")
        print(f"saved: {OUT_ZOS}")
    finally:
        zos.close()


if __name__ == "__main__":
    main()
