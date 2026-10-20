"""MicroLED datacenter link -- multicore-fiber ZOS-API example (MOSAIC repro).

Reproduces two builds from the wide-and-slow microLED interconnect project:

  * "lambertian" -- bare 60-deg Lambertian microLEDs launched across a 5 um air
    gap into a hex-packed multicore imaging fiber with extramural absorption (EMA).
  * "reallens"   -- the same fiber, but each channel is launched through the real,
    manufacturable two-element TIR micro-collimator (a central even-asphere lens +
    an annular-aspheric TIR collar) from a locked prescription.

Each microLED is activated one at a time to fill a 9x9 channel-coupling matrix
H[j, i] (flux binned into detector cell j from emitter i). From H we read
per-channel coupling efficiency and crosstalk (dB). The comparison shows how much
of the idealized micro-optic coupling gain a pitch-limited real lens delivers --
the etendue reality check that motivates a verified simulator.

The script builds BOTH systems and saves TWO .zos files:
    microled_link_lambertian.zos
    microled_link_reallens.zos

Target results (from the reference project, 20k rays/source):
    lambertian : coupling_mean ~0.124, worst crosstalk ~-15.4 dB
    reallens   : coupling_mean ~0.261, worst crosstalk ~-8.2 dB

Requires: Windows, Zemax OpticStudio (v24.x, needs the MISC glass catalog for
F_SILICA), pythonnet (`clr`), numpy, and the TIR-lens prescription file at
examples/optics/tir_collimator_prescription.json (copied from the project).

Run:  python microled_link.py
"""

import json
import math
import os
import winreg

import clr  # pythonnet
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PRESCRIPTION = os.path.join(HERE, "optics", "tir_collimator_prescription.json")

# --------------------------------------------------------------------------- #
# Effective config (mvp5_multicore_50um_{lambertian,reallens}.yaml + defaults).
# Lengths are micrometres unless the name says _mm.
# --------------------------------------------------------------------------- #
WAVELENGTH_NM = 450.0
EMITTER_ROWS = 3
EMITTER_COLS = 3
EMITTER_PITCH_UM = 50.0        # channel pitch
Z_SEPARATION_MM = 1.0          # fiber length (entrance z=0 -> exit z=1.0 mm)

CORE_PITCH_UM = 15.0
CORE_DIAMETER_UM = 11.0
CLAD_RING_THICKNESS_UM = 1.5
CORE_MATERIAL = "N-BK7"        # SCHOTT (default catalog)
CLAD_MATERIAL = "F_SILICA"     # needs the MISC catalog
MATRIX_MATERIAL = "ABSORB"     # built-in NSC keyword -> extramural absorption
BUNDLE_MARGIN_UM = 25.0        # matrix extends this far past the channel bbox

DET_PIXELS_PER_CHANNEL = 6     # -> 18x18 total pixels for a 3x3 grid
LAUNCH_GAP_UM = 5.0            # emitter-to-fiber gap (lambertian only)

RAYS_PER_SOURCE = 20_000
TOTAL_POWER_W = 1.0

# The two variants: only the launch differs.
CONFIGS = {
    "lambertian": {
        "emitter_size_um": 40.0,   # bare 40 um mesa
        "half_angle_deg": 60.0,    # -> cosine exponent m = 1 (Lambertian)
        "collimator": False,
    },
    "reallens": {
        "emitter_size_um": 10.0,   # 10 um mesa feeding the lens
        "half_angle_deg": 60.0,
        "collimator": True,
    },
}


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
        if self.TheSystem is None:
            raise self.SystemNotPresentException("Unable to acquire Primary system.")

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
# Geometry helpers (ported verbatim from the project's src/geometry.py so the
# channel/detector indexing matches exactly).
# --------------------------------------------------------------------------- #
def cosine_power_m(half_angle_deg):
    c = math.cos(math.radians(half_angle_deg))
    return math.log(0.5) / math.log(c)


def grid_positions_mm(n_rows, n_cols, pitch_um):
    """Centred (x,y) mm grid, row-major, row 0 = +Y (top)."""
    p = pitch_um * 1e-3
    xs = (np.arange(n_cols) - (n_cols - 1) / 2.0) * p
    ys = ((n_rows - 1) / 2.0 - np.arange(n_rows)) * p
    pts = np.empty((n_rows * n_cols, 2))
    for r in range(n_rows):
        for c in range(n_cols):
            pts[r * n_cols + c] = (xs[c], ys[r])
    return pts


