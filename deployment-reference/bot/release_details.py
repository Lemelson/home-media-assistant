"""Parse only release technical data; never substitute an audio/overall bitrate."""
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, parse_qs


def topic_url(row):
    value=row.get('infoUrl','')
    try:
        url=urlsplit(value)
        ids=parse_qs(url.query).get('t',[])
        if url.scheme=='https' and url.hostname in ('tracker.example.invalid','www.tracker.example.invalid') and url.path=='/forum/viewtopic.php' and len(ids)==1 and ids[0].isdigit():
            return 'https://tracker.example.invalid/forum/viewtopic.php?t='+ids[0]
    except (ValueError,TypeError):pass
    return None


class FirstPost(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth=0;self.active=False;self.done=False;self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if self.done:return
        if not self.active and 'post_body' in attrs.get('class','').split():
            self.active=True;self.depth=1;return
        if not self.active:return
        if tag=='div':self.depth+=1
        if tag in ('script','style'):self.skip+=1
        if tag in ('br','p','div','tr','li'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if not self.active:return
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
        if tag=='div':
            self.depth-=1
            if self.depth==0:self.active=False;self.done=True
        if tag in ('p','div','tr','li'):self.parts.append('\n')
    def handle_data(self,data):
        if self.active and not self.skip:self.parts.append(data)


def post_text(html):
    parser=FirstPost();parser.feed(html)
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip())


RATE=re.compile(r'(?<![\w.])(\d+(?:[ \u00a0]\d{3})*(?:[.,]\d+)?)\s*(Мбит/с|Кбит/с|Mb/s|kb/s|Mbps|kbps|Mbit/s|Kbit/s)',re.I)

def parse_details(text):
    result={};section=None;video=[];audio=[]
    text=re.sub(r'(?i)(?<!^)(?=\b(?:Аудио|Audio|Звук)\s*(?:#?\d+)?\s*[:/])','\n',text)
    for raw in text.replace('\xa0',' ').splitlines():
        line=raw.strip()
        if re.match(r'^(?:Видео(?:\s*#?\d+)?|Video(?:\s*#?\d+)?)(?:\s*[:/]|\s*$)',line,re.I):section='video'
        elif re.match(r'^(?:Аудио|Audio|Звук)\b',line,re.I):section='audio'
        elif re.match(r'^(?:General|Общее|Text|Menu|Субтитры|Меню|Скриншоты|Описание|Релиз|Перевод)(?:\b|:)',line,re.I):section=None
        if section=='video':video.append(line)
        elif section=='audio':audio.append(line)
        if re.match(r'^(?:Язык|Перевод|Озвучка)\s*:',line,re.I):audio.append(line)
    v='\n'.join(video);a='\n'.join(audio)
    dimensions=re.search(r'(?<!\d)(\d{3,5})\s*[xх×*]\s*(\d{3,5})(?!\d)',v,re.I)
    if dimensions:
        result.update(width=int(dimensions[1]),height=int(dimensions[2]))
        variants=list(dict.fromkeys((int(w),int(h)) for w,h in re.findall(r'(?<!\d)(\d{3,5})\s*[xх×*]\s*(\d{3,5})(?!\d)',v,re.I)))
        if len(variants)>1:result['resolutions']=[list(pair) for pair in variants]
    else:
        for name,pattern in [('width',r'(?:Width|Ширина)\s*:\s*([\d ]+)'),('height',r'(?:Height|Высота)\s*:\s*([\d ]+)')]:
            match=re.search(pattern,v,re.I)
            if match:result[name]=int(match[1].replace(' ',''))
    rates=RATE.findall(v)
    if rates:
        number,unit=rates[0];rate=float(number.replace(' ','').replace(',','.'))
        if unit.casefold().startswith(('k','к')):rate/=1000
        if 0<rate<1000:result['video_mbps']=round(rate,3)
    codec=re.search(r'\b(?:HEVC|AVC|H[. ]?26[45]|x26[45]|MPEG[ -]?2|AV1|VP9|XviD|DivX|VC-1)\b',v,re.I)
    if codec:result['video_codec']=codec.group()
    languages=[]
    for pattern,label in [(r'\b(?:русский|русская|russian|rus)\b','Русский'),(r'\b(?:английский|английская|english|eng)\b','Английский'),(r'\b(?:украинский|українська|ukrainian|ukr)\b','Украинский'),(r'\b(?:японский|japanese|jpn)\b','Японский'),(r'\b(?:корейский|korean|kor)\b','Корейский'),(r'\b(?:испанский|spanish|spa)\b','Испанский'),(r'\b(?:немецкий|german|deu|ger)\b','Немецкий'),(r'\b(?:французский|french|fra|fre)\b','Французский')]:
        if re.search(pattern,a,re.I):languages.append(label)
    if languages:result['languages']=languages
    return result
