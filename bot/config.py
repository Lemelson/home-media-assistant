"""Validate public installation settings without logging their values."""
from urllib.parse import urlsplit


def settings(env):
    def numeric(name, optional=False):
        value=env.get(name,'')
        if optional and not value:return None
        try: result=int(value)
        except (TypeError,ValueError): raise ValueError(name+' must be a numeric Telegram user ID') from None
        if not 0<result<2**63:raise ValueError(name+' is out of range')
        return result
    if not env.get('TELEGRAM_BOT_TOKEN'):raise ValueError('TELEGRAM_BOT_TOKEN is required')
    if len(env.get('MEDIA_AGENT_TOKEN',''))<32:raise ValueError('MEDIA_AGENT_TOKEN must contain at least 32 characters')
    owner=numeric('OWNER_TELEGRAM_ID'); member=numeric('MEMBER_TELEGRAM_ID',True)
    if owner==member:raise ValueError('Owner and member must have different IDs')
    base=env.get('MEDIA_AGENT_URL','http://127.0.0.1:18742').rstrip('/')
    p=urlsplit(base)
    if p.scheme!='http' or p.hostname not in ('127.0.0.1','localhost','::1') or p.username or p.password or p.path or p.query or p.fragment:
        raise ValueError('MEDIA_AGENT_URL must be a loopback HTTP endpoint; use an SSH tunnel for remote access')
    return {'owner_id':owner,'member_id':member,'agent_url':base,
            'images':env.get('ENABLE_REMOTE_IMAGES')=='1','voice':env.get('ENABLE_VOICE')=='1'}
