"""
One-time script: convert PersonalPortfolio seizure .pth models to .onnx
Run: .venv\Scripts\python convert_to_onnx.py
"""
import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent))

import torch
import numpy as np
from pathlib import Path

# Import architecture builders from the existing inference module
from projects.inference.seizure_eeg import (
    _build_cnn_simple,
    _build_cnn_transformer,
    _build_gru_attention_from_state_dict,
    _build_fusion_classifier,
)

MODELS_DIR = Path('media/projects/models')
OUT_DIR = MODELS_DIR  # save alongside .pth files


def _export(model, args, out_path, input_names, output_names, dynamic_axes=None):
    torch.onnx.export(
        model, args, str(out_path),
        input_names=input_names,
        output_names=output_names,
        dynamic_axes=dynamic_axes,
        opset_version=17,
        dynamo=False,
    )
    print(f'Saved: {out_path}  ({out_path.stat().st_size // 1024} KB)')


def export_cnn(pth_name, onnx_name, builder_fn, dummy, input_names, dynamic_axes=None):
    path = MODELS_DIR / pth_name
    if not path.exists():
        print(f'SKIP: {pth_name} not found')
        return
    sd = torch.load(str(path), map_location='cpu', weights_only=True)
    if builder_fn == _build_gru_attention_from_state_dict:
        model = builder_fn(sd)
    else:
        model = builder_fn()
    model.load_state_dict(sd)
    model.eval()
    _export(model, dummy, OUT_DIR / onnx_name, input_names, ['logits'], dynamic_axes)


if __name__ == '__main__':
    print('Exporting cnn_transformer model...')
    export_cnn(
        'cnn_transformer_best_model90.22.pth', 'cnn_transformer.onnx',
        _build_cnn_simple,
        torch.zeros(1, 19, 65, 33),
        input_names=['x'],
        dynamic_axes={'x': {0: 'batch', 3: 'time_steps'}, 'logits': {0: 'batch'}},
    )

    print('Exporting gru_attention model...')
    export_cnn(
        'gru_self_best_model79_15.pth', 'gru_attention.onnx',
        _build_gru_attention_from_state_dict,
        torch.zeros(1, 10, 19, 200),
        input_names=['x'],
        dynamic_axes={'x': {0: 'batch'}, 'logits': {0: 'batch'}},
    )

    print('Exporting fusion model...')
    export_cnn(
        'fusion_best_model1.pth', 'fusion.onnx',
        _build_fusion_classifier,
        (torch.zeros(1, 65, 19, 33), torch.zeros(1, 10, 19, 200)),
        input_names=['cnnx', 'lstmx'],
        dynamic_axes={
            'cnnx':   {0: 'batch', 3: 'time_steps'},
            'lstmx':  {0: 'batch'},
            'logits': {0: 'batch'},
        },
    )

    print('Done.')
