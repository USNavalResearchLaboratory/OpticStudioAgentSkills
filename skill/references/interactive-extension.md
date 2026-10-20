# Interactive Extension Mode

Standalone mode is the default in `boilerplate.md` because it's headless and "just runs" — but several features only work when there's a real GUI behind the API. The most important: **all programmatic image export tools** (`Tools.Layouts.OpenNSC3DLayoutExport`, `OpenShadedModelExport`, sequential layout exports, ...) silently no-op or return empty files in Standalone mode. They depend on the GUI's render context. Same for `analysis.ToFile()`.

If you need a layout PNG, a rendered MTF figure, or anything else that hits Zemax's render pipeline, you need **Interactive Extension (IE) mode**. This file is the recipe.

## When to use which mode

| Operation | Standalone | Interactive Extension |
|---|---|---|
| Build / edit / load / save `.zos` systems | ✅ | ✅ |
| Numeric extraction (`SpotData`, `DataSeries`, `DataGrid`, `GetDetectorData`, coherent E-fields) | ✅ | ✅ |
| Optimization / Tolerancing / QuickFocus | ✅ | ✅ |
| Ray tracing (NSC, batch, ZRD reader) | ✅ | ✅ |
| `UpdateStatus()` system validation | ✅ | ✅ |
| **Layout image export (`Tools.Layouts.Open*Export`)** | ❌ silent no-op | ✅ |
| **`analysis.ToFile()` (rendered figures)** | ❌ unreliable / empty | ✅ |
| Live debugging — watching edits in the GUI as they happen | ❌ no GUI | ✅ |

**Rule of thumb:** start in Standalone. Switch to IE only when you specifically need an image artifact or want to demo / debug live with the user watching.

## The agent ↔ user handoff

