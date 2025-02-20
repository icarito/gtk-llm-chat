# GTK LLM Chat

Una interfaz gráfica GTK para chatear con modelos de lenguaje (LLMs).

## Características

- Interfaz gráfica simple y fácil de usar construida con GTK
- Soporte para múltiples conversaciones en ventanas independientes
- Integración con python-llm para chat con diversos modelos de LLM
- Interfaz moderna usando libadwaita
- Soporte para streaming de respuestas en tiempo real
- Historial de mensajes con desplazamiento automático
- Atajos de teclado (Enter para enviar, Shift+Enter para nueva línea)
- Soporte para cancelación de generación (Ctrl+C)

## Instalación

pip install gtk-llm

### Requisitos del Sistema

- Python 3.8 o superior
- GTK 4.0
- libadwaita
- python-llm

En sistemas basados en Debian/Ubuntu:
```
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 libadwaita-1-0
```

## Uso

Ejecutar la aplicación:
```
gtk-llm-chat
```

Con argumentos opcionales:
```
gtk-llm-chat --cid ID_CONVERSACION  # Continuar una conversación específica
gtk-llm-chat -s "Prompt del sistema"  # Establecer prompt del sistema
gtk-llm-chat -m nombre_modelo  # Seleccionar modelo específico
gtk-llm-chat -c  # Continuar última conversación
```

## Desarrollo

Para configurar el entorno de desarrollo:
```
git clone https://github.com/icarito/gtk-llm-chat.git
cd gtk-llm-chat
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

## Licencia

GPLv3 License - Ver archivo LICENSE para más detalles.