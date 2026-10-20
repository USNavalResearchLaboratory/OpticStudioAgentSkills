# Probe ObjectData.__implementation__ across the four parts of the ZOS-API
# where ParN cells, settings keywords, and tool properties tend to bite:
#
#   1) NCE objects        -- non-sequential components (sources, detectors, ...)
#   2) LDE surface types  -- sequential surfaces (Standard, EvenAspheric, ...)
#   3) Analyses           -- typed settings on each AnalysisIDM
#   4) Tools              -- typed properties on each Tools.Open* result
#
# The dump shows typed property names, defaults, setter methods, and (for NCE)
# ParN cell values. Use the names under "Typed properties" in your code -- pythonnet
# silently creates Python attributes when you guess wrong, leaving the model unchanged.
#
# Edit the four lists below to control what gets probed. Run from a Python env with
# pythonnet installed and Zemax OpticStudio accessible via the standard ZOSAPI registry.

import clr, os, winreg
from itertools import islice


# Edit these lists to add/remove types you want to probe.
NCE_TYPES = [
    'SourceDiode',
    'SourceGaussian',
    'DetectorRectangle',
    'StandardSurface',
    'RectangularVolume',
    'CylinderVolume',
    # Other useful: 'NullObject', 'DetectorPolar', 'SourceFile', 'CADPart',
    # 'EllipticalVolume', 'Mirror', 'DiffractionGrating' (NCE version), ...
]

LDE_SURFACE_TYPES = [
    'Standard',
    'EvenAspheric',         # NOT 'EvenAsphere' (which does not exist in v24.1)
    'Paraxial',
    'CoordinateBreak',
    'Toroidal',
    'DiffractionGrating',
    'BlackBoxLens',         # .ZBB playback — typed setter is BlackBoxLensFilename (NOT ISurfaceTypeSettings.Filename, which throws NRE)
    # Other useful: 'OddAsphere', 'Binary1' (NOT 'BinaryOptic1'), 'ZernikeStandardSag',
    # 'GridSag', 'Fresnel' (NOT 'Fresnel1' / 'Fresnel2'), 'Tilted', 'ABCD', ...
]

ANALYSIS_TYPES = [
    'StandardSpot',
    'FftMtf',
    'GeometricMtf',
    'RayFan',
    'OPDFan',
    'Wavefront',
    'FieldCurvatureDistortion',
    'EncircledEnergy',
    'FftPsf',
    'NSC3DLayout',          # NSC-only; runs but settings still probe-able on seq system
    'DetectorViewer',       # NSC-only
]

# (display_name, Tools.Open<MethodName>) pairs.
TOOL_TYPES = [
    # Optimization
    ('LocalOptimization',         'OpenLocalOptimization'),
    ('GlobalOptimization',        'OpenGlobalOptimization'),
    ('HammerOptimization',        'OpenHammerOptimization'),
    ('QuickFocus',                'OpenQuickFocus'),
    ('QuickAdjust',               'OpenQuickAdjust'),
    # Catalogs (lens + materials search)
    ('LensCatalogs',              'OpenLensCatalogs'),
    ('MaterialsCatalog',          'OpenMaterialsCatalog'),
    # Ray tracing
    ('NSCRayTrace',               'OpenNSCRayTrace'),
    ('BatchRayTrace',             'OpenBatchRayTrace'),
    ('RayDatabaseReader',         'OpenRayDatabaseReader'),
    ('LightningTrace',            'OpenLightningTrace'),
    ('CriticalRaysetGenerator',   'OpenCriticalRaysetGenerator'),
    # Tolerancing / sensitivity
    ('Tolerancing',               'OpenTolerancing'),
    ('QuickSensitivity',          'OpenQuickSensitivity'),
    ('ToleranceDataViewer',       'OpenToleranceDataViewer'),
    # Calculators
    ('MeritFunctionCalculator',   'OpenMeritFunctionCalculator'),
    ('RMSSpotRadiusCalculator',   'OpenRMSSpotRadiusCalculator'),
    # Lens transformations
    ('Scale',                     'OpenScale'),
    ('ConvertToNSCGroup',         'OpenConvertToNSCGroup'),
    ('ConvertAsphereTypes',       'OpenConvertAsphereTypes'),
    ('FindBestAsphere',           'OpenFindBestAsphere'),
    ('RayAimingWizard',           'OpenRayAimingWizard'),
    # Files / archive / export
    ('ExportCAD',                 'OpenExportCAD'),
    ('CreateZAR',                 'OpenCreateZAR'),
    ('RestoreZAR',                'OpenRestoreZAR'),
    ('CreateProject',             'OpenCreateProject'),
    ('RestoreProject',            'OpenRestoreProject'),
    ('FileManager',               'OpenFileManager'),
    ('DesignLockdown',            'OpenDesignLockdown'),
]


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

    def __del__(self):
        if self.TheApplication is not None:
            self.TheApplication.CloseApplication()
            self.TheApplication = None
        self.TheConnection = None


