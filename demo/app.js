'use strict';
const $ = id => document.getElementById(id);
let file, viewer, generation = 0;
const headers = () => $('token').value ? {Authorization: `Bearer ${$('token').value}`} : {};
const status = (message, error=false) => { $('status').textContent=message; $('status').classList.toggle('error',error); };
async function api(path, options={}) {
  const response = await fetch(path,{...options,headers:{...headers(),...options.headers}});
  if (!response.ok) { const data=await response.json().catch(()=>({detail:response.statusText})); throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail)); }
  return response.json();
}
async function openDocument() {
  $('open').disabled=true; status('Opening source… The first request downloads and validates the PDF.');
  try {
    const source=$('source').value.trim();
    file=await api(/^[a-f0-9]{32}$/.test(source)?`/v1/files/${source}`:'/v1/files',/^[a-f0-9]{32}$/.test(source)?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:source})});
    $('reader').hidden=false; $('title').textContent=file.metadata.title||'Archive document';
    $('stats').textContent=`${file.pages.toLocaleString()} pages · ${(file.bytes/1048576).toFixed(1)} MB`;
    $('page').max=file.pages; $('page').value=1; $('count').textContent=`/ ${file.pages}`;
    history.replaceState(null,'',`?file=${file.id}`); await showPage();
  } catch(error) {status(error.message,true);} finally {$('open').disabled=false;}
}
async function showPage() {
  const page=Number($('page').value), ticket=++generation;
  if(!Number.isInteger(page)||page<1||page>file.pages){status('Choose a page within this document.',true);return;}
  status(`Loading page ${page}…`); $('text').textContent=''; $('hits').textContent='';
  try {
    if(!window.OpenSeadragon) throw Error('OpenSeadragon could not load. Check access to cdn.jsdelivr.net and reload.');
    if(viewer) viewer.destroy();
    viewer=OpenSeadragon({id:'viewer',prefixUrl:'https://cdn.jsdelivr.net/npm/openseadragon@5.0.1/build/openseadragon/images/',
      tileSources:`/iiif/3/${file.id}~${page}/info.json`,loadTilesWithAjax:true,ajaxHeaders:headers(),showNavigator:true});
    viewer.addHandler('open-failed',event=>status(`Image could not open: ${event.message}`,true));
    viewer.addHandler('tile-load-failed',()=>status('An image tile could not load. Try a lower zoom or check service logs.',true));
    const text=await api(`/v1/files/${file.id}/pages/${page}/text`);
    if(ticket!==generation)return;
    $('text').textContent=text.text||'This page has no extractable text layer. OCR is a separate operation.';
    status(`Page ${page} ready · existing text only`);
  }catch(error){if(ticket===generation)status(error.message,true);}
}
$('source-form').onsubmit=event=>{event.preventDefault();openDocument();};
$('page-form').onsubmit=event=>{event.preventDefault();showPage();};
$('prev').onclick=()=>{if(Number($('page').value)>1){$('page').value--;showPage();}};
$('next').onclick=()=>{if(Number($('page').value)<file.pages){$('page').value++;showPage();}};
$('example').onclick=()=>{$('source').value='https://www.marxists.org/history/ussr/culture/soviet-life/full-issues/1961/sim_soviet-life_1961-02_2.pdf';openDocument();};
$('search-form').onsubmit=async event=>{
 event.preventDefault(); if(!file||!viewer)return;
 const ticket=generation;
 try{const result=await api(`/v1/files/${file.id}/pages/${$('page').value}/search?q=${encodeURIComponent($('query').value)}`);
 if(ticket!==generation)return; viewer.clearOverlays(); const item=viewer.world.getItemAt(0); if(!item)throw Error('Wait for the page image to finish loading.');
 const imageSize=item.getContentSize();
 for(const hit of result.hits){const [x0,y0,x1,y1]=hit.bboxNormalized;const element=document.createElement('div');element.className='hit';viewer.addOverlay({element,location:item.imageToViewportRectangle(x0*imageSize.x,y0*imageSize.y,(x1-x0)*imageSize.x,(y1-y0)*imageSize.y)});}
 $('hits').textContent=`${result.hits.length} matches on this page`;
 }catch(error){status(error.message,true);}
};
async function download(path,name){try{const data=await api(path);const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){status(error.message,true);}}
$('words').onclick=()=>download(`/v1/files/${file.id}/pages/${$('page').value}/words`,'words.json');
$('manifest').onclick=()=>download(`/iiif/3/${file.id}/manifest.json`,'manifest.json');
const initial=new URLSearchParams(location.search).get('file');if(initial){$('source').value=initial;openDocument();}

fetch('fixtures.json').then(r=>{if(!r.ok)throw Error('Reference list unavailable');return r.json();}).then(data=>{
 for(const fixture of data.files){const option=document.createElement('option');option.value=fixture.url;option.textContent=`${fixture.name} · ${fixture.pages.toLocaleString()} pages`; $('fixture').append(option);}
}).catch(error=>status(error.message,true));
$('load-fixture').onclick=()=>{if($('fixture').value){$('source').value=$('fixture').value;openDocument();}};
