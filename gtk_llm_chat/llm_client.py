import gettext
_ = gettext.gettext

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import GObject, GLib
import llm


class LLMClient(GObject.Object):
    """
    Cliente para interactuar con la API python-llm usando conversaciones
    y streaming, integrado con el bucle principal de GLib/GTK.
    """
    __gsignals__ = {
        # Emite cada token de respuesta del stream
        'response': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # Emite cuando ocurre un error durante la interacción con la API
        'error': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # Emite cuando una solicitud de prompt ha finalizado
        # El booleano indica si finalizó con éxito (True) o no (False)
        'finished': (GObject.SignalFlags.RUN_LAST, None, (bool,))
    }

    def __init__(self, config=None):
        GObject.Object.__init__(self)
        self.config = config or {}
        self.model = None
        self.conversation = None
        self._is_generating_flag = False
        self._stream_iterator = None
        self._idle_source_id = None  # Para poder remover el idle_add

        try:
            model_id = self.config.get('model') or llm.get_default_model()
            print(_(f"{model_id}"))
            self.model = llm.get_model(model_id)
            print(_(f"LLMClient: Using model {self.model.model_id}"))
            self.conversation = self.model.conversation()
        except llm.UnknownModelError as e:
            print(_(f"LLMClient: Error - Unknown model: {e}"))
            # Emitir error aquí podría ser problemático si la UI no está lista
            # Podríamos necesitar un estado 'error_en_init' o lanzar excepción
            raise e  # Re-lanzar por ahora
        except Exception as e:
            print(_(f"LLMClient: Unexpected error in init: {e}"))
            raise e  # Re-lanzar por ahora

    def send_message(self, prompt: str):
        """
        Envía un prompt a la conversación actual y procesa
        la respuesta en stream.
        """
        if self._is_generating_flag:
            self.emit('error', "Ya se está generando una respuesta.")
            return

        if not self.conversation:
            self.emit('error', "La conversación no está inicializada.")
            return

        self._is_generating_flag = True

        # Limpiar estado anterior si es necesario
        if self._idle_source_id:
            GLib.source_remove(self._idle_source_id)
            self._idle_source_id = None
        self._stream_iterator = None

        try:
            print(_(f"LLMClient: Sending prompt: {prompt[:50]}..."))
            # Preparar argumentos para prompt
            prompt_args = {}
            if self.config.get('system'):
                prompt_args['system'] = self.config['system']
            if self.config.get('temperature'):
                # Asegurarse que sea float
                try:
                    temp_val = float(self.config['temperature'])
                    prompt_args['temperature'] = temp_val
                except ValueError:
                    print(_("LLMClient: Ignoring invalid temperature:"),
                          self.config['temperature'])

            # TODO: Añadir manejo de otras opciones/parámetros si es necesario

            # Obtener la respuesta (generador)
            response = self.conversation.prompt(prompt, **prompt_args)

            # Configurar callback para cuando termine
            response.on_done(self._callback_done)

            # Iniciar procesamiento del stream en el idle loop
            self._stream_iterator = iter(response)
            self._idle_source_id = GLib.idle_add(self._process_stream)

        except Exception as e:
            print(_(f"LLMClient: Error sending prompt: {e}"))
            self.emit('error', f"Error al enviar prompt: {e}")
            self._is_generating_flag = False
            self.emit('finished', False)  # Indicar finalización fallida

    def _process_stream(self):
        """
        Función llamada por GLib.idle_add para procesar el stream.
        """
        if not self._is_generating_flag or not self._stream_iterator:
            self._idle_source_id = None  # Asegurar que no se llame de nuevo
            return GLib.SOURCE_REMOVE  # Detener el idle_add

        try:
            chunk = next(self._stream_iterator)
            if chunk:
                # print(chunk, end="", flush=True) # Debug
                self.emit('response', chunk)
            return GLib.SOURCE_CONTINUE  # Continuar llamando

        except StopIteration:
            # El stream terminó normalmente, on_done se encargará
            print(_("LLMClient: Stream finished (StopIteration)"))
            self._idle_source_id = None
            return GLib.SOURCE_REMOVE

        except Exception as e:
            print(_(f"\nLLMClient: Error during streaming: {e}"))
            self.emit('error', f"Error durante el streaming: {e}")
            self._is_generating_flag = False
            # No emitir 'finished' aquí, dejar que on_done lo haga
            self._idle_source_id = None
            return GLib.SOURCE_REMOVE

    def _callback_done(self, response):
        """
        Callback ejecutado por response.on_done() cuando la respuesta finaliza.
        """
        print(_("LLMClient: Response completed (on_done)."))
        # Verificar si hubo error durante el stream
        # (aunque _process_stream ya lo emitió)
        # Podríamos verificar response.error si existiera,
        # o basarnos en _is_generating_flag
        # Si aún está True, no hubo error en _process_stream
        success = self._is_generating_flag
        self._is_generating_flag = False
        self._stream_iterator = None  # Limpiar iterador
        # Asegurar que se remueva si StopIteration no lo hizo
        if self._idle_source_id:
            GLib.source_remove(self._idle_source_id)
            self._idle_source_id = None

        # Emitir señal de finalización
        # Usar idle_add para asegurar que se emita desde el hilo principal,
        # aunque on_done probablemente ya lo haga. Por seguridad:
        GLib.idle_add(self.emit, 'finished', success)

        # Opcional: Imprimir uso de tokens si es útil
        try:
            usage = response.usage()
            print(_(f"LLMClient: Token usage: {usage}"))
        except Exception as e:
            print(_(f"LLMClient: Could not get token usage: {e}"))

    def cancel(self):
        """
        Intenta detener el procesamiento del stream actual.
        Nota: No detiene la generación en el servidor.
        """
        print(_("LLMClient: Cancel request received."))
        if self._is_generating_flag:
            self._is_generating_flag = False
            # El flag detendrá la emisión de 'response' en _process_stream
            # _callback_done se ejecutará eventualmente
            # y emitirá finished(False)
            # Si queremos una señal inmediata, podríamos emitir algo aquí,
            # pero 'finished' parece más apropiado para indicar el final.
            if self._idle_source_id:
                GLib.source_remove(self._idle_source_id)
                self._idle_source_id = None
            # Forzar emisión de finished(False) inmediatamente tras cancelar?
            # GLib.idle_add(self.emit, 'finished', False)  # Considerar esto

    def get_model_id(self):
        """Retorna el ID del modelo cargado."""
        return self.model.model_id if self.model else None

    def get_conversation_id(self):
        """Retorna el ID de la conversación actual si existe."""
        return self.conversation.id if self.conversation else None

    def load_history(self, history_entries):
        """Carga el historial previo en el objeto conversation."""
        # Asegurarse de que la conversación y el modelo estén inicializados
        if not self.conversation or not self.model:
            print(_("LLMClient: Error - Attempting to load history without "
                  "initialized conversation or model."))
            return
        # Ayuda para el type checker
        current_model = self.model
        current_conversation = self.conversation

        print(_(f"LLMClient: Loading {len(history_entries)} history entries..."))
        # Limpiar respuestas existentes si las hubiera
        # (aunque no debería haberlas)
        current_conversation.responses.clear()

        # Variable para mantener el último prompt_obj para la respuesta
        # del asistente
        last_prompt_obj = None

        for entry in history_entries:
            user_prompt = entry.get('prompt')
            assistant_response = entry.get('response')

            if user_prompt:
                # Crear objeto Prompt para la entrada del usuario
                last_prompt_obj = llm.Prompt(user_prompt, current_model)
                # Crear un objeto Response "falso" para representar la entrada
                # del usuario. Necesitamos asignar los atributos mínimos.
                resp_user = llm.Response(
                    last_prompt_obj, current_model, stream=False,
                    conversation=current_conversation
                )
                resp_user._prompt_json = {'prompt': user_prompt}  # Mínimo
                resp_user._done = True
                # Sin texto de respuesta para el prompt del usuario
                resp_user._chunks = []
                current_conversation.responses.append(resp_user)

            if assistant_response and last_prompt_obj:
                # Crear objeto Response para la respuesta del asistente,
                # usando el prompt anterior
                resp_assistant = llm.Response(
                    last_prompt_obj, current_model, stream=False,
                    conversation=current_conversation
                )
                # Mínimo
                resp_assistant._prompt_json = {
                    'prompt': last_prompt_obj.prompt
                }
                resp_assistant._done = True
                # ¡Aquí va la respuesta!
                resp_assistant._chunks = [assistant_response]
                current_conversation.responses.append(resp_assistant)
            elif assistant_response and not last_prompt_obj:
                # Esto no debería ocurrir si el historial está bien formado
                print(_("LLMClient: Warning - Assistant response without "
                      "previous user prompt in history."))

        print(_("LLMClient: History loaded. Total responses in conversation: "
                + f"{len(current_conversation.responses)}"))


# Registrar el tipo GObject para que las señales funcionen correctamente
GObject.type_register(LLMClient)
