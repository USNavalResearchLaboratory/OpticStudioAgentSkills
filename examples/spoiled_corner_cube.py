"""Spoiled corner-cube retroreflector -- minimal ZOS-API example.

A perfect corner cube returns light to a near-point at the source. Many
applications instead want a *controlled, broadened* return. This script builds
the classic "dihedral-angle offset" spoiling mechanism: three mutually
perpendicular mirrors whose dihedral angles are perturbed by a small offset
delta, which splits the single return spot into the characteristic six-lobe
pattern with an exact central null.

It is a deliberately simplified, single-file distillation of the corner-cube
project. It builds a non-sequential (NSC) system, ray-traces with polarization,
reads the return-plane detector, prints the central-null / peak diagnostic, and
saves a `.zos` you can open in OpticStudio to inspect the geometry and detector.

Requires: Windows, Zemax OpticStudio (v24.x) with a ZOS-API license, pythonnet
(`clr`), numpy. Matplotlib is optional (a heatmap is saved if it is installed).

Run:  python spoiled_corner_cube.py
"""

import math
import os
import winreg
from itertools import islice

import clr  # pythonnet
import numpy as np

# --------------------------------------------------------------------------- #
# Design constants (all lengths in millimetres, all angles in degrees).
# These are illustrative -- tune them to explore the spoiling behaviour.
# --------------------------------------------------------------------------- #
WAVELENGTH_UM = 0.633          # HeNe
CC_WIDTH = 25.4                # corner-cube face size (mm)
CC_DISTANCE = 300.0            # source-to-corner-cube distance L (mm)
DIHEDRAL_OFFSET_DEG = 0.10     # delta: the dihedral perturbation that spoils

# Corner-cube whole-body orientation (GUI-verified so the trihedron faces the
# incoming +Z beam and reflects it back toward -Z).
CC_TILT_X = 205.0
CC_TILT_Y = -45.0
CC_TILT_Z = 0.0

BEAM_HALF_WIDTH = 5.0          # source half-width (mm)
BEAM_DIVERGENCE_DEG = 0.05     # source half-angle divergence (deg)
SOURCE_POWER = 1.0             # W
ANALYSIS_RAYS = 200_000        # fast demo; raise to ~1e6 for a clean pattern

DET_HALF_WIDTH = 6.0           # return-plane detector half-width (mm)
DET_PIXELS = 200
DET_Z = -5.0                   # detector just behind the source plane (mm)

OUT_ZOS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "spoiled_corner_cube.zos")


# --------------------------------------------------------------------------- #
# ZOS-API connection boilerplate (standalone mode). See the zemax-zos-api skill
# reference `boilerplate.md` -- use this exact class, do not invent alternatives.
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

    def reshape(self, data, x, y, transpose=False):
        """Convert a System.Double[,] to a 2D Python list."""
        if type(data) is not list:
            data = list(data)
        var_lst = [y] * x
        it = iter(data)
        res = [list(islice(it, i)) for i in var_lst]
        return list(map(list, zip(*res))) if transpose else res


