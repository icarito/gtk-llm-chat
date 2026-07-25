import pytest
from gtk_llm_chat.audio_utils import (
    is_audio_mime, is_audio_url, audio_mime_for_file, is_playable_mime,
    AUDIO_MIME_TYPES, RECORDING_MIME, RECORDING_EXT,
)


class TestAudioMimeRecognition:

    @pytest.mark.parametrize("mime,expected", [
        ('audio/ogg', True),
        ('audio/opus', True),
        ('audio/mp4', True),
        ('audio/x-m4a', True),
        ('audio/mpeg', True),
        ('audio/wav', True),
        ('audio/x-wav', True),
        ('audio/wave', True),
        ('audio/ogg; codecs=opus', True),
        ('Audio/OGG', True),
        ('image/png', False),
        ('text/plain', False),
        ('application/octet-stream', False),
        (None, False),
    ])
    def test_is_audio_mime(self, mime, expected):
        assert is_audio_mime(mime) == expected

    def test_is_playable_mime_alias(self):
        assert is_playable_mime('audio/ogg') is True
        assert is_playable_mime('image/png') is False


class TestAudioUrlRecognition:

    @pytest.mark.parametrize("url,expected", [
        ('https://example.com/voice.ogg', True),
        ('https://example.com/audio.opus', True),
        ('https://example.com/rec.m4a?token=xyz', True),
        ('https://example.com/file.mp3', True),
        ('https://example.com/sound.wav', True),
        ('https://example.com/voice.OGG', True),
        ('https://example.com/image.png', False),
        ('https://example.com/file.txt', False),
        ('https://example.com/nofile', False),
        (None, False),
    ])
    def test_is_audio_url(self, url, expected):
        assert is_audio_url(url) == expected


class TestAudioMimeForFile:

    def test_ogg_extension(self):
        assert audio_mime_for_file('/tmp/voice.ogg') == 'audio/ogg'

    def test_opus_extension(self):
        result = audio_mime_for_file('/tmp/voice.opus')
        assert result in ('audio/opus', 'audio/ogg')

    def test_m4a_extension(self):
        result = audio_mime_for_file('/tmp/voice.m4a')
        assert result in ('audio/mp4', 'audio/x-m4a')

    def test_mp3_extension(self):
        assert audio_mime_for_file('/tmp/voice.mp3') == 'audio/mpeg'

    def test_wav_extension(self):
        result = audio_mime_for_file('/tmp/voice.wav')
        assert result in ('audio/wav', 'audio/x-wav', 'audio/wave')

    def test_non_audio(self):
        assert audio_mime_for_file('/tmp/image.png') is None

    def test_no_extension(self):
        assert audio_mime_for_file('/tmp/nofile') is None

    def test_none_path(self):
        assert audio_mime_for_file(None) is None


class TestConstants:

    def test_recording_mime_is_playable(self):
        assert is_playable_mime(RECORDING_MIME)

    def test_all_defined_mimes_are_playable(self):
        for mime_type, exts in AUDIO_MIME_TYPES.items():
            assert is_playable_mime(mime_type), f"{mime_type} should be playable"

    def test_recording_ext_is_ogg(self):
        assert RECORDING_EXT == '.ogg'
