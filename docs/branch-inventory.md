# Inventario de ramas y stashes

> Generado el 2026-07-03 durante la reorganización del proyecto (retomada tras ~1 año).
> Base de trabajo: `main` (v4.0.5, commit `4a8e301`).
> "delante/detrás" es respecto a `main`. Las ramas con copia en origin son recuperables
> aunque se borren localmente.

## Ramas borradas en esta limpieza

| Rama | SHA punta | Motivo |
|---|---|---|
| `cli_changes_fail` | `a96bd40` | Fusionada en main |
| `unify_executables` | `a170a48` | Fusionada en main |
| `fix_appimage_for_older_TRY1` | `1a4d8ed` | Intento superado por `fix_appimage_for_older` (que sí está en origin) |
| `experiment-brute-force-backport-gtk3` | `57cde58` | Experimento de fuerza bruta superado por `experiment-architect-backport-gtk3` |

Los SHAs quedan registrados: `git branch <nombre> <sha>` los resucita mientras no corra gc.

## Ramas activas / con valor

| Rama | Última actividad | delante/detrás | En origin | Qué es | Veredicto |
|---|---|---|---|---|---|
| `main` | 2025-06-09 | — | sí | Rama principal, v4.0.5 | **Base de trabajo** |
| `haiku_port` | 2025-06-12 | +5/−0 | sí | Port a Haiku: estilos nativos, CSS por plataforma, GResource | **Conservar** — aparcada limpia; los experimentos del fork pystray están en `icarito/pystray@haiku-experiments` |
| `decouple_llm` | 2025-06-10 | +1/−0 | sí | Modo sin LLM con stubs y migraciones | **Conservar** — al día con main, candidata a retomarse |
| `workflow-rework` | 2025-06-08 | +4/−3 | sí | Ajustes de CI (versión Windows) | Revisar si quedó algo sin fusionar (d102999 en main fue "Workflow rework #58") |
| `flatpak-fix` | 2025-06-05 | +1/−25 | sí | Manifiesto Flatpak moderno + AppIndicator | Conservar hasta decidir estrategia Flatpak |
| `update_translations` | 2025-06-04 | +1/−37 | sí | Actualización de strings | Revisar si las traducciones ya entraron por otra vía |
| `welcome-druid` | 2025-06-04 | +31/−38 | sí | Asistente de bienvenida (druid) | Conservar — feature considerable (31 commits) |
| `icarito/issue48` | 2025-06-06 | +25/−25 | sí | Últimos intentos de arreglar iconos | Probablemente obsoleta: main tiene "Fix icons at last" (75acf7d) |

## Ramas históricas (experimentos y fixes de la era pre-4.0.5)

Casi todas están muy detrás de main (60–180 commits); su valor es arqueológico.
Todas menos tres están en origin.

| Rama | Última actividad | delante/detrás | En origin | Qué es |
|---|---|---|---|---|
| `ci/macos-builds` | 2025-05-11 | +6/−88 | **no** | Builds de macOS en CI |
| `dbus_invoke` | 2025-05-14 | +35/−72 | sí | Invocación por D-Bus, ejecutable único |
| `experiment-architect-backport-gtk3` | 2025-03-31 | +1/−133 | sí | Backport GTK4→GTK3 |
| `feat_set_default_model` | 2025-05-18 | +1/−64 | sí | Workflow de modelo por defecto |
| `fix-history-issues` | 2025-05-09 | +1/−89 | sí | Refactor de load_history |
| `fix_33` / `fix_bug_33` | 2025-05-18/19 | +1/−65 | sí | Dos intentos del mismo bug (#33, set model) |
| `fix_appimage_for_older` | 2025-05-20 | +8/−66 | sí | AppImage para distros viejas |
| `fix_model_list` | 2025-05-11 | +3/−85 | sí | Proveedores duplicados |
| `fix_new_conversation_dbus` | 2025-05-23 | +1/−44 | sí | Nueva conversación vía D-Bus |
| `fix_process_integration` / `integrated` | 2025-05-12/13 | +4/−72 | sí | Invocación de procesos multi-entorno |
| `gtk3` | 2025-03-31 | +1/−133 | **no** | Port a GTK3 (ejemplo) |
| `mac_os_build` | 2025-05-09 | +1/−89 | sí | Build macOS sin firma |
| `markdown_parser_feat` | 2025-02-22 | +1/−183 | sí | Renderer Markdown con tokenizer propio |
| `new_applet` | 2025-05-03 | +5/−97 | sí | Applet v2.2.3dev0 |
| `new_default_model_workflow` | 2025-05-18 | +3/−64 | sí | Otra vuelta al modelo por defecto |
| `new_sidebar` | 2025-05-08 | +19/−94 | sí | Sidebar nuevo |
| `performance_refactor` | 2025-04-22 | +1/−106 | **no** | "Lazy everything" (incompleto) |
| `plans` | 2025-03-29 | +1/−142 | sí | Rama-cuaderno de planes (llm_client) |
| `pydeploy-hello-gtk-template` | 2025-04-26 | +11/−101 | sí | Plantilla de deployment GTK |
| `pyinstaller` | 2025-04-25 | +14/−102 | sí | Empaquetado PyInstaller |
| `simplify_startup` | 2025-05-16 | +39/−72 | sí | Simplificación del arranque |
| `single_trayapp_instance` / `try2_single_tray_instance` | 2025-05-22 | +4/+5/−57 | sí | Dos intentos de instancia única del tray |

**Sugerencia**: cuando confirmes que no las necesitas, las que están en origin se pueden
borrar localmente sin riesgo (`git branch -D`). Las tres sin origin (`ci/macos-builds`,
`gtk3`, `performance_refactor`) requieren decisión explícita: push a origin o borrado definitivo.

## Stashes

El antiguo `stash@{0}` (WIP on haiku_port: añadía `.flatpak*` a .gitignore) se aplicó a main
y se descartó durante esta limpieza. Quedan 8, renumerados:

| Stash | Fecha | Rama origen | Contenido | Nota |
|---|---|---|---|---|
| `stash@{0}` | 2025-06-08 | main | `release.yml` −209/+97 líneas | Reescritura grande del workflow de release, posterior al último commit de main. **El más interesante: revisar** |
| `stash@{1}` | 2025-06-07 | main | `resource_manager.py` +22 | Detección Flatpak / iconos |
| `stash@{2}` | 2025-06-04 | main | 11 archivos, −32/+22 | Ajustes varios welcome/selector |
| `stash@{3}` | 2025-06-04 | welcome-druid | `welcome.py`, `single_instance.py` | WIP del druid |
| `stash@{4}` | 2025-05-18 | fix_appimage_for_older | `release.yml` ±2 | Trivial |
| `stash@{5}` | 2025-05-09 | mac_os_build | `llm_client.py` ±1000 líneas | Refactor grande de llm_client, probablemente obsoleto tras refactors de mayo/junio |
| `stash@{6}` | 2025-04-29 | new_applet | `llm_gui.py` +6 | Menor |
| `stash@{7}` | 2025-04-20 | main (v2.0.5) | `llm_gui.py`, `main.py` | Era v2.x, obsoleto |

**Sugerencia**: revisar `stash@{0}` y `stash@{1}` (son sobre main reciente); del 4 al 7
son droppeables con confianza cuando quieras.