def hex_lattice_positions_mm(half_x_mm, half_y_mm, pitch_um):
    """Hex-packed lattice points (mm) inside a centred rectangle."""
    p = pitch_um * 1e-3
    dy = p * math.sqrt(3.0) / 2.0
    tol = 1e-12
    n_rows_half = int(math.floor(half_y_mm / dy)) if dy > 0 else 0
    n_cols_half = int(math.ceil(half_x_mm / p)) + 2
    pts = []
    for jr in range(-n_rows_half, n_rows_half + 1):
        y = jr * dy
        x_off = (p / 2.0) if (abs(jr) % 2 == 1) else 0.0
        for i in range(-n_cols_half, n_cols_half + 1):
            x = x_off + i * p
            if abs(x) <= half_x_mm + tol:
                pts.append((x, y))
    return np.asarray(pts)


def load_prescription(path):
    """Parse the TIR-collimator JSON into {lens, collar, material_name}."""
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    lens = {k: float(v) for k, v in d["central_lens_EvenAsphereLens_mm"].items()}
    collar = {k: float(v) for k, v in d["outer_collar_AnnularAsphericLens_mm"].items()}
    return {"lens": lens, "collar": collar,
            "material_name": d["material"]["index_model_glass"]}


# NCE cell columns for the aspheric coefficients (not exposed as typed props).
LENS_COL_C2R2, LENS_COL_C2R4 = 27, 28
COLLAR_COL_R2, COLLAR_COL_R4 = 19, 20


class Build(object):
    """Holds object indices + detector layout for one built system."""
    def __init__(self):
        self.emitter_objs = []
        self.array_det_idx = None
        self.array_npx = self.array_npy = None
        self.array_kx = self.array_ky = None
        self.n_rows = EMITTER_ROWS
        self.n_cols = EMITTER_COLS
        self.n_chan = EMITTER_ROWS * EMITTER_COLS


