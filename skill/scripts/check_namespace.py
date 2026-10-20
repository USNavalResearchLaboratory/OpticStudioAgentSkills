# check_namespace.py -- pre-flight namespace check for ZOS-API Python scripts.
#
# Parses a Python source file with the ast module, extracts every dotted
# attribute chain rooted at ZOSAPI or System, then resolves each chain via
# getattr against a live Standalone OpticStudio session. Reports unresolved
# chains with file:line so typos and version mismatches are caught before the
# script runs.
#
# Accepts .py files directly and .md files (extracts ```python fenced blocks
# and reports failures back at the original markdown line). Useful for auditing
# documentation as well as runnable scripts.
#
# Usage:
#     python check_namespace.py path/to/script.py [path/to/another.py ...]
#     python check_namespace.py path/to/reference.md script.py --show-resolved
#
# Exit codes: 0 = all resolved, 1 = unresolved chain(s), 2 = bad input.
#
# WHAT IT CATCHES
#   - Sub-namespace and enum typos      (ZOSAPI.Editors.LDE.SurfaceTpye)
#   - Missing methods on interfaces     (ZOSAPI.SystemType.Sequental)
#   - Renamed members across versions   (ZOSAPI.OldName.Member)
#   - from-import typos                 (from ZOSAPI.Editors.LDE import SurfaceTpye)
#
# WHAT IT CANNOT CATCH (these still need probe/CHM/runtime)
#   - surf.get_SurfaceData().__implementation__.X -- runtime-dispatched type
#   - _S_* solve/aperture settings sub-objects (created at call time)
#   - MCE/MFE operand parameter-cell semantics
#   - String-keyed lookups (glass names, coating names, paths)
#   - pythonnet enum-vs-int type traps (sp.Column = 6) -- chain resolves OK;
#     the TypeError fires only at runtime assignment
#   - Chains through your own variables (TheSystem.LDE.GetSurfaceAt) -- we
#     only walk static ZOSAPI/System trees, not inferred interface types

import argparse
import ast
import os
import sys
import winreg
from collections import defaultdict


# ---------------------------------------------------------------------------
# AST: extract dotted attribute chains rooted at ZOSAPI / System / aliases
# ---------------------------------------------------------------------------

ROOTS = ('ZOSAPI', 'System')


def _chain(node):
    """Walk an Attribute/Name node and return ('root', 'part1', ...).
    Returns None if the chain doesn't bottom out at a bare Name
    (e.g. starts from a Call, Subscript, literal)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return tuple(reversed(parts))
    return None


class ChainCollector(ast.NodeVisitor):
    """Collect every (chain, lineno) where chain[0] is ZOSAPI / System or a
    known local alias bound to one. Tracks:
       - from ZOSAPI.X.Y import Z       -> Z -> (ZOSAPI, X, Y, Z)
       - ST = ZOSAPI.Editors.LDE.SurfaceType -> ST -> (ZOSAPI, ...)
    so aliased usage like ST.EvenAsphere still resolves."""

    def __init__(self):
        self.aliases = {}            # local name -> expanded chain
        self.chains = []             # list of (chain, lineno)

    def _resolve(self, chain):
        """Expand chain[0] via the alias table. Returns the chain ready for
        getattr-walking, or None if the chain isn't rooted at a tracked name."""
        if not chain:
            return None
        head = chain[0]
        if head in ROOTS:
            return chain
        if head in self.aliases:
            return self.aliases[head] + chain[1:]
        return None

    def visit_ImportFrom(self, node):
        # from ZOSAPI.X.Y import A, B as C
        if node.module is None:
            return
        parts = tuple(node.module.split('.'))
        if parts[0] not in ROOTS:
            return
        for alias in node.names:
            if alias.name == '*':
                continue                         # cannot track wildcards
            local_name = alias.asname or alias.name
            self.aliases[local_name] = parts + (alias.name,)

    def visit_Assign(self, node):
        # Track simple `name = <chain>` aliases. Only update if RHS resolves
        # to a known root/alias; leave existing alias intact if RHS is opaque
        # (handles things like `ZOSAPI = zos.ZOSAPI` which is effectively a
        # no-op for our purposes -- ZOSAPI is still a ROOT).
        if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            ch = _chain(node.value)
            if ch is not None:
                resolved = self._resolve(ch)
                if resolved is not None and target not in ROOTS:
                    self.aliases[target] = resolved
        self.generic_visit(node)

    def visit_Attribute(self, node):
        # Extract the longest enclosing chain at this node. If it bottoms out
        # at a tracked name, record it and STOP recursing into children
        # (children are prefix sub-chains we'd just duplicate-report). If it
        # doesn't bottom out at a Name (e.g. tool.GetResult(0).Vendor), recurse
        # so inner expressions are still walked.
        ch = _chain(node)
        if ch is not None:
            resolved = self._resolve(ch)
            if resolved is not None:
                self.chains.append((resolved, node.lineno))
            return
        self.generic_visit(node)


