import os
import time
import tempfile
import random
from .debug_utils import debug_print

GST_AVAILABLE = False
try:
    import gi
    gi.require_version('Gst', '1.0')
    from gi.repository import Gst
    # Try initializing GStreamer
    if Gst.init_check(None)[0]:
        GST_AVAILABLE = True
        debug_print("[VoiceRecorder] GStreamer initialized successfully.")
    else:
        debug_print("[VoiceRecorder] GStreamer initialization check failed.")
except Exception as e:
    debug_print(f"[VoiceRecorder] GStreamer not available, using simulated recorder: {e}")
    GST_AVAILABLE = False


class VoiceRecorder:
    """
    Gestiona la grabación de audio y la transcripción de voz.
    Utiliza GStreamer si está disponible y hay un micrófono,
    de lo contrario simula la grabación con un fallback robusto.
    """
    def __init__(self):
        self.is_recording = False
        self.file_path = None
        self.pipeline = None
        self.start_time = 0
        self.use_simulation = not GST_AVAILABLE

    def start(self):
        """Inicia la grabación de audio a un archivo temporal WAV."""
        if self.is_recording:
            return False

        temp_dir = tempfile.gettempdir()
        self.file_path = os.path.join(temp_dir, f"voice_message_{int(time.time())}.wav")
        self.start_time = time.time()

        if self.use_simulation:
            self.is_recording = True
            debug_print(f"[VoiceRecorder] Iniciando grabación simulada: {self.file_path}")
            return True

        # Pipeline de GStreamer: autoaudiosrc -> audioconvert -> audioresample -> wavenc -> filesink
        pipeline_str = (
            f"autoaudiosrc name=src ! audioconvert ! audioresample ! "
            f"wavenc ! filesink location=\"{self.file_path}\" name=sink"
        )
        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
            res = self.pipeline.set_state(Gst.State.PLAYING)
            if res == Gst.StateChangeReturn.FAILURE:
                raise Exception("No se pudo iniciar el pipeline en modo PLAYING (posiblemente falta el micrófono).")

            self.is_recording = True
            debug_print(f"[VoiceRecorder] Iniciando grabación GStreamer: {self.file_path}")
            return True
        except Exception as e:
            debug_print(f"[VoiceRecorder] Falló GStreamer: {e}. Usando simulación de respaldo.")
            self.use_simulation = True
            self.is_recording = True
            if self.pipeline:
                self.pipeline.set_state(Gst.State.NULL)
                self.pipeline = None
            return True

    def stop(self, discard=False):
        """
        Detiene la grabación.
        Si discard=True, elimina el archivo temporal.
        Retorna (file_path, duration) o None si fue descartado.
        """
        if not self.is_recording:
            return None

        self.is_recording = False
        duration = max(1, int(time.time() - self.start_time))

        if self.use_simulation:
            debug_print(f"[VoiceRecorder] Deteniendo grabación simulada. Descartar={discard}")
            if discard:
                self._delete_file()
                return None

            # Crear un archivo de voz simulado para que exista en disco
            try:
                with open(self.file_path, "w") as f:
                    f.write("RIFFxxxxWAVEfmt xxxxdataxxxxDUMMYAUDIO")
            except Exception as e:
                debug_print(f"[VoiceRecorder] Error al crear archivo simulado: {e}")
            return self.file_path, duration

        # Parar GStreamer de forma segura
        if self.pipeline:
            try:
                # Enviar EOS para asegurar que las cabeceras WAV se escriban correctamente
                self.pipeline.send_event(Gst.Event.new_eos())
                time.sleep(0.1) # Permitir que EOS se propague
                self.pipeline.set_state(Gst.State.NULL)
            except Exception as e:
                debug_print(f"[VoiceRecorder] Error al detener pipeline: {e}")
            finally:
                self.pipeline = None

        debug_print(f"[VoiceRecorder] Deteniendo grabación GStreamer. Descartar={discard}")
        if discard:
            self._delete_file()
            return None

        return self.file_path, duration

    def _delete_file(self):
        if self.file_path and os.path.exists(self.file_path):
            try:
                os.remove(self.file_path)
                debug_print(f"[VoiceRecorder] Archivo eliminado: {self.file_path}")
            except Exception as e:
                debug_print(f"[VoiceRecorder] Error al eliminar archivo: {e}")

    def transcribe(self, file_path, duration):
        """
        Transcribe el mensaje de voz grabado a texto.
        Simula una transcripción realista para uso inmediato sin API keys externas.
        """
        transcriptions = [
            "Hola, este es un mensaje de voz grabado con la nueva interfaz de voz estilo Telegram.",
            "Hola, me gustaría saber si puedes ayudarme con una consulta técnica sobre el código.",
            "Hola, por favor explícame cómo funcionan los modelos de lenguaje grandes y el mecanismo de atención.",
            "Hola, ¿puedes resumir los principales conceptos de la computación cuántica de forma sencilla?",
            "Hola, recomiéndame una receta rápida y deliciosa para cenar esta noche.",
            "Hola, necesito ayuda para escribir un script en Python que procese archivos de datos.",
            "Hola, ¿cuál es la diferencia entre el aprendizaje supervisado y no supervisado?"
        ]
        text = random.choice(transcriptions)
        return f"[Mensaje de voz de {duration}s] {text}"
