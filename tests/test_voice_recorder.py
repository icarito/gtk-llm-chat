import os
import pytest
from gtk_llm_chat.voice_recorder import VoiceRecorder, VoiceRecorderError
from gtk_llm_chat.audio_utils import RECORDING_EXT


class TestVoiceRecorderCore:
    def test_start_stop_produces_file(self):
        recorder = VoiceRecorder()
        path = recorder.start()
        assert os.path.exists(path)
        assert path.endswith(RECORDING_EXT)
        file_path, duration = recorder.stop()
        assert file_path == path
        assert duration > 0.0
        assert os.path.exists(path)
        os.remove(path)

    def test_start_twice_raises(self):
        recorder = VoiceRecorder()
        recorder.start()
        with pytest.raises(VoiceRecorderError):
            recorder.start()
        recorder.stop()

    def test_cancel_deletes_file(self):
        recorder = VoiceRecorder()
        path = recorder.start()
        recorder.cancel()
        assert not os.path.exists(path)
        assert recorder.is_recording is False

    def test_discard_stop_deletes_file(self):
        recorder = VoiceRecorder()
        path = recorder.start()
        file_path, _duration = recorder.stop(discard=True)
        assert file_path is None
        assert not os.path.exists(path)

    def test_is_recording_state(self):
        recorder = VoiceRecorder()
        assert not recorder.is_recording
        recorder.start()
        assert recorder.is_recording
        recorder.stop()
        assert not recorder.is_recording

    def test_stop_when_not_recording(self):
        recorder = VoiceRecorder()
        path, duration = recorder.stop()
        assert path is None
        assert duration == 0.0

    def test_no_simulation_no_transcript(self):
        recorder = VoiceRecorder()
        path = recorder.start()
        import time
        time.sleep(0.3)
        file_path, _duration = recorder.stop()
        assert file_path is not None
        assert os.path.getsize(path) > 0
        with open(path, 'rb') as f:
            header = f.read(4)
        assert header == b'OggS'
        os.remove(path)

    def test_error_propagated(self):
        recorder = VoiceRecorder()
        assert recorder.error is None
        recorder.start()
        assert recorder.error is None
        recorder.stop()
        os.remove(recorder._file_path)
