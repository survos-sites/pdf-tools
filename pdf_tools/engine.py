"""Executed only in the dedicated child process, never a FastAPI worker thread."""
import io
import math
import re

import pymupdf as fitz
from PIL import Image


def rectangle(page, value, units='pt', native_dpi=300):
    bounds = page.rect
    if value == 'full':
        return bounds
    if value == 'square':
        side = min(bounds.width, bounds.height)
        return fitz.Rect((bounds.width-side)/2, (bounds.height-side)/2,
                         (bounds.width+side)/2, (bounds.height+side)/2)
    percent = value.startswith('pct:')
    values = [float(x) for x in value.removeprefix('pct:').split(',')]
    if len(values) != 4 or not all(math.isfinite(x) for x in values):
        raise ValueError('Region must contain four finite numbers')
    x, y, w, h = values
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise ValueError('Region must have nonnegative origin and positive size')
    if percent:
        x, w = x*bounds.width/100, w*bounds.width/100
        y, h = y*bounds.height/100, h*bounds.height/100
    elif units == 'px':
        # Map the declared (rounded) IIIF canvas exactly onto PDF points.
        cw, ch = canvas(page, native_dpi)
        x, w = x*bounds.width/cw, w*bounds.width/cw
        y, h = y*bounds.height/ch, h*bounds.height/ch
    clip = fitz.Rect(x, y, x+w, y+h) & bounds
    if clip.is_empty:
        raise ValueError('Region lies outside page')
    return clip


def canvas(page, dpi):
    return math.ceil(page.rect.width*dpi/72), math.ceil(page.rect.height*dpi/72)


def dimensions(size, w, h):
    if size == 'max':
        ow, oh = w, h
    elif size.startswith('pct:'):
        scale = float(size[4:])/100
        ow, oh = w*scale, h*scale
    elif size.startswith('!'):
        mw, mh = [float(x) for x in size[1:].split(',')]
        scale = min(mw/w, mh/h)
        ow, oh = w*scale, h*scale
    else:
        a, b = size.split(',')
        if not a and not b:
            raise ValueError('Empty size')
        ow = float(a) if a else w*float(b)/h
        oh = float(b) if b else h*float(a)/w
    if not all(math.isfinite(x) and x > 0 for x in (ow, oh)):
        raise ValueError('Size must be positive and finite')
    return max(1, math.ceil(ow-1e-8)), max(1, math.ceil(oh-1e-8))


def execute(path, operation, params):
    with fitz.open(path) as doc:
        if not doc.is_pdf or doc.needs_pass or not doc.page_count:
            raise ValueError('Source must be an unencrypted nonempty PDF')
        if operation == 'info':
            metadata = doc.metadata
            match = re.search(r'archive\.org/details/([^\s/]+)', metadata.get('keywords', ''))
            return {'pages': doc.page_count, 'metadata': metadata,
                    'iaIdentifier': match.group(1) if match else None}
        if operation == 'geometries':
            return [dict(zip(('width','height'), canvas(p, params['nativeDpi']))) for p in doc]
        if operation == 'toc':
            return doc.get_toc()
        number = params['page']
        if number < 1 or number > doc.page_count:
            raise IndexError(f'Page {number} not found (PDF has {doc.page_count} pages)')
        page = doc[number-1]  # Public API is 1-based; PyMuPDF is 0-based.
        if operation in ('page', 'words', 'text', 'search'):
            # Report boxes in displayed page coordinates, including PDF rotation.
            def box(rect):
                r = fitz.Rect(rect) * page.rotation_matrix
                return {'bboxPt': list(r), 'bboxNormalized': [r.x0/page.rect.width, r.y0/page.rect.height,
                                                            r.x1/page.rect.width, r.y1/page.rect.height]}
            if operation == 'text':
                return {'page': number, 'text': page.get_text().strip()}
            if operation == 'search':
                return {'page': number, 'hits': [box(r) for r in page.search_for(params['q'])]}
            words = [{**box(w[:4]), 'text': w[4], 'block': w[5], 'line': w[6], 'n': w[7]}
                     for w in page.get_text('words')]
            if operation == 'words':
                return {'page': number, 'words': words}
            cw, ch = canvas(page, params['nativeDpi'])
            return {'page': number, 'widthPt': page.rect.width, 'heightPt': page.rect.height,
                    'width': cw, 'height': ch, 'nativeDpi': params['nativeDpi'],
                    'rotation': page.rotation, 'hasTextLayer': bool(words), 'wordCount': len(words)}
        if operation == 'geometry':
            w, h = canvas(page, params['nativeDpi'])
            return {'width': w, 'height': h}
        if operation == 'render':
            clip = rectangle(page, params.get('region', 'full'), params.get('units', 'pt'), params['nativeDpi'])
            cw, ch = canvas(page, params['nativeDpi'])
            base_w = cw * clip.width/page.rect.width
            base_h = ch * clip.height/page.rect.height
            if params.get('units', 'pt') == 'pt':
                base_w, base_h = clip.width*params['nativeDpi']/72, clip.height*params['nativeDpi']/72
            w, h = dimensions(params['size'], base_w, base_h)
            if w*h > params['maxPixels'] or max(w, h) > 16000:
                raise ValueError('Requested image exceeds pixel limit')
            fmt = params['format']
            if fmt not in ('png', 'jpg', 'webp') or params['quality'] not in ('default', 'gray'):
                raise ValueError('Unsupported image format or quality')
            pix = page.get_pixmap(matrix=fitz.Matrix(w/clip.width, h/clip.height), clip=clip,
                                  colorspace=fitz.csGRAY if params['quality']=='gray' else fitz.csRGB, alpha=False)
            image = Image.frombytes('L' if pix.n == 1 else 'RGB', (pix.width, pix.height), pix.samples)
            if image.size != (w, h):
                image = image.resize((w,h), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format={'jpg':'JPEG','png':'PNG','webp':'WEBP'}[fmt])
            return output.getvalue()
        raise ValueError('Unknown operation')
