import pydbus
from gi.repository import GLib

class ChatService:
    """Servicio D-Bus para manejar solicitudes de chat."""

    dbus = {
        'org.fuentelibre.ChatService': {
            'methods': {
                'OpenConversation': ('s', ''),  # Recibe un string (CID) y no retorna nada
            },
            'signals': {},
            'properties': {},
        }
    }

    def __init__(self, app):
        self.app = app

    def OpenConversation(self, cid):
        """Abrir una nueva conversación dado un CID."""
        self.app.OpenConversation(cid)

if __name__ == "__main__":
    from chat_application import LLMChatApplication

    app = LLMChatApplication()
    bus = pydbus.SessionBus()
    service = ChatService(app)
    bus.publish("org.fuentelibre.ChatService", service)

    loop = GLib.MainLoop()
    loop.run()
