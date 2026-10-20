"""Thin wrapper around chmseek for the two OpticStudio CHM files.

Handles the boilerplate the agent would otherwise have to repeat each call:
- forces UTF-8 stdio so the Doxygen `*` markers don't crash on Windows cp1252
- accepts shorthand --chm zos / --chm gui (no full Windows path)
- strips the HF Hub auth warning from stderr
- normalises chmseek's two `read` response shapes (`text` vs `chunks[].text`)
- defaults to a compact text format an agent can scan; pass --json for raw

Usage examples:

    # search for a concept (hybrid = semantic + keyword)
    python chmseek_zos.py search "save NSC ray trace to ZRD"

    # exact-symbol search
    python chmseek_zos.py grep "INSCRayTrace"

    # read a result page, with surrounding chunks
    python chmseek_zos.py read --chunk ch_000712 --neighbors 2

    # read a whole page once you've found a good landing spot
    python chmseek_zos.py read --page p_001328

    # search the OpticStudio GUI/concepts help instead of the API help
    python chmseek_zos.py search "Forbes merit function" --chm gui

Pass --json to any command to dump the raw chmseek JSON instead of the
formatted text.

Invoking via `conda run` from another project directory: ALWAYS add
`--no-capture-output`, e.g.

    conda run --no-capture-output -n zemax python chmseek_zos.py read --chunk ch_001664

Plain `conda run` (without that flag) captures this script's stdout and
re-print()s it through conda's own cp1252 stream, which crashes on any
non-ASCII CHM content (µ, λ, °, Doxygen bullets, or the U+FFFD this script
emits via errors='replace'). The crash is inside conda\\cli\\main_run.py, NOT
this script -- our stdout reconfigure() can't control conda's re-encode step.
`--no-capture-output` streams the child's stdout straight to the terminal and
sidesteps it. (If you've `conda activate`d the env instead, this doesn't apply.)
"""

import argparse
import json
import os
import subprocess
import sys

# Force this script's own stdout to UTF-8 so the Doxygen `*` markers in CHM
# content don't crash on Windows cp1252 terminals. (PYTHONIOENCODING handles
# the chmseek subprocess; this handles our own print() calls.)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')


CHM_PATHS = {
    'zos': r'C:\Program Files\Zemax OpticStudio\ZOS-API\Help\ZOS-API.chm',
    'gui': r'C:\Program Files\Zemax OpticStudio\Help\OpticStudio_Help_en.chm',
}


