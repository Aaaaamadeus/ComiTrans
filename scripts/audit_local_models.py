"""Audit the exact release file set, including external tensors, without inference."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import package_release


def audit(archive=None):
    import onnx  # Development audit only; never imported by the application.
    from onnx.external_data_helper import _get_all_tensors
    files = package_release.collect_models()
    selected = {path.resolve() for path, _ in files}
    entries, graphs = [], []
    for path, name in files:
        with path.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        entries.append({'path': name, 'bytes': path.stat().st_size, 'sha256': checksum})
        if path.suffix != '.onnx':
            continue
        model = onnx.load_model(path, load_external_data=False)
        external = []
        for tensor in _get_all_tensors(model):
            if tensor.data_location == onnx.TensorProto.EXTERNAL:
                location = dict((entry.key, entry.value) for entry in tensor.external_data)['location']
                weight = (path.parent / location).resolve()
                if weight not in selected:
                    raise ValueError(f'External weight not included in release: {weight}')
                external.append(location)
        def contract(value):
            tensor = value.type.tensor_type
            return {'name': value.name, 'dtype': tensor.elem_type,
                    'shape': [d.dim_value or d.dim_param for d in tensor.shape.dim]}
        graphs.append({'path': name, 'external_data': sorted(set(external)),
                       'inputs': [contract(value) for value in model.graph.input],
                       'outputs': [contract(value) for value in model.graph.output]})
    total = sum(entry['bytes'] for entry in entries)
    result = {'baseline_bytes': package_release.MODEL_BASELINE_BYTES,
              'limit_bytes': package_release.MODEL_LIMIT_BYTES, 'bytes': total,
              'baseline_ratio': total / package_release.MODEL_BASELINE_BYTES,
              'budget_used_ratio': total / package_release.MODEL_LIMIT_BYTES,
              'files': entries, 'graphs': graphs}
    if archive:
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError('Archive CRC verification failed')
            if set(bundle.namelist()) != {entry['path'] for entry in entries}:
                raise ValueError('Archive file set mismatch')
            for entry in entries:
                with bundle.open(entry['path']) as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != entry['sha256']:
                        raise ValueError('Archive digest mismatch: ' + entry['path'])
            result['archive_uncompressed_bytes'] = sum(info.file_size for info in bundle.infolist())
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.archive)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print({key: value for key, value in result.items() if key not in ('files', 'graphs')})