IE mode requires a one-time GUI step from the user (the GUI's `Programming → Interactive Extension` menu item is what puts OpticStudio into "listening" state). The agent can't do this itself — it needs the user. The exact sequence:

1. **Agent tells the user, in the conversation:**

   > "I need Interactive Extension mode for this step (image export doesn't work in headless mode).
   > Please:
   > 1. Open Zemax OpticStudio (or bring an existing window to the front).
   > 2. In the menu bar: **Programming → Interactive Extension**.
   > 3. You should see a 'Listening' status appear.
   > Reply when that's done and I'll connect."

2. **User does the GUI step and replies.**

3. **Agent runs a script that calls `ConnectAsExtension(0)`.** If the user hasn't enabled IE yet, the connection fails immediately with a clear error — re-prompt them.

4. **Agent does its work** — image export, the analysis-and-render flow from `verification.md`, whatever needed the GUI render context.

5. **Agent disconnects (does NOT call `CloseApplication()`)** so the user's OpticStudio session stays open. They can keep iterating in the GUI from where the agent left things, or close it themselves when done.

This is structurally identical to `gcloud auth login` or `git push` over SSH — one human-in-the-loop bootstrap, then automated work. Accept the once-per-session friction; it's the cost of having images.

## Connection class for IE mode

The standard `PythonStandaloneApplication` class in `boilerplate.md` calls `CreateNewApplication()` and `CloseApplication()`. IE mode needs `ConnectAsExtension(0)` and **must skip `CloseApplication()`** (otherwise it closes the user's GUI). Below is the parallel class — same boilerplate everywhere else:

```python
import clr, os, winreg
from itertools import islice


class PythonInteractiveApplication(object):
    """Connect to a running OpticStudio GUI that has Programming → Interactive
    Extension enabled. Does NOT close the GUI on exit — leave it for the user."""

    class LicenseException(Exception): pass
    class ConnectionException(Exception): pass
    class InitializationException(Exception): pass
    class SystemNotPresentException(Exception): pass
    class ExtensionNotEnabledException(Exception): pass

    def __init__(self, instance=0, path=None):
        # Same DLL-loading dance as the standalone class
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

        # KEY DIFFERENCE: ConnectAsExtension instead of CreateNewApplication
        self.TheApplication = self.TheConnection.ConnectAsExtension(instance)
        if self.TheApplication is None:
            raise self.ExtensionNotEnabledException(
                "ConnectAsExtension failed. Is OpticStudio running with "
                "Programming → Interactive Extension enabled?")
        if not self.TheApplication.IsValidLicenseForAPI:
            raise self.LicenseException("License is not valid for ZOSAPI use.")

        self.TheSystem = self.TheApplication.PrimarySystem
        if self.TheSystem is None:
            raise self.SystemNotPresentException("Unable to acquire Primary system.")

    def __del__(self):
        # KEY DIFFERENCE: do NOT call CloseApplication() — that would close the
        # user's OpticStudio GUI. Just drop our references; the GUI keeps running.
        self.TheApplication = None
        self.TheConnection = None

    # The reshape / transpose helpers are identical to the standalone class —
    # copy them in or share via inheritance.
```

Use it the same way:

```python
zos = PythonInteractiveApplication()       # raises if IE not enabled
ZOSAPI = zos.ZOSAPI
TheApplication = zos.TheApplication
TheSystem = zos.TheSystem

# ... do image-export, optimization, analysis as usual ...

del zos                                    # disconnects without closing the GUI
zos = None
```

## The UpdateMode trap (cross-link)

When connected via IE, `TheSystem.UpdateMode` defaults to `LensUpdateMode.EditorsOnly` for performance. **Analysis windows do not refresh** when you edit the lens via the API. Either loop `Get_AnalysisAtIndex(i).ApplyAndWaitForCompletion()` after edits, or set `TheSystem.UpdateMode = ZOSAPI.LensUpdateMode.AllWindows` and call `TheSystem.UpdateStatus()` once. Full discussion in `system-and-application.md` § "Interactive Extension: the UpdateMode trap."

## IE-mode trap: `New(False)` inherits the GUI's last system type

In **Standalone** mode the system you get from `TheApplication.PrimarySystem` is sequential by default; `TheSystem.New(False)` resets to a clean sequential system. **In IE mode** `PrimarySystem` and `New(False)` reflect whatever system type the user happened to have open in the GUI just before they enabled Interactive Extension. If they were last working in NSC, your "fresh" sequential script silently lands on an NSC system and every LDE call fails or no-ops.

Fix: don't use `New(False)`. Always pin the type explicitly with `CreateNewSystem`:

```python
# WRONG in IE mode — inherits whatever system type the user last had open
TheSystem.New(False)

# RIGHT — gives you a guaranteed sequential (or NSC) system regardless of GUI state
TheSystem = TheApplication.CreateNewSystem(ZOSAPI.SystemType.Sequential)
# or:
TheSystem = TheApplication.CreateNewSystem(ZOSAPI.SystemType.NonSequential)
```

This idiom is harmless in Standalone too, so use `CreateNewSystem(SystemType.X)` everywhere when the script needs a known starting type. The asymmetry only matters when porting a Standalone script that uses `New(False)` to IE.

## Cleanup checklist

- ✅ Save your `.zos` if you want changes to persist (`TheSystem.SaveAs(...)` or `TheSystem.Save()`). The GUI doesn't auto-save.
- ✅ Drop your `zos` reference (`del zos; zos = None`) — disconnects cleanly.
- ❌ Do NOT call `TheApplication.CloseApplication()` — that closes the user's GUI session.
- ❌ Do NOT close any analysis windows the user opened manually before your script ran. (Closing analyses you opened via `New_Analysis(...)` is fine via `analysis.Close()`.)

## Hybrid pattern: most work in standalone, IE for the artifact pass

The most efficient agent flow when only the final images need IE:

1. **Phase 1 — standalone:** build, optimize, validate, extract numeric metrics, save `.zos`. No user interaction needed.
2. **Phase 2 — IE:** when the design is final and you want layout / shaded-model / rendered-MTF images, ask the user to enable IE, load the saved `.zos`, run only the export tools, save images, disconnect.

This minimizes the "interactive bottleneck" — the user is only blocked once per design, at the end, when there's actually something worth looking at.

## Failure modes and remedies

| Symptom | Likely cause | Fix |
|---|---|---|
| `ConnectAsExtension` returns `None` | OpticStudio isn't running, or Programming → Interactive Extension isn't enabled | Re-prompt the user; they may need to enable IE again after closing/reopening the file |
| `IsValidLicenseForAPI` is False even though IE was enabled | License floats away from this seat | User checks license / restarts OpticStudio |
| Edits to LDE/NCE happen but analysis windows are stale | The `UpdateMode = EditorsOnly` trap | Set `UpdateMode = AllWindows`, or call `Get_AnalysisAtIndex(i).ApplyAndWaitForCompletion()` after each batch of edits |
| Image-export tools say `IsValidFileName=False` despite a valid path | `OutputFileName` is outside `TheApplication.ImagesDir` | Render to `ImagesDir`, then `shutil.copy2` to your real artifact folder (see `analyses.md` § "NSC 3D Layout image export") |
| Script ends and OpticStudio also closes | `CloseApplication()` was called, or the IE class still inherits the standalone `__del__` | Use the `PythonInteractiveApplication` class above, not `PythonStandaloneApplication`, and verify the `__del__` doesn't call `CloseApplication()` |

If you're not sure whether you're in IE or Standalone mode at runtime: there isn't a clean API flag for it, but the symptoms above (especially the silent image-export no-op and the rendered-figure unreliability) are the giveaway.
