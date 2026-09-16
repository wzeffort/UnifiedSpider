"""Finalize an already packed clean staging directory, without repacking Python."""
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

stage = Path(sys.argv[1]).resolve()
assert stage.parent == Path(__file__).resolve().parent.parent / 'releases'
assert not any((stage / 'app' / name).exists() for name in ('data', 'sessions', 'browser_profiles'))
manifest = {p.relative_to(stage).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in stage.rglob('*') if p.is_file() and p.name != 'manifest.json'}
(stage / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
output = stage.parent / ('WebCollector-Ready-' + time.strftime('%Y%m%d-%H%M%S') + '.zip')
with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=2) as archive:
    for p in stage.rglob('*'):
        if p.is_file():
            archive.write(p, 'WebCollector/' + p.relative_to(stage).as_posix(),
                          compress_type=zipfile.ZIP_STORED if p.name == 'runtime.zip' else zipfile.ZIP_DEFLATED)
digest = hashlib.sha256(output.read_bytes()).hexdigest()
output.with_suffix('.sha256.txt').write_text(digest + '  ' + output.name + '\n', encoding='ascii')
print(json.dumps({'archive': str(output), 'bytes': output.stat().st_size, 'sha256': digest}), flush=True)
