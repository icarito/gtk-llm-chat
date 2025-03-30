# GTK LLM Chat

Una interfaz gráfica GTK para chatear con modelos de lenguaje (LLMs).

![screenshot](./docs/screenshot01.png)

## Características

- Interfaz gráfica simple y fácil de usar construida con GTK
- Soporte para múltiples conversaciones en ventanas independientes
- Integración con python-llm para chat con diversos modelos de LLM
- Interfaz moderna usando libadwaita
- Soporte para streaming de respuestas en tiempo real
- Historial de mensajes con desplazamiento automático
- Atajos de teclado (Enter para enviar, Shift+Enter para nueva línea)

## Instalación

```
pipx install llm               # required by gtk-llm-chat
llm install gtk-chat
```

### Requisitos del Sistema

- [llm](https://llm.datasette.io/en/stable/)
- Python 3.8 o superior
- GTK 4.0
- libadwaita
- libayatana-appindicator

En sistemas basados en Debian/Ubuntu:
```
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 libadwaita-1-0 libayatana-appindicator3-1
```

## Uso

Ejecutar la aplicación:
```
llm gtk-applet
```

o para un chat individual:
```
llm gtk-chat
```


Con argumentos opcionales:
```
llm gtk-chat --cid ID_CONVERSACION  # Continuar una conversación específica
llm gtk-chat -s "Prompt del sistema"  # Establecer prompt del sistema
llm gtk-chat -m nombre_modelo  # Seleccionar modelo específico
llm gtk-chat -c  # Continuar última conversación
```

## Desarrollo

Para configurar el entorno de desarrollo:
```
git clone https://github.com/icarito/gtk-llm-chat.git
cd gtk-llm-chat
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Licencia

GPLv3 License - Ver archivo LICENSE para más detalles.