# ---------------------------------------------------------------------------
# Generic helper: dump typed properties + setter methods from a .NET impl
# ---------------------------------------------------------------------------

def _dump_impl(impl, label='impl'):
    """Print the typed-property table for any pythonnet wrapper's __implementation__."""
    print(f"  {label} type: {type(impl).__name__}")

    all_attrs = dir(impl)
    typed_props = sorted(set(
        a for a in all_attrs
        if not a.startswith('_')
        and not a.startswith('get_')
        and not a.startswith('set_')
        and not a.startswith('Par')
        and a[0].isupper()
        and 'Cell' not in a
    ))
    print(f"\n  Typed properties (use these in your code):")
    for prop in typed_props:
        try:
            val = getattr(impl, prop)
            if callable(val) and not isinstance(val, (int, float, str, bool)):
                continue   # skip method-like attributes
            print(f"    {prop:34s} = {val}")
        except Exception as e:
            print(f"    {prop:34s} = ERROR: {e}")

    setters = sorted(a for a in all_attrs if a.startswith('set_'))
    if setters:
        print(f"\n  Setter methods (writable typed properties):")
        for s in setters:
            print(f"    {s}")


def _get_impl(obj):
    """Return obj.__implementation__ via either get_ObjectData or direct access.
    Some ZOSAPI types expose it directly; some need an explicit getter cast."""
    # try direct first (works for tools, analyses settings, surface data)
    try:
        return obj.__implementation__
    except AttributeError:
        pass
    # NCE objects need this form
    try:
        return obj.get_ObjectData().__implementation__
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 1) NCE objects -- ParN cell layout matters; dump both ObjectData and cells
# ---------------------------------------------------------------------------

def probe_nce_object(nce, name, ot_enum, oc_enum):
    nce.InsertNewObjectAt(nce.NumberOfObjects + 1)
    obj = nce.GetObjectAt(nce.NumberOfObjects)
    obj.ChangeType(obj.GetObjectTypeSettings(ot_enum))

    print(f"\n{'='*70}\n  [NCE] {name}  (TypeName: {obj.TypeName})\n{'='*70}")
    print(f"\n  ObjectData (interface) type: {type(obj.ObjectData).__name__}")
    impl = obj.get_ObjectData().__implementation__
    _dump_impl(impl, label='.__implementation__')

    print(f"\n  ParN cell values (raw -- compare to typed property defaults above):")
    for par_num in range(1, 20):
        col_name = f'Par{par_num}'
        if not hasattr(oc_enum, col_name):
            break
        cell = obj.GetObjectCell(getattr(oc_enum, col_name))
        try:
            v = cell.DoubleValue
            print(f"    Par{par_num:2d} (dbl) = {v}")
        except Exception:
            try:
                v = cell.IntegerValue
                print(f"    Par{par_num:2d} (int) = {v}")
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 2) LDE surface types -- same pattern but via SurfaceData
# ---------------------------------------------------------------------------

def probe_lde_surface(lde, name, st_enum):
    lde.InsertNewSurfaceAt(2)
    surf = lde.GetSurfaceAt(2)
    surf.ChangeType(surf.GetSurfaceTypeSettings(st_enum))

    print(f"\n{'='*70}\n  [LDE Surface] {name}  (TypeName: {surf.TypeName})\n{'='*70}")
    # Surface itself has the universal properties (Radius, Thickness, Material, Conic, IsStop, ...)
    print(f"\n  Surface (universal) typed properties:")
    for prop in ('Radius', 'Thickness', 'Material', 'Conic', 'SemiDiameter',
                 'Comment', 'IsStop', 'TiltDecData'):
        if hasattr(surf, prop):
            try:
                print(f"    {prop:30s} = {getattr(surf, prop)}")
            except Exception:
                pass

    # Surface-type-specific data via SurfaceData.__implementation__
    print(f"\n  SurfaceData.__implementation__ (type-specific properties):")
    try:
        sd_impl = surf.get_SurfaceData().__implementation__
        _dump_impl(sd_impl, label='SurfaceData.__implementation__')
    except Exception as e:
        print(f"    SurfaceData probe failed: {e}")

    # ParN cells on the surface (also type-specific)
    print(f"\n  ParN cell values on the surface:")
    SC = lde.GetSurfaceAt(2).GetCellAt
    for par_num in range(1, 15):
        try:
            cell = SC(par_num + 12)   # ISurface cells: 1..12 are universal, 13+ are params
            try:
                v = cell.DoubleValue
                print(f"    Par{par_num:2d} (dbl) = {v}")
            except Exception:
                try:
                    v = cell.IntegerValue
                    print(f"    Par{par_num:2d} (int) = {v}")
                except Exception:
                    pass
        except Exception:
            break

    lde.RemoveSurfaceAt(2)