def build_multicore(zos, cfg):
    """Build one multicore-fiber system. Returns (TheSystem, Build)."""
    ZOSAPI = zos.ZOSAPI
    TheSystem = zos.TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)
    zos.TheSystem = TheSystem
    TheSystem.SystemData.Wavelengths.GetWavelength(1).Wavelength = WAVELENGTH_NM / 1000.0

    # F_SILICA lives in the MISC catalog; N-BK7 is in the default SCHOTT catalog.
    try:
        TheSystem.SystemData.MaterialCatalogs.AddCatalog("MISC")
    except Exception as exc:
        print(f"[warn] AddCatalog('MISC') failed: {exc}")

    NCE = TheSystem.NCE
    OT = ZOSAPI.Editors.NCE.ObjectType
    OC = ZOSAPI.Editors.NCE.ObjectColumn
    b = Build()

    def _new(idx, obj_type):
        while NCE.NumberOfObjects < idx:
            NCE.InsertNewObjectAt(NCE.NumberOfObjects + 1)
        obj = NCE.GetObjectAt(idx)
        obj.ChangeType(obj.GetObjectTypeSettings(obj_type))
        return obj

    def _impl(obj):
        return obj.get_ObjectData().__implementation__

    z_sep = Z_SEPARATION_MM
    core_r = CORE_DIAMETER_UM * 1e-3 / 2.0
    ring_r = core_r + CLAD_RING_THICKNESS_UM * 1e-3
    bbox_half = (EMITTER_COLS * EMITTER_PITCH_UM * 1e-3) / 2.0
    matrix_half = bbox_half + BUNDLE_MARGIN_UM * 1e-3

    channel_pts = grid_positions_mm(EMITTER_ROWS, EMITTER_COLS, EMITTER_PITCH_UM)
    core_pts = hex_lattice_positions_mm(bbox_half, bbox_half, CORE_PITCH_UM)
    n_sites = core_pts.shape[0]

    # --- Object 1: absorbing matrix (EMA), parent of every core nest -------- #
    matrix = _new(1, OT.RectangularVolume)
    matrix.XPosition = matrix.YPosition = matrix.ZPosition = 0.0
    md = _impl(matrix)
    md.X1HalfWidth = md.Y1HalfWidth = matrix_half
    md.X2HalfWidth = md.Y2HalfWidth = matrix_half
    md.ZLength = z_sep
    matrix.Material = MATRIX_MATERIAL

    # --- Objects 2..: per-site clad ring (InsideOf matrix) + core (InsideOf ring)
    for k in range(n_sites):
        x, y = float(core_pts[k, 0]), float(core_pts[k, 1])
        ring_idx, core_idx = 2 + 2 * k, 3 + 2 * k
        ring = _new(ring_idx, OT.CylinderVolume)
        ring.XPosition, ring.YPosition, ring.ZPosition = x, y, 0.0
        rd = _impl(ring)
        rd.FrontR = rd.BackR = ring_r
        rd.ZLength = z_sep
        ring.Material = CLAD_MATERIAL
        ring.InsideOf = 1
        core = _new(core_idx, OT.CylinderVolume)
        core.XPosition, core.YPosition, core.ZPosition = x, y, 0.0
        cd = _impl(core)
        cd.FrontR = cd.BackR = core_r
        cd.ZLength = z_sep
        core.Material = CORE_MATERIAL
        core.InsideOf = ring_idx

    base = 1 + 2 * n_sites  # last core object number

    # --- Launch: emitter Z depends on whether the TIR collimator is present - #
    presc = None
    if cfg["collimator"]:
        presc = load_prescription(PRESCRIPTION)
        src_half = cfg["emitter_size_um"] * 1e-3 / 2.0
        src_cos = 1.0
        collimator_zs = -(presc["collar"]["Thickness"] + LAUNCH_GAP_UM * 1e-3)
        emitter_z = collimator_zs
    else:
        src_half = cfg["emitter_size_um"] * 1e-3 / 2.0
        src_cos = cosine_power_m(cfg["half_angle_deg"])
        emitter_z = -(LAUNCH_GAP_UM * 1e-3)

    # --- Emitters: one SourceEllipse per channel, in air before the face ---- #
    for c in range(b.n_chan):
        idx = base + c + 1
        obj = _new(idx, OT.SourceEllipse)
        obj.XPosition = float(channel_pts[c, 0])
        obj.YPosition = float(channel_pts[c, 1])
        obj.ZPosition = float(emitter_z)
        d = _impl(obj)
        d.XHalfWidth = d.YHalfWidth = src_half
        d.CosineExponent = float(src_cos)
        d.SourceDistance = 0.0
        d.Power = TOTAL_POWER_W
        d.NumberOfAnalysisRays = RAYS_PER_SOURCE
        d.NumberOfLayoutRays = 20
        d.WaveNumber = 1
        b.emitter_objs.append(idx)

    # --- Single pixelated array detector spanning the channel bbox ---------- #
    kx = ky = DET_PIXELS_PER_CHANNEL
    npx, npy = kx * b.n_cols, ky * b.n_rows
    det_idx = base + b.n_chan + 1
    det = _new(det_idx, OT.DetectorRectangle)
    det.XPosition = det.YPosition = 0.0
    det.ZPosition = z_sep + 1.0e-3
    det.GetObjectCell(OC.Par1).DoubleValue = bbox_half
    det.GetObjectCell(OC.Par2).DoubleValue = bbox_half
    det.GetObjectCell(OC.Par3).IntegerValue = npx
    det.GetObjectCell(OC.Par4).IntegerValue = npy
    dd = _impl(det)
    dd.XHalfWidth = dd.YHalfWidth = bbox_half
    dd.NumberXPixels, dd.NumberYPixels = npx, npy
    b.array_det_idx = det_idx
    b.array_npx, b.array_npy, b.array_kx, b.array_ky = npx, npy, kx, ky

    # --- TIR collimator (reallens only): lens + collar per channel ---------- #
    if presc is not None:
        lens_p, collar_p = presc["lens"], presc["collar"]
        glass = presc["material_name"]
        zs = -(collar_p["Thickness"] + LAUNCH_GAP_UM * 1e-3)
        nxt = NCE.NumberOfObjects
        for c in range(b.n_chan):
            cx, cy = float(channel_pts[c, 0]), float(channel_pts[c, 1])
            lens_idx = nxt + 1
            lens = _new(lens_idx, OT.EvenAsphereLens)
            lens.XPosition, lens.YPosition = cx, cy
            lens.ZPosition = zs + lens_p["Z"]
            ld = _impl(lens)
            ld.Radius1 = lens_p["Radius1"]; ld.Radius2 = lens_p["Radius2"]
            ld.Conic2 = lens_p["Conic2"]
            ld.Clear1 = lens_p["Clear1"]; ld.Clear2 = lens_p["Clear2"]
            ld.Edge1 = lens_p["Edge1"]; ld.Edge2 = lens_p["Edge2"]
            ld.Thickness = lens_p["Thickness"]
            lens.Material = glass
            lens.GetCellAt(LENS_COL_C2R2).DoubleValue = lens_p["Coeff2OnRPower2"]
            lens.GetCellAt(LENS_COL_C2R4).DoubleValue = lens_p["Coeff2OnRPower4"]

            collar_idx = lens_idx + 1
            collar = _new(collar_idx, OT.AnnularAsphericLens)
            collar.XPosition, collar.YPosition = cx, cy
            collar.ZPosition = zs + collar_p["Z"]
            cd2 = _impl(collar)
            cd2.FrontRadius = collar_p["FrontRadius"]; cd2.RearRadius = collar_p["RearRadius"]
            cd2.MinFrontAperture = collar_p["MinFrontAperture"]
            cd2.MaxFrontAperture = collar_p["MaxFrontAperture"]
            cd2.MinBackAperture = collar_p["MinBackAperture"]
            cd2.MaxBackAperture = collar_p["MaxBackAperture"]
            cd2.Thickness = collar_p["Thickness"]; cd2.ThkAperture = collar_p["ThkAperture"]
            cd2.Edge1 = collar_p["Edge1"]; cd2.Edge2 = collar_p["Edge2"]
            collar.Material = glass
            collar.GetCellAt(COLLAR_COL_R2).DoubleValue = collar_p["RearRPower2"]
            collar.GetCellAt(COLLAR_COL_R4).DoubleValue = collar_p["RearRPower4"]
            nxt = collar_idx

    status = TheSystem.UpdateStatus()
    if status:
        raise RuntimeError(f"System invalid after build: {status}")
    return TheSystem, b


