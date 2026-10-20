# Multi-Configuration Editor (MCE)

The Multi-Configuration Editor lets a single optical system express multiple variants — different temperatures, zoom positions, beam paths, mechanical states — by listing operands that override surface or system parameters per config. Useful for thermal/mechanical envelopes, zoom lenses, multi-field studies, and parameter sweeps that are too small to justify rebuilding the system.

For pure parameter sweeps where you don't need persistent configurations, see the in-place sweep pattern in `patterns.md` instead.

## Configurations

```python
TheMCE = TheSystem.MCE
TheMCE.AddConfiguration(False)             # adds one; arg = whether to copy current
TheMCE.NumberOfConfigurations
TheMCE.SetCurrentConfiguration(idx)        # 1-based; switches the system to view that config
TheMCE.DeleteConfiguration(idx)            # one config
TheMCE.DeleteAllConfigurations()           # all configs (MCE-specific)
TheMCE.DeleteAllRows()                     # all operand ROWS — IEditor base method (works on LDE/NCE/MCE/MFE/TDE)
```

**Don't invent method names.** `IMultiConfigEditor` has `DeleteAllConfigurations()` (clears configs) and the inherited `DeleteAllRows()` (clears operand rows) — but no `RemoveAllOperands` or similar combo. The same `DeleteAllRows()` works on every editor; see `optimization.md` § "Merit Function Editor (MFE)" for the matching MFE warning about row-removal pitfalls.

`SetCurrentConfiguration` actually swaps the system's surface values — every analysis or trace afterward sees the values for that config. Switch back with `SetCurrentConfiguration(1)` (or whichever) when done.

## Operands

Each row of the MCE is an operand that controls one parameter across all configs. Add and configure:

```python
TheMCE.AddOperand()                                    # appended at end
op = TheMCE.GetOperandAt(idx)                          # 1-based
MCOT = ZOSAPI.Editors.MCE.MultiConfigOperandType
op.ChangeType(MCOT.THIC)                               # operand type
op.Param1 = 0                                          # surface number (operand-specific meaning)

# Per-config values:
op.GetOperandCell(1).DoubleValue = 10000.0             # config 1
op.GetOperandCell(2).DoubleValue = 5000.0              # config 2
op.GetOperandCell(3).DoubleValue = 1000.0              # config 3
```

`Param1` (and `Param2`, `Param3`) meanings depend on the operand type. For `THIC`, `Param1` = surface number. For `PRAM` (parameter), `Param1` = surface, `Param2` = parameter column.

### Cell value type depends on the operand

`GetOperandCell(i).DoubleValue` works for most operands (THIC, CRVT, CONI, SDIA, TEMP, PRES, ...) where the value is a real number. **A few operands store integers** — most notably **`IGNR`** (ignore-surface flag, 0/1) — and rejecting `DoubleValue` with a "value cannot be converted" error. The defensive pattern:

```python
def set_mce_cell(op, config_n, value):
    """Set an MCE operand cell, falling back to IntegerValue when DoubleValue is rejected."""
    cell = op.GetOperandCell(config_n)
    try:
        cell.DoubleValue = float(value)
    except Exception:
        cell.IntegerValue = int(value)
```

Same pattern applies anywhere `DoubleValue` looks like the right setter but the cell is actually integer-typed. The Coordinate Break surface's "Order" cell behaves the same way — see `sequential-design.md`. When in doubt, check `cell.DoubleValue` (read) first; if that raises, the cell is integer-typed and you need `IntegerValue`.

### Common MCE operand types

| Type | Controls |
|------|----------|
| `THIC` | Thickness of a surface |
| `CRVT` | Curvature (1/radius) of a surface |
| `CONI` | Conic constant of a surface |
| `GLSS` | Glass/material of a surface |
| `SDIA` | Semi-diameter of a surface |
| `PRAM` | A surface parameter column (Param2 = column index) |
| `TEMP` | System temperature |
| `PRES` | System pressure |
| `MOFF` | Multi-config offset (no-op placeholder) |
| `MCOM` | Multi-config comment |
| `IGNR` | Ignore a surface in this config |
| `APER` | Aperture |
| `XFIE` / `YFIE` | Field X / Y position |
| `WAVE` | Wavelength |

## Pickup solves between configs

Most thermal models pick up the same value across configs from a master config. The pattern uses a solve on the cell rather than a copy:

```python
SolveType = ZOSAPI.Editors.SolveType
solve = op.GetOperandCell(1).CreateSolveType(SolveType.ConfigPickup)
solve._S_ConfigPickup.Configuration = 1     # source config
solve._S_ConfigPickup.Operand = 5           # source operand row (when picking from a different operand)
op.GetOperandCell(2).SetSolveData(solve)    # apply to config 2
```

### Thermal pickup

`SolveType.ThermalPickup` is the special case for "thermalize this parameter from config 1". The shipped Doublet thermal example sets up TEMP/PRES/CRVT/THIC/SDIA operands across two configs, with thermal-pickup solves on the geometric operands so they automatically follow the temperature change in the master config:

```python
TheMCE.AddConfiguration(False)             # config 2
# Add TEMP, PRES, CRVT, THIC, GLSS, SDIA operands for each surface...
TheMCE.GetOperandAt(1).ChangeType(MCOT.TEMP)        # operand 1 = temperature
TheMCE.GetOperandAt(1).GetOperandCell(2).DoubleValue = 100.0   # 100°C in config 2

TheSystem.SystemData.Environment.AdjustIndexToEnvironment = True

# Thermal pickup on the geometric operands:
solve = TheMCE.GetOperandAt(3).GetOperandCell(1).CreateSolveType(SolveType.ThermalPickup)
solve._S_ThermalPickup.Configuration = 1
for op_idx in [3, 4, 6, 7, 8, 10, 11, 12, 13]:
    TheMCE.GetOperandAt(op_idx).GetOperandCell(2).SetSolveData(solve)
```

This reproduces the GUI's "Make Thermal" wizard. The result: changing the temperature in any config automatically updates surface curvatures, thicknesses, and indices via the pickup chain.

## Idiomatic per-config alignment loop

After setting up a multi-config system, you usually want each config to be independently focused (the optimum image plane shifts with temperature, zoom position, etc.):

```python
qf = TheSystem.Tools.OpenQuickFocus()
qf.Criterion = ZOSAPI.Tools.General.QuickFocusCriterion.SpotSizeRadial
for i in range(1, TheMCE.NumberOfConfigurations + 1):
    TheMCE.SetCurrentConfiguration(i)
    qf.RunAndWaitForCompletion()
qf.Close()
```

Replace `OpenQuickFocus` with `OpenLocalOptimization` for a full per-config optimization run — same loop pattern. Each call sees the current config's variables and merit function.

## When to use MCE vs. in-place sweep

| Scenario | Use |
|----------|-----|
| Permanent design variants (thermal envelope, zoom positions) | MCE |
| Iterating a single design under different beam polarizations | MCE (POLA operand) or in-place sweep |
| Tolerancing study | Tolerancing tool (see `optimization.md`) |
| Parameter sweep for sensitivity analysis | In-place sweep (see `patterns.md`) — faster, no MCE bookkeeping |
| Multi-wavelength or multi-field analysis at fixed config | Just configure SystemData.Wavelengths / SystemData.Fields — no MCE needed |
