"""Offline, reproducible excerpt scoring; no inference or paid calls."""
import argparse
import json
from pathlib import Path
import statistics
import unicodedata


def normalize(text):
    return ' '.join(unicodedata.normalize('NFKC',text).lower().split())


def distance(a,b):
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        row=[i]
        for j,y in enumerate(b,1):row.append(min(row[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
        previous=row
    return previous[-1]


def inside(word,box):
    x,y,w,h=word['box'];a,b,c,d=box
    return a<=x+w/2<=a+c and b<=y+h/2<=b+d


def main():
    p=argparse.ArgumentParser();p.add_argument('--results',type=Path,default=Path('work/pilot/results'))
    p.add_argument('--gold',type=Path,default=Path('benchmarks/newspaper/gold.json'));p.add_argument('--output',type=Path,default=Path('work/pilot/scores.json'));args=p.parse_args()
    rows=[]
    for z in json.loads(args.gold.read_text())['zones']:
        ref=normalize(z['text'])
        for mode in ['alto','alto-layout','tesseract','region-ocr']:
            r=json.loads((args.results/f'p{z["page"]:02}-{mode}.json').read_text())
            words=[w for b in r['blocks'] for l in b['lines'] for w in l['words'] if inside(w,z['box'])]
            hyp=normalize(' '.join(w['text'] for w in words))
            # Spatial ordering diagnostic: compare native word order with top-to-bottom line bands.
            spatial=sorted(words,key=lambda w:(round((w['box'][1]+w['box'][3]/2)/20),w['box'][0]))
            shyp=normalize(' '.join(w['text'] for w in spatial))
            rows.append({'page':z['page'],'kind':z['kind'],'mode':mode,'reference':ref,'hypothesis':hyp,
                         'characters':len(ref),'words':len(ref.split()),'characterEdits':distance(ref,hyp),
                         'wordEdits':distance(ref.split(),hyp.split()),'cer':distance(ref,hyp)/len(ref),
                         'wer':distance(ref.split(),hyp.split())/len(ref.split()),
                         'spatialSortCER':distance(ref,shyp)/len(ref)})
    bench=json.loads((args.results/'benchmark.json').read_text());summary={}
    for mode in ['alto','alto-layout','tesseract','region-ocr']:
        rs=[r for r in rows if r['mode']==mode];bs=[r for r in bench if r['mode']==mode and 'error' not in r]
        avg=statistics.mean(r['wallSeconds'] for r in bs)
        summary[mode]={'cer':sum(r['characterEdits'] for r in rs)/sum(r['characters'] for r in rs),
                       'wer':sum(r['wordEdits'] for r in rs)/sum(r['words'] for r in rs),
                       'meanWallSeconds':avg,'medianWallSeconds':statistics.median(r['wallSeconds'] for r in bs),
                       'maxConservativePeakGiB':max(r['conservativePeakBytes'] for r in bs)/1024**3,
                       'batchHours1822':avg*1822/3600,'eightHourPagesAt50PercentDuty':14400/avg,
                       'unassignedBlocks':sum(r['unassigned'] for r in bs),'blocks':sum(r['blocks'] for r in bs),
                       'emptyTextPages':sum(r['words']==0 for r in bs)}
    args.output.write_text(json.dumps({'normalization':'NFKC lowercase whitespace; punctuation and printed line-break hyphens retained; no spell correction. CER/WER use native engine order and include missed text/duplicates.',
                                    'summary':summary,'excerpts':rows},indent=2,ensure_ascii=False))
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