def trace_channel_matrix(TheSystem, b, split_rays=True):
    """Activate one emitter at a time; bin the array detector into H[j, i]."""
    NCE = TheSystem.NCE
    H = np.zeros((b.n_chan, len(b.emitter_objs)))

    def _impl(idx):
        return NCE.GetObjectAt(idx).get_ObjectData().__implementation__

    for i, e_on in enumerate(b.emitter_objs):
        for e in b.emitter_objs:
            _impl(e).NumberOfAnalysisRays = RAYS_PER_SOURCE if e == e_on else 0
        rt = TheSystem.Tools.OpenNSCRayTrace()
        try:
            rt.SplitNSCRays = split_rays
            rt.ScatterNSCRays = False
            rt.UsePolarization = False
            rt.IgnoreErrors = True
            rt.ClearDetectors(0)
            rt.RunAndWaitForCompletion()
        finally:
            rt.Close()
        flat = list(NCE.GetAllDetectorDataSafe(b.array_det_idx, 0))
        grid = np.asarray(flat).reshape(b.array_npy, b.array_npx)
        blocks = grid.reshape(b.n_rows, b.array_ky, b.n_cols, b.array_kx).sum(axis=(1, 3))
        blocks = blocks[::-1, :]  # detector bottom-up -> channel top-down
        H[:, i] = blocks.reshape(b.n_chan)
        print(f"  emitter {i + 1}/{len(b.emitter_objs)}: signal={H[i, i]:.4e}")

    for e in b.emitter_objs:  # restore ray budgets
        _impl(e).NumberOfAnalysisRays = RAYS_PER_SOURCE
    return H


def report(name, H):
    signal = np.diag(H)
    off = H.copy()
    np.fill_diagonal(off, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(signal > 0, off.sum(axis=1) / signal, np.inf)
    finite = ratio[np.isfinite(ratio)]
    xtalk_db_max = 10.0 * math.log10(finite.max()) if finite.size else float("nan")
    print(f"\n[{name}] coupling mean/min/max = "
          f"{signal.mean():.4f} / {signal.min():.4f} / {signal.max():.4f}")
    print(f"[{name}] worst crosstalk = {xtalk_db_max:.2f} dB "
          f"(ratio {finite.max():.4f})")


def main():
    for name, cfg in CONFIGS.items():
        print(f"\n=== building '{name}' ({'TIR collimator' if cfg['collimator'] else 'bare Lambertian'}) ===")
        zos = PythonStandaloneApplication()
        try:
            TheSystem, b = build_multicore(zos, cfg)
            out = os.path.join(HERE, f"microled_link_{name}.zos")
            TheSystem.SaveAs(out)
            H = trace_channel_matrix(TheSystem, b)
            TheSystem.Save()
            report(name, H)
            print(f"[{name}] saved: {out}")
        finally:
            zos.close()


if __name__ == "__main__":
    main()
