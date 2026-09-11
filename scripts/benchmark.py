"""Opt-in real downloads: register each fixture, inspect/render its last page twice."""
import argparse
import json
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:5001')
parser.add_argument('--name', help='One filename; omit to run all eight (~182 MB total)')
parser.add_argument('--output', default='work/benchmark.json')
args = parser.parse_args()
fixtures = json.loads((Path(__file__).resolve().parents[1]/'demo/fixtures.json').read_text())['files']
results = []
with httpx.Client(base_url=args.base_url, timeout=660) as client:
    for fixture in fixtures:
        if args.name and fixture['name'] != args.name:
            continue
        start = time.monotonic()
        response = client.post('/v1/files', json={'url':fixture['url'], 'sha256':fixture['sha256']})
        response.raise_for_status()
        info = response.json()
        registration = time.monotonic()-start
        assert info['bytes'] == fixture['bytes'], f"Fixture size changed: {fixture['name']}"
        timings = []
        for _ in range(2):
            start = time.monotonic()
            image = client.get(f"/v1/files/{info['id']}/pages/{info['pages']}/image.png?width=1000")
            image.raise_for_status()
            assert image.content.startswith(b'\x89PNG')
            timings.append(round(time.monotonic()-start,3))
        words = client.get(f"/v1/files/{info['id']}/pages/{info['pages']}/words")
        words.raise_for_status()
        row = {**fixture, 'fileId':info['id'],'sha256':info['sha256'],'pages':info['pages'],
               'registerSeconds':round(registration,3),'renderSeconds':timings,
               'lastPageWords':len(words.json()['words'])}
        results.append(row)
        print(json.dumps(row), flush=True)
path=Path(args.output)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(results,indent=2)+'\n')
