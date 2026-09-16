"""Small safe subset of Telegram HTML, with balanced tags and no attributes."""
from html import escape, unescape
from html.parser import HTMLParser

class _TelegramHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output=[]
        self.stack=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('b','i','blockquote') and not (tag=='blockquote' and tag in self.stack):
            self.output.append('<'+tag+'>'); self.stack.append(tag)
    def handle_endtag(self,tag):
        if tag in self.stack:
            while self.stack:
                current=self.stack.pop(); self.output.append('</'+current+'>')
                if current==tag:break
    def handle_data(self,data): self.output.append(escape(data,quote=False))

def telegram_html(value,limit=3000):
    parser=_TelegramHTML()
    parser.feed(str(value)[:limit]); parser.close()
    while parser.stack: parser.output.append('</'+parser.stack.pop()+'>')
    return ''.join(parser.output)

def plain_text(value):
    parser=_TelegramHTML(); parser.feed(str(value)); parser.close()
    return unescape(''.join(part for part in parser.output if not part.startswith('<')))
