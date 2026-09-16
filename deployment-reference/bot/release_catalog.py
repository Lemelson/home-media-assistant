"""Presentation only: no resolution or size silently removes a release."""
import re

PAGE_SIZE=8

def dimension_quality(width,height):
    if height<=2160 and 3800<=width<=4096:return 'uhd'
    if height<=1080 and 1900<=width<=1920:return 'fhd'
    if height<=720 and 1200<=width<=1280:return 'hd'
    return {2160:'uhd',1080:'fhd',720:'hd'}.get(height,'other')

def quality_key(row):
    height=row.get('details',{}).get('height')
    if height:
        variants=row.get('details',{}).get('resolutions') or [[row.get('details',{}).get('width',0),height]]
        keys={dimension_quality(w,h) for w,h in variants}
        return next(iter(keys)) if len(keys)==1 else 'other'
    title=row.get('title','')
    if re.search(r'\b(?:2160[pi]|4[KК]|3840[xх×]2160|4096[xх×]2160)\b',title,re.I):return 'uhd'
    if re.search(r'\b(?:1080[pi]|Full[ -]?HD|1920[xх×]1080)\b',title,re.I):return 'fhd'
    if re.search(r'\b(?:720[pi]|1280[xх×]720)\b',title,re.I):return 'hd'
    if not re.search(r'\b(?:\d{3,4}[pi]|\d{3,5}[xх×]\d{3,5}|[248][KК])\b',title,re.I) and re.search(r'\bUHD\b',title,re.I):return 'uhd'
    return 'other'

def quality_label(row):
    key=quality_key(row)
    if key!='other':return {'uhd':'✨ 4К','fhd':'🎞 Full HD','hd':'📺 HD'}[key]
    height=row.get('details',{}).get('height')
    if len(row.get('details',{}).get('resolutions',[]))>1:return '🎬 Разные разрешения'
    if height:return '🎬 '+('8К' if height==4320 else str(height)+'p')
    token=re.search(r'\b(?:\d{3,4}[pi]|[248][KК]|\d{3,5}[xх×]\d{3,5})\b',row.get('title',''),re.I)
    return '🎬 '+(token.group() if token else 'Видео')

def size_icon(row):
    size=int(row.get('size') or 0)/1024**3
    return '📦' if size>=30 else ('🪶' if 0<size<8 else '💾')

def catalog_page(state):
    rows=state['releases'];quality=state.get('quality_filter','all')
    indices=[i for i,r in enumerate(rows) if quality=='all' or quality_key(r)==quality]
    if state.get('sort')=='size':indices.sort(key=lambda i:int(rows[i].get('size') or 0))
    pages=max(1,(len(indices)+PAGE_SIZE-1)//PAGE_SIZE)
    page=max(0,min(int(state.get('page',0)),pages-1))
    return indices[page*PAGE_SIZE:(page+1)*PAGE_SIZE],page,pages
