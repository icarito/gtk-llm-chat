import gettext
_ = gettext.gettext

import gi
from gi.repository import GObject, GLib
import llm
import threading
import time
from db_operations import ChatHistory  # Import ChatHistory

class LLMClient(GObject.Object):
    """
    Simplified client for interacting with the python-llm API synchronously in a thread.
    """
    __gsignals__ = {
        # Emits each response token from the stream
        'response': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # Emits when an error occurs during API interaction
        'error': (GObject.SignalFlags.RUN_LAST, None, (str,)),
        # Emits when a prompt request has finished
        # The boolean indicates success (True) or failure (False)
        'finished': (GObject.SignalFlags.RUN_LAST, None, (bool,)),
        'model-loaded': (GObject.SignalFlags.RUN_LAST, None, (str,)),
    }

    def __init__(self, config=None, chat_history=None):
        GObject.Object.__init__(self)
        self.config = config or {}
        self.model = None
        self.conversation = None
        self._is_generating_flag = False
        self._stream_thread = None
        self._init_error = None
        self.chat_history = None # Remove chat_history from here

        # Load the model in the background
        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        """Loads the model synchronously."""
        try:
            model_id = self.config.get('model') or llm.get_default_model()
            print(_(f"LLMClient: Attempting to load model: {model_id}"))
            self.model = llm.get_model(model_id)
            print(_(f"LLMClient: Using model {self.model.model_id}"))
            self.conversation = self.model.conversation()
            GLib.idle_add(self.emit, 'model-loaded', self.model.model_id)
        except llm.UnknownModelError as e:
            print(_(f"LLMClient: Error - Unknown model: {e}"))
            self._init_error = str(e)
            GLib.idle_add(self.emit, 'error', f"Modelo desconocido: {e}")
        except Exception as e:
            print(_(f"LLMClient: Unexpected error in init: {e}"))
            self._init_error = str(e)
            GLib.idle_add(self.emit, 'error', f"Error inesperado al inicializar: {e}")

    def send_message(self, prompt: str):
        """Sends a prompt to the current conversation in a thread."""
        if self._is_generating_flag:
            GLib.idle_add(self.emit, 'error', "Ya se está generando una respuesta.")
            return

        if self._init_error or not self.model:
            GLib.idle_add(self.emit, 'error', f"Error al inicializar el modelo: {self._init_error or 'Modelo no disponible'}")
            return

        self._is_generating_flag = True

        # Start the stream processing in a separate thread
        self._stream_thread = threading.Thread(target=self._process_stream, args=(prompt,), daemon=True)
        self._stream_thread.start()

    def _process_stream(self, prompt: str):
        """Processes the response stream synchronously."""
        success = False
        full_response = ""
        chat_history = ChatHistory() # Create a new ChatHistory object
        try:
            print(_(f"LLMClient: Sending prompt: {prompt[:50]}..."))
            prompt_args = {}
            if self.config.get('system'):
                prompt_args['system'] = self.config['system']
            if self.config.get('temperature'):
                try:
                    temp_val = float(self.config['temperature'])
                    prompt_args['temperature'] = temp_val
                except ValueError:
                    print(_("LLMClient: Ignoring invalid temperature:"), self.config['temperature'])

            response = self.conversation.prompt(prompt, **prompt_args)

            print(_("LLMClient: Starting stream processing..."))
            for chunk in response:
                if not self._is_generating_flag:
                    print(_("LLMClient: Stream processing cancelled externally."))
                    break
                if chunk:
                    full_response += chunk
                    GLib.idle_add(self.emit, 'response', chunk)
            success = True
            print(_("LLMClient: Stream finished normally."))

        except Exception as e:
            print(_(f"LLMClient: Error during streaming: {e}"))
            GLib.idle_add(self.emit, 'error', f"Error durante el streaming: {str(e)}")
        finally:
            print(_(f"LLMClient: Cleaning up stream task (success={success})."))
            self._is_generating_flag = False
            self._stream_thread = None
            if success:
                cid = self.config.get('cid')
                model_id = self.get_model_id()
                if not cid and self.get_conversation_id():
                    new_cid = self.get_conversation_id()
                    self.config['cid'] = new_cid
                    print(f"Nueva conversación creada con ID: {new_cid}")
                    default_name = _("New Conversation")
                    chat_history.create_conversation_if_not_exists(new_cid, default_name)
                    cid = new_cid
                if cid and model_id:
                    try:
                        chat_history.add_history_entry(
                            cid,
                            prompt,
                            full_response,
                            model_id
                        )
                    except Exception as e:
                        print(f"Error al guardar en historial: {e}")
            chat_history.close() # Close the connection
            GLib.idle_add(self.emit, 'finished', success)

    def cancel(self):
        """Cancels the current stream processing task."""
        print(_("LLMClient: Cancel request received."))
        self._is_generating_flag = False
        if self._stream_thread and self._stream_thread.is_alive():
            print(_("LLMClient: Terminating active stream thread."))
            self._stream_thread = None
        else:
            print(_("LLMClient: No active stream thread to cancel."))

    def get_model_id(self):
        """Returns the ID of the loaded model."""
        return self.model.model_id if self.model else None

    def get_conversation_id(self):
        """Returns the ID of the current conversation if it exists."""
        return self.conversation.id if self.conversation else None

    def load_history(self, history_entries):
        """Loads previous history into the conversation object."""
        if self._init_error or not self.model:
            print(_("LLMClient: Error - Attempting to load history with model initialization error."))
            return
        if not self.conversation:
            print(_("LLMClient: Error - Attempting to load history without initialized conversation."))
            return

        current_model = self.model
        current_conversation = self.conversation

        print(_(f"LLMClient: Loading {len(history_entries)} history entries..."))
        current_conversation.responses.clear()

        last_prompt_obj = None

        for entry in history_entries:
            user_prompt = entry.get('prompt')
            assistant_response = entry.get('response')

            if user_prompt:
                last_prompt_obj = llm.Prompt(user_prompt, current_model)
                resp_user = llm.Response(
                    last_prompt_obj, current_model, stream=False,
                    conversation=current_conversation
                )
                resp_user._prompt_json = {'prompt': user_prompt}
                resp_user._done = True
                resp_user._chunks = []
                current_conversation.responses.append(resp_user)

            if assistant_response and last_prompt_obj:
                resp_assistant = llm.Response(
                    last_prompt_obj, current_model, stream=False,
                    conversation=current_conversation
                )
                resp_assistant._prompt_json = {
                    'prompt': last_prompt_obj.prompt
                }
                resp_assistant._done = True
                resp_assistant._chunks = [assistant_response]
                current_conversation.responses.append(resp_assistant)
            elif assistant_response and not last_prompt_obj:
                print(_("LLMClient: Warning - Assistant response without "
                      "previous user prompt in history."))

        print(_("LLMClient: History loaded. Total responses in conversation: "
                + f"{len(current_conversation.responses)}"))

GObject.type_register(LLMClient)