# ---------------------------------------------------------------------------
# 3) Analyses -- typed settings on each AnalysisIDM
# ---------------------------------------------------------------------------

def probe_analysis(analyses, name, idm_enum):
    print(f"\n{'='*70}\n  [Analysis] {name}\n{'='*70}")
    try:
        analysis = analyses.New_Analysis(idm_enum)
    except Exception as e:
        print(f"  Could not create analysis: {e}")
        return

    print(f"  HasAnalysisSpecificSettings: {analysis.HasAnalysisSpecificSettings}")
    if not analysis.HasAnalysisSpecificSettings:
        print(f"  --> No typed settings; use ModifySettings with a saved .cfg file instead.")

    settings = analysis.GetSettings()
    print(f"  GetSettings() interface type: {type(settings).__name__}")
    impl = _get_impl(settings)
    if impl is not None:
        _dump_impl(impl, label='Settings.__implementation__')
    else:
        print(f"  No __implementation__ accessible; fall back to ModifySettings + .cfg.")
    analysis.Close()


# ---------------------------------------------------------------------------
# 4) Tools -- typed properties on each Tools.Open* result
# ---------------------------------------------------------------------------

def probe_tool(tools, name, open_method_name):
    print(f"\n{'='*70}\n  [Tool] {name}  (Tools.{open_method_name})\n{'='*70}")
    open_method = getattr(tools, open_method_name, None)
    if open_method is None:
        print(f"  Tools.{open_method_name} not present in this ZOS-API version.")
        return
    try:
        tool = open_method()
    except Exception as e:
        print(f"  Could not open tool: {e}")
        return

    impl = _get_impl(tool)
    _dump_impl(impl if impl is not None else tool, label='Tool.__implementation__')
    try:
        tool.Close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    zos = PythonStandaloneApplication()
    ZOSAPI = zos.ZOSAPI
    TheApplication = zos.TheApplication

    # Phase 1: sequential system for LDE surfaces, analyses, tools
    seq = TheApplication.PrimarySystem        # default is sequential
    seq.New(False)
    LDE = seq.LDE
    Analyses = seq.Analyses
    Tools = seq.Tools
    SurfaceType = ZOSAPI.Editors.LDE.SurfaceType
    AnalysisIDM = ZOSAPI.Analysis.AnalysisIDM

    print("Probing ZOS-API typed property surfaces. Use the names under 'Typed properties'")
    print("in your code -- guessing them produces silent Python-attribute shadows that")
    print("never reach the Zemax model.")

    print("\n\n##### LDE SURFACE TYPES #####")
    for name in LDE_SURFACE_TYPES:
        if not hasattr(SurfaceType, name):
            print(f"\n  WARNING: '{name}' is not in ZOSAPI.Editors.LDE.SurfaceType")
            continue
        try:
            probe_lde_surface(LDE, name, getattr(SurfaceType, name))
        except Exception as e:
            print(f"\n  ERROR probing LDE.{name}: {e}")

    print("\n\n##### ANALYSES #####")
    for name in ANALYSIS_TYPES:
        if not hasattr(AnalysisIDM, name):
            print(f"\n  WARNING: '{name}' is not in ZOSAPI.Analysis.AnalysisIDM")
            continue
        try:
            probe_analysis(Analyses, name, getattr(AnalysisIDM, name))
        except Exception as e:
            print(f"\n  ERROR probing Analysis.{name}: {e}")

    print("\n\n##### TOOLS #####")
    for name, open_method_name in TOOL_TYPES:
        try:
            probe_tool(Tools, name, open_method_name)
        except Exception as e:
            print(f"\n  ERROR probing Tools.{open_method_name}: {e}")

    # Phase 2: NSC system for NCE object types
    nsc = TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)
    NCE = nsc.NCE
    OT = ZOSAPI.Editors.NCE.ObjectType
    OC = ZOSAPI.Editors.NCE.ObjectColumn

    print("\n\n##### NCE OBJECT TYPES #####")
    for name in NCE_TYPES:
        if not hasattr(OT, name):
            print(f"\n  WARNING: '{name}' is not in ZOSAPI.Editors.NCE.ObjectType")
            continue
        try:
            probe_nce_object(NCE, name, getattr(OT, name), OC)
        except Exception as e:
            print(f"\n  ERROR probing NCE.{name}: {e}")

    del zos
    zos = None
    print("\nDone.")
