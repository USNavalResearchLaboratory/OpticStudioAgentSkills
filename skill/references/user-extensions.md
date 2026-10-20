# User Extensions: What Python Can and Can't Do

OpticStudio supports four kinds of "user extension" that extend or replace built-in functionality. **Python can author one of them** (operand callbacks via the API). The other three require compiled C# or C++. This file is short on purpose — it just clarifies the boundary so you don't waste time trying to write a User Analysis in Python.

## The four extension types

| Extension | What it does | Languages | Files |
|-----------|--------------|-----------|-------|
| **User Operand (UDOC)** | Custom merit-function operand. OpticStudio calls a compiled `UDOC##.exe` and reads back a numeric value the optimizer treats like any other operand. | C# or C++ — compiled to `.exe` | `{Zemax}\ZOS-API\Operands\UDOC##.exe` (`##` = 01..99) |
| **User Analysis** | Custom analysis window that appears in OpticStudio's Analyses menu alongside built-in analyses. | C# only — compiled DLL | `{Zemax}\ZOS-API Extensions\` |
| **User Extension** | General-purpose extension launched from the OpticStudio menu — full programmatic control of the running session. | C# or C++ — compiled DLL | `{Zemax}\ZOS-API Extensions\` |
| **User Operand callback** | Python function registered as an operand handler. Lets you compute a custom MFE value from a Python script, without compiling anything. | **Python** (and others) via `RegisterNETOperandCallback` | n/a — registered at runtime |

The bundled `User-Defined-Operand-(UDOC).py` example just contains a comment confirming "no python" — UDOC `.exe` files cannot be authored in Python. Use the callback approach below instead.

## What Python CAN do

### Call a pre-compiled UDOC operand

If someone else (or you, in C#) has compiled a UDOC and dropped it in `{Zemax}\ZOS-API\Operands\UDOC07.exe`, your Python script can use it like any other MFE operand:

```python
op = TheMFE.AddOperand()
op.ChangeType(ZOSAPI.Editors.MFE.MeritOperandType.UDOC)
op.GetCellAt(2).IntegerValue = 7      # UDOC index → calls UDOC07.exe
op.GetCellAt(3).IntegerValue = 1      # operand-specific args (passed to the .exe)
op.Target = 0.0; op.Weight = 1.0
```

### Implement an operand callback in pure Python

`RegisterNETOperandCallback` registers a Python function as the implementation of an `UDOP` (user-defined operand callback) operand. The Python function gets called every time the optimizer evaluates the merit function. Pattern:

```python
def my_operand_callback(args):
    # args.OperandArgument1, args.OperandArgument2, ... carry the per-operand inputs
    # access TheSystem here to compute whatever metric you want
    value = compute_my_metric(TheSystem, args.OperandArgument1)
    args.OperandResults = value           # one number returned to the optimizer

callback_id = TheApplication.RegisterNETOperandCallback(my_operand_callback)
# Use the matching MFE operand (UDOP family) and pass callback_id as the lookup
```

The exact MFE operand type that pairs with a callback is documented in the CHM (search "User-Defined Operand"). The callback runs in the same Python process, so you have full numpy/scipy access. The trade-off is per-call overhead from the .NET → Python crossing, so don't put expensive computations inside if you can avoid it.

### Run command strings

`TheApplication.RunCommand(cmd_string)` exposes a small set of OpticStudio commands. Mostly useful for things the API doesn't expose directly (some legacy macros). Returns nothing structured — output goes to the message log:

```python
TheApplication.BeginMessageLogging()
TheApplication.RunCommand('SOME COMMAND')
msgs = TheApplication.RetrieveLogMessages()
TheApplication.EndMessageLogging()
```

### Package a Python script as a Zemax-distributable executable

The `Generate-the-executable-in-Python-for-ZOS-API-User-Extensions.html` Ansys article describes packaging a Python ZOS-API script with PyInstaller into a `.exe`, then placing it where OpticStudio expects a User Extension. The script still talks to the API via Standalone or Interactive Extension; the packaging just lets users launch it from OpticStudio's menu like a native extension. Useful if you want to ship Python automation to colleagues who don't have Python installed.

## What Python CAN'T do

- **Author a User Analysis or User Extension** that appears in OpticStudio's menu.
- **Author a UDOC `.exe`** that runs as a compiled operand (the `RegisterNETOperandCallback` route is similar in spirit but technically different — the operand is `UDOP`, not `UDOC`, and it requires the Python script to be running).
- **Hook into surface DLLs** (custom surface types implemented as `.DLL`). Those are C/C++ only.

For any of these, the workflow is: write the extension in C#/C++ using the full ZOS-API.NET, compile it, then drive it from Python (or use it from the GUI). That's the path the `Custom-DLLs-in-OpticStudio-*.html` and `How-to-create-a-User-Analysis-using-ZOS-API.html` Ansys articles describe.
