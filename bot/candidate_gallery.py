"""Send candidate photos with bounded recovery from opaque remote image errors."""
from bot.rendering import plain_text


def send_candidate_gallery(dialog, chat_id, candidates, lines, markup, galleries, *,
                           per_candidate_limit=None, alternatives=None):
    """Return a rich message or None for the caller's normal text fallback.

    Keep candidate identity attached to every photo. Only after the first send
    fails, optionally obtain alternative galleries once and try their second and
    third images. There are at most four Telegram sends including smaller-gallery
    recovery. With no alternatives, the single-film three-photo rescue is unchanged.
    """
    def select(source, offset=0):
        photos=[]
        for index in range(len(candidates)):
            gallery=source[index] if index<len(source) else []
            urls=[url for url in gallery if isinstance(url,str) and url.startswith('https://')]
            if not urls and offset:
                original=galleries[index] if index<len(galleries) else []
                urls=[url for url in original if isinstance(url,str) and url.startswith('https://')]
            if not urls:
                continue
            if offset:
                urls=urls[offset:]+urls[:offset] if offset<len(urls) else urls
            if per_candidate_limit is not None:
                urls=urls[:max(0,per_candidate_limit)]
            photos.extend((index,url) for url in urls)
        return photos

    primary=select(galleries)
    if not primary:
        return None

    def attempts():
        yield primary
        if alternatives is not None:
            try:
                expanded=alternatives()
                if isinstance(expanded,(list,tuple)):
                    yield select(expanded,1)
                    yield select(expanded,2)
            except Exception:
                pass
        if len(primary)>1:
            for index in range(min(3,len(primary))):
                yield primary[:index]+primary[index+1:]

    seen=set()
    for attempt in attempts():
        signature=tuple(attempt)
        if not attempt or signature in seen:
            continue
        if len(seen)>=4:
            break
        seen.add(signature)
        blocks=[{'type':'paragraph','text':plain_text(lines[0])}]
        for index in range(len(candidates)):
            blocks.append({'type':'paragraph','text':{'type':'bold','text':plain_text(lines[index+1])}})
            blocks.extend({'type':'photo','photo':{'type':'photo','media':url}}
                          for candidate_index,url in attempt if candidate_index==index)
        blocks.append({'type':'paragraph','text':plain_text(lines[-1])})
        try:
            return dialog.telegram.call('sendRichMessage',chat_id=chat_id,
                rich_message={'blocks':blocks},reply_markup=markup)
        except Exception:
            continue
    return None
