"""Read only selected ALTO members from an existing capture; not an ingestion system."""
import argparse
from pathlib import Path
import re
import tarfile

p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('--output',type=Path,default=Path('work/pilot/alto'));p.add_argument('--pages',default='1,2,3,4,12,19,21,25');a=p.parse_args()
wanted=set(map(int,a.pages.split(',')));a.output.mkdir(parents=True,exist_ok=True)
with tarfile.open(a.archive,'r|bz2') as archive:
    for member in archive:
        match=re.fullmatch(r'sn85059732/1914/11/29/ed-1/seq-(\d+)/ocr.xml',member.name)
        if not match or int(match[1]) not in wanted:continue
        if not member.isfile() or member.size>20*1024**2:raise ValueError('Unexpected ALTO member')
        number=int(match[1]);(a.output/f'{number}.xml').write_bytes(archive.extractfile(member).read());wanted.remove(number)
        if not wanted:break
if wanted:raise ValueError(f'Missing pages: {wanted}')