def _run_chmseek(args):
    """Invoke chmseek with UTF-8 stdio and return its parsed JSON, or raise.

    On failure, chmseek writes a structured error to STDOUT as JSON (e.g.
    {"ok": false, "error": {"code": "INVALID_CHUNK_ID", "message": ..., "hints": [...]}})
    and leaves stderr empty. The old code only echoed stderr, so every chmseek
    error (bad chunk/page id, missing CHM, etc.) was silently swallowed and the
    caller saw nothing. We now parse stdout first and surface that error
    regardless of return code.
    """
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    proc = subprocess.run(['chmseek', *args, '--json'],
                          env=env, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')

    payload = None
    if proc.stdout.strip():
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = None

    # chmseek signals failure via returncode AND/OR an {"ok": false} payload.
    is_error = (proc.returncode != 0) or (
        isinstance(payload, dict) and payload.get('ok') is False)

    if is_error:
        if isinstance(payload, dict) and 'error' in payload:
            err = payload['error'] or {}
            code = err.get('code', '')
            msg = err.get('message', '')
            hints = err.get('hints') or []
            sys.stderr.write(f'chmseek error{f" [{code}]" if code else ""}: {msg}\n')
            for h in hints:
                sys.stderr.write(f'  hint: {h}\n')
        elif proc.stderr.strip():
            sys.stderr.write(proc.stderr)
        elif proc.stdout.strip():
            # non-JSON failure body — show it rather than exit silently
            sys.stderr.write(f'chmseek failed (rc={proc.returncode}); '
                             f'stdout (first 500): {proc.stdout[:500]}\n')
        else:
            sys.stderr.write(f'chmseek failed (rc={proc.returncode}) with no output\n')
        raise SystemExit(proc.returncode or 2)

    if payload is not None:
        return payload

    # returncode 0 but unparseable stdout
    sys.stderr.write('chmseek output was not valid JSON\n')
    sys.stderr.write(f'stdout (first 500): {proc.stdout[:500]}\n')
    sys.stderr.write(f'stderr: {proc.stderr}\n')
    raise SystemExit(2)


def _resolve_chm(name):
    """Accept 'zos', 'gui', or a literal path. Return the CHM path."""
    if name in CHM_PATHS:
        return CHM_PATHS[name]
    if not os.path.isfile(name):
        sys.stderr.write(f"CHM not found: {name!r}. Use --chm zos or --chm gui, "
                         f"or pass a full path. Known shortcuts:\n")
        for k, v in CHM_PATHS.items():
            sys.stderr.write(f"  {k} -> {v}\n")
        raise SystemExit(2)
    return name


def _format_search_results(payload, chm_name, max_results):
    # chm_name is the --chm shorthand (e.g. 'zos' / 'gui') or a literal path.
    # It MUST be carried into the suggested READ command: chunk/page IDs are
    # per-CHM, so a READ that omits --chm runs against the default ('zos') and
    # fails with INVALID_CHUNK_ID when the result came from a different CHM.
    chm_flag = f" --chm {chm_name}" if chm_name else ""
    out = []
    for r in payload.get('results', [])[:max_results]:
        score = r.get('score') or 0.0
        sem = r.get('semantic_score') or 0.0
        kw = r.get('keyword_score') or 0.0
        out.append(f"[{r['rank']}] page={r['page_id']} chunk={r['chunk_id']}  "
                   f"{r.get('title', '')}")
        out.append(f"    score={score:.3f} (semantic={sem:.3f}, keyword={kw:.3f})")
        snippet = (r.get('snippet') or r.get('text_preview') or '').strip()
        snippet = ' '.join(snippet.split())  # collapse whitespace
        if len(snippet) > 240:
            snippet = snippet[:237] + '...'
        out.append(f"    {snippet}")
        out.append(f"    READ: python {os.path.basename(__file__)} read "
                   f"--chunk {r['chunk_id']}{chm_flag} --neighbors 2")
        out.append('')
    if not out:
        out.append('(no results)')
    return '\n'.join(out)


def _extract_text(payload):
    """chmseek read returns either {'text': str} or {'chunks': [{'text': str},...]}."""
    if 'text' in payload and isinstance(payload['text'], str):
        return payload['text']
    chunks = payload.get('chunks') or []
    return '\n'.join(c.get('text', '') for c in chunks)


def cmd_search(args):
    chm = _resolve_chm(args.chm)
    payload = _run_chmseek(['search', chm, args.query, '--mode', args.mode])
    if args.json:
        print(json.dumps(payload, indent=2))
        return
    # Pass the --chm shorthand (args.chm), NOT the resolved path, so the
    # suggested READ commands carry --chm and target the right CHM.
    print(_format_search_results(payload, args.chm, args.limit))


def cmd_grep(args):
    chm = _resolve_chm(args.chm)
    payload = _run_chmseek(['grep', chm, args.term])
    if args.json:
        print(json.dumps(payload, indent=2))
        return
    print(_format_search_results(payload, args.chm, args.limit))


def cmd_read(args):
    chm = _resolve_chm(args.chm)
    cmd = ['read', chm]
    if args.chunk:
        cmd += ['--chunk-id', args.chunk]
        if args.neighbors:
            cmd += ['--neighbors', str(args.neighbors)]
    elif args.page:
        cmd += ['--page-id', args.page]
    else:
        sys.stderr.write('read needs --chunk <id> or --page <id>\n')
        raise SystemExit(2)
    payload = _run_chmseek(cmd)
    if args.json:
        print(json.dumps(payload, indent=2))
        return
    title = payload.get('title') or payload.get('page_title') or ''
    src = payload.get('source_path') or payload.get('source_uri') or ''
    print(f"=== {args.chunk or args.page}: {title} ===")
    if src:
        print(f"Source: {src}")
    print()
    text = _extract_text(payload)
    print(text if text else '(no text extracted)')


def cmd_toc(args):
    chm = _resolve_chm(args.chm)
    payload = _run_chmseek(['toc', chm])
    if args.json:
        print(json.dumps(payload, indent=2))
        return
    # toc payload structure varies; just dump it readably
    print(json.dumps(payload, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--chm', default='zos',
                        help="'zos' (ZOS-API.chm), 'gui' (OpticStudio_Help_en.chm), "
                             "or a full path to a CHM file. Default: zos")
    common.add_argument('--json', action='store_true',
                        help='Emit raw chmseek JSON instead of formatted text.')

    sp = sub.add_parser('search', parents=[common],
                        help='Hybrid (semantic + keyword) search.')
    sp.add_argument('query')
    sp.add_argument('--mode', default='hybrid',
                    choices=['hybrid', 'semantic', 'keyword'])
    sp.add_argument('--limit', type=int, default=8)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser('grep', parents=[common],
                        help='Exact-keyword search (no embeddings).')
    sp.add_argument('term')
    sp.add_argument('--limit', type=int, default=10)
    sp.set_defaults(func=cmd_grep)

    sp = sub.add_parser('read', parents=[common],
                        help='Read a chunk (with neighbors) or a whole page.')
    sp.add_argument('--chunk', help='Chunk id (e.g. ch_000712)')
    sp.add_argument('--page', help='Page id (e.g. p_001328)')
    sp.add_argument('--neighbors', type=int, default=2,
                    help='Surrounding chunks to include (chunk reads only). Default: 2')
    sp.set_defaults(func=cmd_read)

    sp = sub.add_parser('toc', parents=[common],
                        help='Dump the table of contents.')
    sp.set_defaults(func=cmd_toc)

    args = p.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
