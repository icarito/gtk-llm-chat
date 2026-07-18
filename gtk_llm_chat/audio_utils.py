import mimetypes
import re

AUDIO_MIME_TYPES = {
    'audio/ogg': ['ogg', 'oga', 'ogv', 'ogx', 'opus'],
    'audio/opus': ['opus'],
    'audio/mp4': ['m4a'],
    'audio/x-m4a': ['m4a'],
    'audio/mpeg': ['mp3'],
    'audio/wav': ['wav'],
    'audio/x-wav': ['wav'],
    'audio/wave': ['wav'],
}

AUDIO_MIME_BY_EXT = {}
for mime_type, exts in AUDIO_MIME_TYPES.items():
    for ext in exts:
        AUDIO_MIME_BY_EXT.setdefault(ext, []).append(mime_type)

RECORDING_MIME = 'audio/ogg'
RECORDING_EXT = '.ogg'

PLAYBACK_MIMES = frozenset({
    'audio/ogg', 'audio/opus',
    'audio/mp4', 'audio/x-m4a', 'audio/mpeg',
    'audio/wav', 'audio/x-wav', 'audio/wave',
})

AUDIO_EXT_RE = re.compile(
    r'\.(ogg|oga|opus|m4a|mp3|wav)(\?|#|$)', re.IGNORECASE)


def is_audio_mime(mime_type: str | None) -> bool:
    if not mime_type:
        return False
    return mime_type.lower().split(';')[0].strip() in PLAYBACK_MIMES


def is_audio_url(url: str | None) -> bool:
    if not url:
        return False
    return bool(AUDIO_EXT_RE.search(url))


def audio_mime_for_file(path: str | None) -> str | None:
    if not path:
        return None
    mime, _ = mimetypes.guess_type(path)
    if mime and is_audio_mime(mime):
        return mime
    ext = path.rsplit('.', 1)[-1].lower() if '.' in path else ''
    candidates = AUDIO_MIME_BY_EXT.get(ext, [])
    return candidates[0] if candidates else None


def is_playable_mime(mime_type: str | None) -> bool:
    return is_audio_mime(mime_type)