def _extract_python_blocks_from_md(path):
    """Yield (start_line, code) tuples for each ```python ... ``` block in path.
    start_line is the 1-based line of the FIRST code line inside the fence."""
    with open(path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    i = 0
    while i < len(lines):
        stripped = lines[i].rstrip('\n').strip()
        # Match ```python, ```py, or ```python {info}
        if stripped == '```python' or stripped == '```py' \
                or stripped.startswith('```python ') or stripped.startswith('```py '):
            block_start = i + 2                       # 1-based line after opener
            j = i + 1
            block_lines = []
            while j < len(lines):
                if lines[j].rstrip('\n').strip() == '```':
                    break
                block_lines.append(lines[j])
                j += 1
            yield block_start, ''.join(block_lines)
            i = j + 1
        else:
            i += 1


def collect_chains(path):
    """Return list of (chain, lineno) for either a .py or a .md file. For
    markdown, line numbers are the original markdown lines. SyntaxError on
    partial / illustrative code blocks is logged and the block skipped."""
    if path.lower().endswith('.md'):
        all_chains = []
        for block_start, code in _extract_python_blocks_from_md(path):
            try:
                tree = ast.parse(code, filename=path)
            except SyntaxError as e:
                print(f"  [skip] {path}:{block_start + (e.lineno or 1) - 1}: "
                      f"partial code block ({e.msg})", file=sys.stderr)
                continue
            collector = ChainCollector()
            collector.visit(tree)
            for ch, ln in collector.chains:
                all_chains.append((ch, block_start + ln - 1))
        return all_chains

    with open(path, 'r', encoding='utf-8') as f:
        source = f.read()
    tree = ast.parse(source, filename=path)
    collector = ChainCollector()
    collector.visit(tree)
    return collector.chains


# ---------------------------------------------------------------------------
# Live ZOSAPI session -- same boilerplate as probe_object_properties.py
# ---------------------------------------------------------------------------

class _Session:
    def __init__(self):
        import clr
        aKey = winreg.OpenKey(winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER),
                              r"Software\Zemax", 0, winreg.KEY_READ)
        zemaxData = winreg.QueryValueEx(aKey, 'ZemaxRoot')
        NetHelper = os.path.join(os.sep, zemaxData[0],
                                 r'ZOS-API\Libraries\ZOSAPI_NetHelper.dll')
        winreg.CloseKey(aKey)
        clr.AddReference(NetHelper)
        import ZOSAPI_NetHelper
        if not ZOSAPI_NetHelper.ZOSAPI_Initializer.Initialize():
            raise RuntimeError("Unable to locate Zemax OpticStudio.")
        zdir = ZOSAPI_NetHelper.ZOSAPI_Initializer.GetZemaxDirectory()
        clr.AddReference(os.path.join(os.sep, zdir, "ZOSAPI.dll"))
        clr.AddReference(os.path.join(os.sep, zdir, "ZOSAPI_Interfaces.dll"))
        import ZOSAPI, System
        self.ZOSAPI = ZOSAPI
        self.System = System
        self.connection = ZOSAPI.ZOSAPI_Connection()
        self.app = self.connection.CreateNewApplication()
        if self.app is None:
            raise RuntimeError("Could not create ZOSAPI application.")
        if not self.app.IsValidLicenseForAPI:
            self.app.CloseApplication()
            raise RuntimeError("License invalid for ZOSAPI use.")

    def close(self):
        if self.app is not None:
            self.app.CloseApplication()
            self.app = None
            self.connection = None


# Members that appear on every .NET Object / Enum / value-type wrapper -- they
# pollute difflib loose matches and the small-type dump fallback. Filter them
# out so suggestions reveal actual enum values and useful namespace contents.
_ENUM_NOISE = frozenset((
    'Equals', 'GetHashCode', 'GetType', 'ToString', 'MemberwiseClone', 'Finalize',
    'CompareTo', 'HasFlag', 'IsDefined', 'GetValues', 'GetName', 'GetNames',
    'GetUnderlyingType', 'Parse', 'TryParse', 'Format', 'ToObject',
    'Overloads', 'value__', 'GetTypeCode', 'ReferenceEquals',
    'op_BitwiseAnd', 'op_BitwiseOr', 'op_ExclusiveOr', 'op_OnesComplement',
    'op_Equality', 'op_Inequality',
))


