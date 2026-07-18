import os
import time
import tempfile

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst  # noqa: E402

from .audio_utils import RECORDING_EXT  # noqa: E402
from .debug_utils import debug_print  # noqa: E402

Gst.init(None)


class VoiceRecorderError(Exception):
    pass


class VoiceRecorder:
    def __init__(self):
        self._pipeline: Gst.Pipeline | None = None
        self._file_path: str | None = None
        self._start_time: float = 0.0
        self._is_recording: bool = False
        self._error: str | None = None

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def error(self) -> str | None:
        return self._error

    def start(self, output_path: str | None = None) -> str:
        if self._is_recording:
            raise VoiceRecorderError("Already recording")
        self._error = None

        if output_path:
            self._file_path = output_path
        else:
            fd, self._file_path = tempfile.mkstemp(
                suffix=RECORDING_EXT, prefix='voice_')
            os.close(fd)

        pipeline_str = (
            'autoaudiosrc ! audioconvert ! audioresample ! '
            'opusenc ! oggmux ! '
            f'filesink location="{self._file_path}"'
        )
        self._pipeline = Gst.parse_launch(pipeline_str)

        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self._on_bus_message)

        ret = self._pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            self._cleanup_pipeline()
            self._error = "Microphone or encoder unavailable"
            raise VoiceRecorderError(self._error)

        self._start_time = time.monotonic()
        self._is_recording = True
        debug_print(f"[VoiceRecorder] started: {self._file_path}")
        return self._file_path

    def stop(self, discard: bool = False) -> tuple:
        if not self._is_recording:
            return None, 0.0
        self._is_recording = False
        duration = max(0.1, time.monotonic() - self._start_time)

        if self._pipeline:
            self._pipeline.send_event(Gst.Event.new_eos())
            self._pipeline.set_state(Gst.State.NULL)
        self._cleanup_pipeline()

        if discard:
            self._delete_file()
            debug_print("[VoiceRecorder] discarded")
            return None, 0.0

        debug_print(f"[VoiceRecorder] stopped: {duration:.1f}s")
        return self._file_path, duration

    def cancel(self):
        return self.stop(discard=True)

    def _on_bus_message(self, _bus, message):
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            self._error = f"{err}: {debug}"
            debug_print(f"[VoiceRecorder] error: {self._error}")
            self._is_recording = False
        elif t == Gst.MessageType.EOS:
            debug_print("[VoiceRecorder] EOS received")

    def _cleanup_pipeline(self):
        if self._pipeline:
            bus = self._pipeline.get_bus()
            bus.remove_signal_watch()
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None

    def _delete_file(self):
        if self._file_path and os.path.exists(self._file_path):
            try:
                os.remove(self._file_path)
            except OSError:
                pass
        self._file_path = None
