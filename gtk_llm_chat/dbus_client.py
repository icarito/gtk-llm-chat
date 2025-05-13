"""
Cliente D-Bus común para los applets de GTK-LLM-Chat
Proporciona funcionalidad D-Bus compartida para tk_llm_applet.py y gtk_llm_applet.py
"""
import os
import sys
import subprocess

# Intentar importar dbus-next con manejo de errores
try:
    import dbus_next
except ImportError:
    print("Warning: dbus_next not available, D-Bus communication will not work")
    dbus_next = None


def open_conversation_dbus(conversation_id=None):
    """
    Envía un mensaje D-Bus para abrir una conversación.
    Si D-Bus falla, usa el método de respaldo.
    
    Args:
        conversation_id: ID de la conversación a abrir, o None para una nueva
        
    Returns:
        bool: True si se envió con éxito, False si se usó el método de respaldo
    """
    # Si dbus_next no está disponible, usar fallback inmediatamente
    if dbus_next is None:
        print("D-Bus no disponible, usando método alternativo")
        fallback_open_conversation(conversation_id)
        return False
        
    try:
        # Conectar al bus de sesión usando dbus-next
        from dbus_next.aio import MessageBus
        from dbus_next import Message, MessageType
        import asyncio

        # Función asíncrona para enviar el mensaje
        async def send_dbus_message():
            # Conexión al bus de sesión
            bus = await MessageBus().connect()
            
            # Crear un mensaje D-Bus
            message = Message(
                destination='org.fuentelibre.ChatApplication',
                path='/org/fuentelibre/ChatApplication',
                interface='org.fuentelibre.ChatApplication',
                member='OpenConversation',
                signature='s',
                body=[conversation_id or ""]
            )
            
            # Enviar el mensaje y esperar respuesta
            reply = await bus.call(message)
            await bus.disconnect()
            return reply

        # Ejecutar la función asíncrona
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # Si no hay event loop activo, crear uno nuevo
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        reply = loop.run_until_complete(send_dbus_message())
        
        # Verificar si la respuesta indica error
        if reply and getattr(reply, 'message_type', None) == MessageType.ERROR:
            print(f"Error al abrir la conversación: {reply.body}")
            fallback_open_conversation(conversation_id)
            return False
        
        return True
    except Exception as e:
        print(f"Error al comunicarse con D-Bus: {e}")
        # Usar el método de fallback si falla D-Bus
        fallback_open_conversation(conversation_id)
        return False


def fallback_open_conversation(conversation_id=None):
    """
    Método alternativo para abrir conversación si falla D-Bus.
    Inicia la aplicación directamente usando subprocess.
    
    Args:
        conversation_id: ID de la conversación a abrir, o None para una nueva
    """
    args = ['llm', 'gtk-chat']
    if conversation_id:
        args += ['--cid', str(conversation_id)]
    if getattr(sys, 'frozen', False):
        base = os.path.abspath(os.path.dirname(sys.argv[0]))
        executable = "gtk-llm-chat"
        if sys.platform == "win32":
            executable += ".exe"
        elif sys.platform == "linux" and os.environ.get('_PYI_ARCHIVE_FILE'):
            base = os.path.dirname(os.environ.get('_PYI_ARCHIVE_FILE'))
            if os.environ.get('APPIMAGE'):
                executable = 'AppRun'
        args = [os.path.join(base, executable)] + args[2:]
    
    try:
        subprocess.Popen(args)
    except Exception as e:
        print(f"Error al iniciar la aplicación: {e}")
