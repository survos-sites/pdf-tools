#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
uv venv work/analysis-venv
uv pip install --python work/analysis-venv/bin/python -r requirements-analysis.txt
mkdir -p work/models
curl -fL --retry 2 -o work/models/layout_model_new.onnx.download \
  https://huggingface.co/NealCaren/american-stories-onnx/resolve/2558a02376901ad18afd296f88e5e4554fa1b36b/layout_model_new.onnx
printf '%s  %s\n' '045b2e5588e53c700490730244bdc3e8ff21e903aff1c2af9b169dcdb1d9155e' 'work/models/layout_model_new.onnx.download' | shasum -a 256 -c -
mv work/models/layout_model_new.onnx.download work/models/layout_model_new.onnx
printf '%s\n' 'Set PDFTOOLS_ANALYSIS_PYTHON to the absolute work/analysis-venv/bin/python path.'
