## 1. Fix

- [x] 1.1 En `chat_window.py`, en `_on_llm_error` (~línea 3390), reactivar
      el input y detener el spinner (mismo efecto que `set_enabled(True)`
      en `_on_llm_finished`).
- [x] 1.2 Confirmar que `_on_llm_finished` no queda duplicando trabajo de
      forma problemática si ambas señales llegaran a dispararse para un
      mismo turno. `set_enabled` (línea 1717) es idempotente — sólo setea
      `sensitive`/visible child state sin contadores ni acumulación; el
      mismo patrón de llamarlo preventivamente ya existe en
      `_on_stop_clicked` (línea 1743). Sin riesgo de duplicación
      problemática.

## 2. Verificación

- [ ] 2.1 Reproducir manualmente un error pre-streaming (por ejemplo,
      forzar backend sin modelo configurado) y confirmar que el input
      queda usable inmediatamente después del error. **Pendiente**: el
      flag `--no-llm` documentado en docs/development-guide.md ya no
      existe en `main.py` actual (`unrecognized arguments: --no-llm`) —
      la app requiere una sesión GTK interactiva real para probar el
      flujo de error visualmente; no se pudo automatizar sin abrir una
      ventana. Queda como verificación manual pendiente por el usuario.
- [ ] 2.2 Reproducir un error durante streaming activo y confirmar que no
      hay regresión (input se reactiva igual que antes). Mismo
      impedimento que 2.1 — pendiente de verificación manual con ventana
      real.
- [x] 2.3 Correr la suite de tests y los comandos de verificación
      documentados en CLAUDE.md / docs/development-guide.md.
      `pytest tests/`: 55/55 passed (sin regresión; no hay tests
      existentes que cubran `_on_llm_error` específicamente). `flake8`
      con la config real del repo (`--max-line-length=95
      --extend-ignore=E402`, ya que flake8 no lee `pyproject.toml` sin un
      plugin adicional que el repo no tiene instalado): mismo conteo de
      warnings preexistentes (82) antes y después del cambio — ningún
      warning nuevo introducido.
