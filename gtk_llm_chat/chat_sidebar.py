import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GObject # Importar GObject si necesitas señales/propiedades
# Importar _ desde el lugar correcto, asumiendo que está en chat_application
# Ajusta la ruta si es necesario (ej. from .chat_application import _)
try:
    from .chat_application import _
except ImportError:
    # Fallback si se ejecuta directamente o la estructura es diferente
    def _(s): return s


class ChatSidebar(Gtk.Box):
    """
    Sidebar widget for model selection and configuration.
    """
    # Opcional: Definir señales si el sidebar necesita comunicar cambios
    # __gsignals__ = {
    #     'model-changed': (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    #     'temperature-changed': (GObject.SignalFlags.RUN_FIRST, None, (float,))
    # }

    def __init__(self, config=None, llm_client=None, **kwargs):
        # Extraer argumentos específicos ANTES de llamar al super()
        self.config = config or {}
        self.llm_client = llm_client # Puede ser None inicialmente

        # Llamar al constructor de Gtk.Box con el resto de kwargs
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, **kwargs)

        self.set_margin_top(12)
        self.set_margin_bottom(12)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_size_request(280, -1) # Opcional: un ancho por defecto

        # --- Título del Sidebar ---
        sidebar_title = Gtk.Label(label=_("Model Configuration"))
        sidebar_title.add_css_class("title-4") # Estilo de título
        sidebar_title.set_halign(Gtk.Align.START) # Alinear a la izquierda
        self.append(sidebar_title)

        # --- Contenedor para las preferencias (usando Adw.PreferencesGroup) ---
        prefs_group = Adw.PreferencesGroup()
        self.append(prefs_group)

        # --- Fila para seleccionar el modelo ---
        self.model_row = Adw.ComboRow(title=_("Model")) # Guardar referencia
        # Poblar modelos (esto debería ser dinámico)
        self._populate_models()
        # Seleccionar modelo actual de la configuración si existe
        current_model = self.config.get('model') # Asumiendo que 'model' está en config
        if current_model:
             self._select_model_in_combo(current_model)

        # Conectar señal para reaccionar al cambio de modelo
        self.model_row.connect("notify::selected-item", self._on_model_selected)
        prefs_group.add(self.model_row)

        # --- Fila para ajustar la temperatura (ejemplo) ---
        self.temperature_row = Adw.ActionRow(title=_("Temperature")) # Guardar referencia
        # Obtener valor inicial de la config o usar default
        initial_temp = self.config.get('temperature', 0.7)
        self.adjustment = Gtk.Adjustment(value=initial_temp, lower=0.0, upper=2.0, step_increment=0.1, page_increment=0.2)
        self.adjustment.connect("value-changed", self._on_temperature_changed)
        scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=self.adjustment, digits=1, value_pos=Gtk.PositionType.RIGHT)
        scale.set_hexpand(True)
        self.temperature_row.add_suffix(scale)
        self.temperature_row.set_activatable_widget(scale) # Permitir activar la fila haciendo clic en la escala
        prefs_group.add(self.temperature_row)

        # --- Puedes añadir más Adw.PreferencesRow, Adw.ActionRow, Adw.ExpanderRow, etc. aquí ---
        # Ejemplo: Expander para ajustes avanzados
        # advanced_expander = Adw.ExpanderRow(title=_("Advanced Settings"))
        # advanced_expander.add_row(Adw.ActionRow(title=_("Setting 1")))
        # advanced_expander.add_row(Adw.ActionRow(title=_("Setting 2")))
        # prefs_group.add(advanced_expander)

    def set_llm_client(self, llm_client):
        """Permite establecer el cliente LLM después de la inicialización."""
        self.llm_client = llm_client
        # Opcional: Repoblar modelos si dependen del cliente LLM
        # self._populate_models()

    def _populate_models(self):
        """Puebla la lista de modelos en el ComboRow."""
        # --- Lógica para obtener modelos ---
        # Esto es un placeholder. Deberías obtener la lista real de modelos
        # disponibles, quizás desde self.llm_client o self.config
        available_models = ["Model A (Placeholder)", "Model B (Placeholder)", "Model C (Placeholder)"]
        if self.llm_client and hasattr(self.llm_client, 'get_available_models'):
             try:
                  # Intenta obtener modelos del cliente LLM si existe el método
                  models_from_client = self.llm_client.get_available_models()
                  if models_from_client:
                       available_models = models_from_client
             except Exception as e:
                  print(f"Warning: Could not get models from LLM client: {e}")
        # --- Fin Lógica ---

        self.model_row.set_model(Gtk.StringList.new(available_models))

    def _select_model_in_combo(self, model_name_to_select):
        """Selecciona un modelo específico en el ComboRow."""
        model = self.model_row.get_model()
        if not model:
            return
        for i in range(model.get_n_items()):
            item = model.get_string(i)
            if item == model_name_to_select:
                self.model_row.set_selected(i)
                break

    def _on_model_selected(self, combo_row, param):
        """Manejador para cuando cambia el modelo seleccionado."""
        selected_item = combo_row.get_selected_item()
        if selected_item:
            model_name = selected_item.get_string()
            print(f"Sidebar: Model selected: {model_name}")
            # Actualizar la configuración interna
            self.config['model'] = model_name
            # Notificar a la ventana principal o al cliente LLM
            if self.llm_client and hasattr(self.llm_client, 'set_model'):
                 try:
                      self.llm_client.set_model(model_name)
                 except Exception as e:
                      print(f"Error setting model in LLM client: {e}")
            # O emitir una señal si se definieron __gsignals__
            # self.emit('model-changed', model_name)

    def _on_temperature_changed(self, adjustment):
        """Manejador para cuando cambia el valor de la temperatura."""
        temperature = adjustment.get_value()
        print(f"Sidebar: Temperature changed: {temperature:.1f}")
        # Actualizar la configuración interna
        self.config['temperature'] = temperature
        # Notificar al cliente LLM
        if self.llm_client and hasattr(self.llm_client, 'set_temperature'):
             try:
                  self.llm_client.set_temperature(temperature)
             except Exception as e:
                  print(f"Error setting temperature in LLM client: {e}")
        # O emitir una señal
        # self.emit('temperature-changed', temperature)
