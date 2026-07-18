"""Application-scoped, user-facing lifecycle for the shared XMPP session."""

from gi.repository import GObject


class XmppLifecycle(GObject.Object):
    """Translate transport states into stable phases consumed by every window."""

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_LAST, None, (str, str)),
    }

    STARTING = 'starting'
    LOADING_ACCOUNT = 'loading-account'
    CONNECTING = 'connecting'
    SYNCING_ROSTER = 'syncing-roster'
    ONLINE = 'online'
    RETRYING = 'retrying'
    OFFLINE_BY_USER = 'offline-by-user'
    UNCONFIGURED = 'unconfigured'
    ERROR = 'error'

    def __init__(self):
        super().__init__()
        self._phase = self.STARTING
        self._detail = ''
        self._offline_requested = False

    @property
    def phase(self):
        return self._phase

    @property
    def detail(self):
        return self._detail

    def set_phase(self, phase, detail=''):
        detail = str(detail or '')
        if phase == self._phase and detail == self._detail:
            return
        self._phase = phase
        self._detail = detail
        self.emit('changed', phase, detail)

    def account_loading(self):
        self._offline_requested = False
        self.set_phase(self.LOADING_ACCOUNT)

    def account_missing(self):
        self.set_phase(self.UNCONFIGURED)

    def user_disconnected(self):
        self._offline_requested = True
        self.set_phase(self.OFFLINE_BY_USER)

    def user_reconnecting(self):
        self._offline_requested = False
        self.set_phase(self.CONNECTING)

    def session_error(self, detail):
        if not self._offline_requested:
            self.set_phase(self.ERROR, detail)

    def observe_session_state(self, state):
        if self._offline_requested and state == 'disconnected':
            self.set_phase(self.OFFLINE_BY_USER)
            return
        # Authentication/configuration failures emit session-error immediately
        # before the transport's final disconnected state. Preserve the useful
        # error instead of replacing it with the generic retrying phase.
        if state == 'disconnected' and self._phase == self.ERROR:
            return
        phases = {
            'connecting': self.CONNECTING,
            'syncing-roster': self.SYNCING_ROSTER,
            'connected': self.ONLINE,
            'reconnecting': self.RETRYING,
            'disconnected': self.RETRYING,
        }
        phase = phases.get(state)
        if phase is not None:
            self.set_phase(phase)