def build_spoiled_corner_cube(zos):
    """Build the NSC scene and return (TheSystem, detector_object_id)."""
    ZOSAPI = zos.ZOSAPI
    TheSystem = zos.TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)
    zos.TheSystem = TheSystem

    TheSystem.SystemData.Wavelengths.GetWavelength(1).Wavelength = WAVELENGTH_UM
    NCE = TheSystem.NCE
    OT = ZOSAPI.Editors.NCE.ObjectType

    import System  # for System.Double() wrapping (pythonnet 3.x)

    # --- Object 1: source (SourceDiode), emits +Z from the origin ---------- #
    src = NCE.GetObjectAt(1)
    src.ChangeType(src.GetObjectTypeSettings(OT.SourceDiode))
    sdata = src.get_ObjectData().__implementation__
    sdata.XMinusWidth = sdata.YMinusWidth = BEAM_HALF_WIDTH
    sdata.XMinusDivergence = sdata.YMinusDivergence = BEAM_DIVERGENCE_DEG
    sdata.Power = SOURCE_POWER
    sdata.NumberOfLayoutRays = 25
    sdata.NumberOfAnalysisRays = ANALYSIS_RAYS
    src.ZPosition = 0.0
    # Force a defined (linear) polarization so mirror-reflection losses register.
    sd = src.SourcesData
    sd.RandomPolarization = False
    sd.set_Jx(System.Double(1.0)); sd.set_Jy(System.Double(1.0))
    sd.set_XPhase(System.Double(0.0)); sd.set_YPhase(System.Double(0.0))

    # --- Object 2: NullObject parent carrying the whole-cube orientation --- #
    NCE.InsertNewObjectAt(2)
    parent = NCE.GetObjectAt(2)
    parent.ChangeType(parent.GetObjectTypeSettings(OT.NullObject))
    parent.ZPosition = CC_DISTANCE
    parent.TiltAboutX = CC_TILT_X
    parent.TiltAboutY = CC_TILT_Y
    parent.TiltAboutZ = CC_TILT_Z
    parent_id = 2

    # --- Objects 3-5: three StandardSurface mirrors forming the trihedron -- #
    # The dihedral offset delta is applied on TWO tilt axes per mirror. This
    # asymmetric two-axis convention (empirically GUI-verified) is what produces
    # the six-lobe return; a single-axis perturbation collapses it to two lobes.
    delta = DIHEDRAL_OFFSET_DEG
    half = CC_WIDTH / 2.0
    aperture = CC_WIDTH / math.sqrt(2.0)  # circumscribed circle of the WxW face

    def _make_mirror(row):
        NCE.InsertNewObjectAt(row)
        m = NCE.GetObjectAt(row)
        m.ChangeType(m.GetObjectTypeSettings(OT.StandardSurface))
        m.RefObject = parent_id
        m.Material = "MIRROR"
        md = m.get_ObjectData().__implementation__
        md.Conic = 0.0
        md.Radius = 0.0            # flat; set nonzero here to model "bowed" faces
        md.MaxAperture = aperture
        return m

    m1 = _make_mirror(3)          # local XY plane, normal +Z
    m1.XPosition = half; m1.YPosition = half; m1.ZPosition = 0.0
    m1.TiltAboutX = -delta; m1.TiltAboutY = delta

    m2 = _make_mirror(4)          # local XZ plane, normal +Y after base tilt
    m2.XPosition = half; m2.YPosition = 0.0; m2.ZPosition = half
    m2.TiltAboutX = -90.0; m2.TiltAboutY = delta; m2.TiltAboutZ = -delta

    m3 = _make_mirror(5)          # local YZ plane, normal +X after base tilt
    m3.XPosition = 0.0; m3.YPosition = half; m3.ZPosition = half
    m3.TiltAboutX = delta; m3.TiltAboutY = 90.0; m3.TiltAboutZ = delta

    # --- Object 6: return-plane detector, co-located behind the source ----- #
    NCE.InsertNewObjectAt(6)
    det = NCE.GetObjectAt(6)
    det.ChangeType(det.GetObjectTypeSettings(OT.DetectorRectangle))
    dd = det.get_ObjectData().__implementation__
    dd.XHalfWidth = dd.YHalfWidth = DET_HALF_WIDTH
    dd.NumberXPixels = dd.NumberYPixels = DET_PIXELS
    det.ZPosition = DET_Z
    det_id = 6

    status = TheSystem.UpdateStatus()
    if status:
        raise RuntimeError(f"System invalid after build: {status}")
    return TheSystem, det_id


def main():
    zos = PythonStandaloneApplication()
    try:
        ZOSAPI = zos.ZOSAPI
        TheSystem, det_id = build_spoiled_corner_cube(zos)

        # Save geometry first so it is inspectable even if the trace fails.
        TheSystem.SaveAs(OUT_ZOS)

        rt = TheSystem.Tools.OpenNSCRayTrace()
        rt.SplitNSCRays = False
        rt.ScatterNSCRays = False
        rt.UsePolarization = True     # capture mirror reflection losses
        rt.IgnoreErrors = True
        rt.ClearDetectors(0)
        rt.RunAndWaitForCompletion()
        rt.Close()

        # Full per-pixel grid; flip vertically to match the Zemax display.
        raw = TheSystem.NCE.GetAllDetectorDataSafe(det_id, 0)
        arr = np.flipud(np.array(list(raw)).reshape(DET_PIXELS, DET_PIXELS))

        c = DET_PIXELS // 2
        total = float(arr.sum())
        peak = float(arr.max())
        center = float(arr[c, c])
        print(f"Return-plane detector ({DET_PIXELS}x{DET_PIXELS}, "
              f"+/-{DET_HALF_WIDTH} mm):")
        print(f"  total flux : {total:.4e} W")
        print(f"  peak pixel : {peak:.4e} W")
        print(f"  center px  : {center:.4e} W  (expect ~0 -> central null)")
        print(f"  saved: {OUT_ZOS}")

        # Persist detector data into the saved file, then optional heatmap.
        TheSystem.Save()
        try:
            import matplotlib
            matplotlib.use("Agg")   # non-interactive: avoids Qt/COM clash
            import matplotlib.pyplot as plt
            png = OUT_ZOS.replace(".zos", ".png")
            plt.figure(figsize=(5, 5))
            plt.imshow(arr, extent=[-DET_HALF_WIDTH, DET_HALF_WIDTH,
                                    -DET_HALF_WIDTH, DET_HALF_WIDTH],
                       origin="lower", cmap="inferno")
            plt.title("Spoiled corner-cube return")
            plt.xlabel("x (mm)"); plt.ylabel("y (mm)")
            plt.colorbar(label="W")
            plt.tight_layout(); plt.savefig(png, dpi=150)
            print(f"  saved: {png}")
        except ImportError:
            print("  (matplotlib not installed -- skipping heatmap)")
    finally:
        zos.close()


if __name__ == "__main__":
    main()
