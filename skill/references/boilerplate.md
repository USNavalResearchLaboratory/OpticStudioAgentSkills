# Boilerplate: Connection and Setup

## The PythonStandaloneApplication class

Every ZOS-API script starts the same way: locate the Zemax install directory via the Windows registry, load three .NET assemblies, instantiate a `ZOSAPI_Connection`, and acquire `TheApplication` and `TheSystem`. Use this exact class — don't invent alternative connection patterns.

```python
import clr, os, winreg
from itertools import islice


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

    def reshape(self, data, x, y, transpose=False):
        """Convert a System.Double[,] to a 2D Python list."""
        if type(data) is not list:
            data = list(data)
        var_lst = [y] * x
        it = iter(data)
        res = [list(islice(it, i)) for i in var_lst]
        if transpose:
            return self.transpose(res)
        return res

    def transpose(self, data):
        if type(data) is not list:
            data = list(data)
        return list(map(list, zip(*data)))
```

## Entry point pattern

```python
if __name__ == '__main__':
    zos = PythonStandaloneApplication()
    ZOSAPI = zos.ZOSAPI
    TheApplication = zos.TheApplication
    TheSystem = zos.TheSystem

    # ---- design logic here ----

    del zos
    zos = None
```

## System creation

For a non-sequential design (NSC), create a fresh system explicitly:

```python
TheSystem = TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)
NCE = TheSystem.NCE
```

Don't use `TheSystem.MakeNonSequential()` here — it exists but is **lossy** (flips the editor mode without porting any loaded surface/object data). For a fresh empty NSC system use `CreateNewSystem(SystemType.NonSequential)`; for converting an existing loaded lens (e.g. from a `.zmx`) use `Tools.OpenConvertToNSCGroup()` — see `references/sequential-design.md`.

For sequential designs, the default system is already sequential; just use `TheSystem.LDE`.

## Key API entry points

The full namespace tour lives in `system-and-application.md`. Quick orientation:

| Object | Purpose | Detailed reference |
|--------|---------|-------------------|
| `TheSystem.LDE` | Lens Data Editor (sequential surfaces) | `sequential-design.md` |
| `TheSystem.NCE` | Non-sequential Component Editor | `nsc-objects.md`, `conventions.md` |
| `TheSystem.MCE` | Multi-Configuration Editor | `multi-config.md` |
| `TheSystem.MFE` | Merit Function Editor | `optimization.md` |
| `TheSystem.TDE` | Tolerance Data Editor | `optimization.md` |
| `TheSystem.SystemData` | System Explorer (Aperture, Fields, Wavelengths, Environment, ...) | `sequential-design.md` |
| `TheSystem.Tools` | OpenNSCRayTrace, OpenLocalOptimization, OpenQuickFocus, OpenBatchRayTrace, ... | `optimization.md`, `ray-database.md` |
| `TheSystem.Analyses` | New_Analysis, New_StandardSpot, New_FftMtf, ... | `analyses.md` |

## Connection modes

The boilerplate above uses **Standalone mode** — `TheConnection.CreateNewApplication()` launches a headless OpticStudio for the script's lifetime. This is right for nearly all automation.

The other supported mode is **Interactive Extension** (`TheConnection.ConnectAsExtension(instance_id)`), which attaches to a running OpticStudio with the GUI visible. It requires the user to enable Programming → Interactive Extension in the GUI menu first. **Critical caveat:** Interactive Extension defaults to `UpdateMode = EditorsOnly` for performance, so analyses created via the API don't refresh in the GUI windows automatically. See `system-and-application.md` for the full pattern (and the User Extension / User Analysis modes too, which are C#/C++ only).

## Cleanup matters

Always `del zos; zos = None` **before** any blocking call (like `plt.show()` or `input()`). Without this, OpticStudio holds resources and may leak between runs. The `__del__` method calls `CloseApplication()`, which is what releases the license slot.

If you forget to clean up, subsequent runs may fail with "License is not valid" until the OS reaps the orphan process.

## Save/load files

```python
TheSystem.SaveAs(r'C:\path\to\design.zos')   # write
TheSystem.LoadFile(r'C:\path\to\design.zos', False)  # read; second arg = saveIfNeeded
TheSystem.Close(False)                       # close current; arg = save
```

`.zos` is the modern format; `.zmx` is the legacy text format. Either can be loaded.

## Helper: converting `System.Double[,]` to numpy

The `reshape` method on the boilerplate class converts the .NET 2D arrays returned by detector queries into a Python list-of-lists. Wrap that with `np.array()` and (usually) `np.flipud()` to match the orientation Zemax displays:

```python
import numpy as np

def to_numpy(raw_data, zos_instance):
    """Convert System.Double[,] to numpy array (Y-flipped to match Zemax display)."""
    data_2d = zos_instance.reshape(raw_data,
                                   raw_data.GetLength(0),
                                   raw_data.GetLength(1))
    return np.flipud(np.array(data_2d))
```

The `flipud` is because Zemax orders detector rows top-to-bottom, but matplotlib's `imshow` defaults to bottom-to-top.
