"""Speech transcription using the existing OpenRouter account."""
import base64

from bot.providers import ProviderError, request_json


class OpenRouterTranscriber:
    def __init__(self, key, telegram, model='openai/whisper-large-v3-turbo'):
        self.key = key
        self.telegram = telegram
        self.model = model

    def __call__(self, voice):
        limit = 20 * 1024 * 1024
        if voice.get('file_size', 0) > limit or voice.get('duration', 0) > 600:
            raise ProviderError('voice_too_long')
        try:
            raw = self.telegram.download_file(voice['file_id'], limit)
        except Exception:
            raise ProviderError('transcription_failed') from None
        if len(raw) > limit:
            raise ProviderError('voice_too_long')
        try:
            result = request_json(
                'https://openrouter.ai/api/v1/audio/transcriptions',
                {'model': self.model, 'input_audio': {
                    'data': base64.b64encode(raw).decode('ascii'), 'format': 'ogg'},
                 'language': 'ru', 'response_format': 'json'},
                {'Authorization': 'Bearer ' + self.key}, timeout=60)
            text = result.get('text') if isinstance(result, dict) else None
            if not isinstance(text, str) or not text.strip():
                raise ValueError('invalid transcription')
            return text.strip()
        except Exception:
            raise ProviderError('transcription_failed') from None
