# Test fixture for check_namespace.py -- mix of valid and intentionally-broken
# ZOS-API references. Expected: real names resolve, typos and made-up names fail.

import clr
import ZOSAPI
import System

# --- Valid: should all resolve --------------------------------------------

from ZOSAPI.Editors.LDE import SurfaceType
from ZOSAPI.Analysis import AnalysisIDM as AIDM

x1 = ZOSAPI.SystemType.Sequential
x2 = ZOSAPI.SystemType.NonSequential
x3 = ZOSAPI.Editors.LDE.SurfaceType.EvenAspheric
x4 = ZOSAPI.Editors.SolveType.SurfacePickup
x5 = ZOSAPI.Editors.NCE.ObjectType
x6 = ZOSAPI.Analysis.AnalysisIDM.FftMtf
x7 = SurfaceType.CoordinateBreak                 # via from-import alias
x8 = AIDM.RayFan                                 # via from-import alias-as
x9 = System.Int32
x10 = System.Enum.GetValues

# Local alias chain
ST = ZOSAPI.Editors.LDE.SurfaceType
y1 = ST.Standard
y2 = ST.DiffractionGrating

# --- Invalid: should fail --------------------------------------------------

bad1 = ZOSAPI.SystemType.Sequental               # typo: missing 'i'
bad2 = ZOSAPI.Editors.LDE.SurfaceTpye            # typo: 'pye'
bad3 = ZOSAPI.Analysis.AnalysisIDM.FftMTF        # casing wrong (should be FftMtf)
bad4 = ZOSAPI.MadeUpNamespace.X                  # outright fake
bad5 = ST.NotAnEnumMember                        # bad via alias
bad6 = System.Int37                              # fake System type

# Should be ignored: not rooted at ZOSAPI/System
ignored = some_local.GetSurfaceAt(2).Radius