def _suggest(parent, missing_name):
    """Suggestions for an AttributeError. First tries difflib at a sensible
    cutoff; if nothing matches, retries at a looser cutoff; if still nothing,
    dumps the parent's full public member list for small types (<=40) or just
    the count for large ones. The fallback dump is what lets us discover wrong
    namespace paths and renamed members from a single re-run. .NET Object /
    Enum machinery is filtered out so the suggestions are actually useful."""
    try:
        import difflib
        names = [n for n in dir(parent)
                 if not n.startswith('_') and n not in _ENUM_NOISE]
    except Exception:
        return []
    if not names:
        return []
    close = difflib.get_close_matches(missing_name, names, n=3, cutoff=0.55)
    if close:
        return close
    loose = difflib.get_close_matches(missing_name, names, n=5, cutoff=0.3)
    if loose:
        return [f"<loose: {', '.join(loose)}>"]
    if len(names) <= 40:
        return [f"<no match; members: {', '.join(sorted(names))}>"]
    return [f"<no match; {len(names)} public members>"]


def resolve_chain(session, chain):
    """Walk getattr(session.<root>, chain[1], chain[2], ...).
    Returns (ok, failed_at_index, error_string). On failure, error_string
    includes difflib suggestions from the parent's dir() when helpful."""
    obj = getattr(session, chain[0], None)
    if obj is None:
        return False, 0, f"root namespace not available: {chain[0]}"
    for i, part in enumerate(chain[1:], start=1):
        try:
            nxt = getattr(obj, part)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            suggestions = _suggest(obj, part)
            if suggestions:
                msg += f"  | did you mean: {', '.join(suggestions)}"
            return False, i, msg
        if nxt is None:
            return False, i, "getattr returned None (member missing)"
        obj = nxt
    return True, None, None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Pre-flight check: verify ZOSAPI/System names in a script "
                    "or markdown reference exist in the loaded ZOS-API namespace.")
    parser.add_argument('paths', nargs='*', help='Python (.py) or markdown (.md) file(s) to check')
    parser.add_argument('--audit', action='store_true',
                        help='Audit the whole skill: SKILL.md + references/*.md + '
                             'scripts/*.py (excluding self / test fixtures / diagnostics) '
                             'relative to this script\'s install.')
    parser.add_argument('--show-resolved', action='store_true',
                        help='Print resolved chains too (default: only failures).')
    args = parser.parse_args()

    if args.audit:
        import glob
        skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        audit_paths = [os.path.join(skill_root, 'SKILL.md')]
        audit_paths += sorted(glob.glob(os.path.join(skill_root, 'references', '*.md')))
        for py in sorted(glob.glob(os.path.join(skill_root, 'scripts', '*.py'))):
            base = os.path.basename(py)
            if base in ('check_namespace.py',) or base.startswith('_'):
                continue
            audit_paths.append(py)
        args.paths = audit_paths + args.paths
        print(f"[audit] scanning {len(audit_paths)} skill file(s) under {skill_root}",
              file=sys.stderr)

    if not args.paths:
        parser.error('no paths given (use --audit or pass file paths)')

    all_chains = []                              # list of (path, lineno, chain)
    for path in args.paths:
        if not os.path.isfile(path):
            print(f"[error] {path}: not a file", file=sys.stderr)
            return 2
        for ch, ln in collect_chains(path):
            all_chains.append((path, ln, ch))

    if not all_chains:
        print("No ZOSAPI/System attribute chains found.")
        return 0

    unique_chains = sorted(set(ch for _, _, ch in all_chains))
    print(f"Found {len(all_chains)} attribute access(es), {len(unique_chains)} "
          f"unique chain(s), across {len(args.paths)} file(s).", file=sys.stderr)
    print("Launching Standalone OpticStudio for namespace resolution...", file=sys.stderr)

    session = _Session()
    try:
        results = {ch: resolve_chain(session, ch) for ch in unique_chains}
    finally:
        session.close()

    failures = defaultdict(list)                 # chain -> list of (path, lineno)
    successes = set()
    for path, ln, ch in all_chains:
        ok, _idx, _err = results[ch]
        if ok:
            successes.add(ch)
        else:
            failures[ch].append((path, ln))

    if args.show_resolved:
        for ch in sorted(successes):
            print(f"  OK    {'.'.join(ch)}")

    if failures:
        print(f"\n{len(failures)} unresolved chain(s):\n")
        for ch in sorted(failures):
            ok, idx, err = results[ch]
            dotted = '.'.join(ch)
            failed_part = ch[idx] if idx is not None and idx < len(ch) else '?'
            print(f"  FAIL  {dotted}")
            print(f"        failed at: {failed_part}  ({err})")
            for path, ln in failures[ch]:
                print(f"        used at: {path}:{ln}")
            print()
        return 1

    print(f"\nAll {len(successes)} unique chain(s) resolved.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
