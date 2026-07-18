import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib  # noqa: E402

Gst.init(None)

PLAY_STATE_PLAYING = 'playing'
PLAY_STATE_PAUSED = 'paused'
PLAY_STATE_STOPPED = 'stopped'
PLAY_STATE_ERROR = 'error'


class AudioPlayer:
    def __init__(self):
        self._pipeline: Gst.Pipeline | None = None
        self._state: str = PLAY_STATE_STOPPED
        self._error: str | None = None
        self._duration: float = 0.0
        self._position: float = 0.0
        self._update_callback: callable | None = None
        self._update_id: int | None = None

    @property
    def state(self) -> str:
        return self._state

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def duration(self) -> float:
        return self._duration

    @property
    def position(self) -> float:
        return self._position

    def set_update_callback(self, callback):
        self._update_callback = callback

    def load(self, url_or_path: str):
        self._cleanup()
        self._state = PLAY_STATE_STOPPED
        self._error = None
        try:
            pipeline_str = (
                f'uridecodebin uri="{url_or_path}" ! '
                'audioconvert ! audioresample ! autoaudiosink'
            )
            self._pipeline = Gst.parse_launch(pipeline_str)
        except Exception as exc:
            self._error = str(exc)
            self._state = PLAY_STATE_ERROR
            self._notify()
            return

        bus = self._pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message', self._on_bus_message)
        self._pipeline.set_state(Gst.State.PAUSED)

    def play(self):
        if not self._pipeline:
            return
        self._pipeline.set_state(Gst.State.PLAYING)
        self._state = PLAY_STATE_PLAYING
        if not self._update_id:
            self._update_id = GLib.timeout_add(100, self._poll_position)
        self._notify()

    def pause(self):
        if not self._pipeline:
            return
        self._pipeline.set_state(Gst.State.PAUSED)
        self._state = PLAY_STATE_PAUSED
        self._stop_polling()
        self._notify()

    def stop(self):
        self._cleanup()
        self._state = PLAY_STATE_STOPPED
        self._position = 0.0
        self._duration = 0.0
        self._notify()

    def _on_bus_message(self, _bus, message):
        t = message.type
        if t == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            self._error = f"{err}: {debug}"
            self._state = PLAY_STATE_ERROR
            self._stop_polling()
            self._notify()
        elif t == Gst.MessageType.EOS:
            self._state = PLAY_STATE_STOPPED
            self._position = self._duration
            self._stop_polling()
            self._notify()
        elif t == Gst.MessageType.STATE_CHANGED:
            if self._pipeline and self._duration == 0.0:
                ok, dur = self._pipeline.query_duration(Gst.Format.TIME)
                if ok:
                    self._duration = dur / Gst.SECOND

    def _poll_position(self) -> bool:
        if not self._pipeline or self._state != PLAY_STATE_PLAYING:
            self._update_id = None
            return GLib.SOURCE_REMOVE
        ok, pos = self._pipeline.query_position(Gst.Format.TIME)
        if ok:
            self._position = pos / Gst.SECOND
            self._notify()
        return GLib.SOURCE_CONTINUE

    def _stop_polling(self):
        if self._update_id:
            GLib.source_remove(self._update_id)
            self._update_id = None

    def _notify(self):
        if self._update_callback:
            self._update_callback(self._state, self._position,
                                  self._duration, self._error)

    def _cleanup(self):
        self._stop_polling()
        if self._pipeline:
            bus = self._pipeline.get_bus()
            bus.remove_signal_watch()
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
        self._state = PLAY_STATE_STOPPED
