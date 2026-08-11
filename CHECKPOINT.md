# CHECKPOINT: Asesor Clínico MEFI
**Fecha última actualización:** 15 de julio de 2026
**Estado:** Refactorización Modular (Hito 2 completado, Hito 3 en progreso)

## 1. Estatus de la Arquitectura
- [x] **Configuración externa:** `config.yaml` creado y activo.
- [x] **Capa de Abstracción:** `llm_client.py` creado y operativo.
- [x] **Inyección de Dependencias:** `app.py` ya inyecta el `client` y `modelo` a las funciones.
- [ ] **Desacoplamiento UI-Lógica:** Pendiente de confirmar que `app.py` no contenga lógica de conexión antigua.

## 2. Pendientes Inmediatos (Next Steps)
1.  **Resolver el 404 (Model Not Found):** Probar los IDs exactos de la "Lista Segura" en `config.yaml` (`google/gemini-flash-1.5` o `anthropic/claude-3.5-sonnet`).
2.  **Verificación de Interfaz:** Asegurar que `app.py` tiene la firma de función correcta: `def analizar_imagen_mefi(imagen_bytes, client, modelo):`.
3.  **Smoke Test:** Subir imagen (JPG/PNG) y verificar que no lance error 400 (Invalid Image Input).

## 3. Notas Técnicas (Lessons Learned)
- **Error 400 (Invalid Image Input):** Se sospecha que el parámetro `response_format={"type": "json_object"}` estaba causando conflictos con modelos de visión. Se eliminó para probar estabilidad.
- **Error 404:** Los IDs de los modelos en OpenRouter son sensibles. Usar siempre el script de verificación o la lista oficial.
- **Estructura:** La app ahora funciona como `App -> LLM Factory -> Provider`. No volver a "hardcodear" URLs de API en `app.py`.

## 4. Próximos Objetivos (Hito 3)
- Validar flujo clínico completo (CSV + Reporte Markdown).
- Implementar selector de modelo dinámico en UI.
- Preparar estructura para `providers/` (NVIDIA/HuggingFace) para futura escalabilidad.