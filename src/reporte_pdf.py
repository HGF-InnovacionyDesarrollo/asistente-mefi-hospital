"""Generador de Reporte Clínico Consolidado en PDF (Plantilla Determinística + Contraste LLM).

Usa PyMuPDF (`fitz.Story` + `fitz.DocumentWriter`) para maquetar un documento A4
institucional con:
1. Encabezado del Hospital Dr. Gustavo Fricke y metadatos del registro.
2. Resumen ejecutivo de parámetros cuantificados y semáforo FIGO 2015 / NICE NG229.
3. Captura del trazado digitalizado con curvas de auditoría (celeste/naranja).
4. Cuadro comparativo lado a lado (Informe por Plantilla vs. Informe IA / LLM)
   alineado en las 4 dimensiones clínicas.
5. Recuadro de firma/timbre profesional y disclaimer clínico obligatorio (INFANT).
"""

from __future__ import annotations

import datetime
import html
import io
import re

import fitz  # PyMuPDF
from PIL import Image

import prompts


def _md_a_html(texto_md: str) -> str:
    """Convierte el subconjunto de Markdown usado en los informes (negritas,
    cursivas, código inline, listas y párrafos) a HTML limpio para `fitz.Story`."""
    if not texto_md:
        return "<p><i>Sin contenido disponible.</i></p>"

    lineas_html: list[str] = []
    en_lista = False

    def _formatear_inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", s)
        s = re.sub(r"`([^`]+)`", r"<tt>\1</tt>", s)
        return s

    for cruda in texto_md.splitlines():
        s = cruda.strip()
        if not s:
            if en_lista:
                lineas_html.append("</ul>")
                en_lista = False
            continue

        if s.startswith("#"):
            if en_lista:
                lineas_html.append("</ul>")
                en_lista = False
            titulo = s.lstrip("#").strip()
            lineas_html.append(f"<p><b>{_formatear_inline(titulo)}</b></p>")
            continue

        m_bullet = re.match(r"^(?:[-*•]|\d+\.)\s+(.*)", s)
        if m_bullet:
            if not en_lista:
                lineas_html.append("<ul>")
                en_lista = True
            lineas_html.append(f"<li>{_formatear_inline(m_bullet.group(1))}</li>")
        else:
            if en_lista:
                lineas_html.append("</ul>")
                en_lista = False
            lineas_html.append(f"<p>{_formatear_inline(s)}</p>")

    if en_lista:
        lineas_html.append("</ul>")

    return "\n".join(lineas_html)


def generar_pdf_consolidado(
    features: dict,
    informe_plantilla: str,
    informe_llm: str | None = None,
    metadatos: dict | None = None,
    overlay_img: Image.Image | None = None,
    modelo_llm: str | None = None,
) -> bytes:
    """Construye y devuelve los bytes del PDF consolidado A4."""
    ahora_str = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")
    meta = metadatos or {}
    id_reg = html.escape(str(meta.get("id") or "Sin identificar (anónimo)"))
    fecha_reg = html.escape(str(meta.get("fecha_hora") or "No especificada"))
    vel_reg = html.escape(str(meta.get("velocidad_papel_cm_min") or 1.0))
    eg_reg = html.escape(str(meta.get("edad_gestacional") or "No especificada"))
    ctx_reg = html.escape(str(meta.get("contexto_clinico") or "No especificado"))
    oxi_reg = html.escape(str(meta.get("uso_oxitocina") or "No especificado"))
    mec_reg = html.escape(str(meta.get("meconio") or "No especificado"))
    pat_reg = html.escape(str(meta.get("patologia_antenatal") or "No reportada"))
    comp_reg = html.escape(
        str(meta.get("comparacion_mefi_previos") or "Pendiente contrastar con MEFI previos del caso (Protocolo V2)")
    )
    prof_reg = html.escape(str(meta.get("profesional") or ""))
    obs_reg = html.escape(str(meta.get("observaciones_clinicas") or "")).replace("\n", "<br/>")

    figo = features["figo"]
    cat = figo["categoria"]
    desc_figo = html.escape(figo["descripcion"])
    razones_figo = html.escape(" · ".join(figo["razones"]))
    semaforo = figo["semaforo_nice"]

    colores_cat = {
        "I": ("#E8F5E9", "#1B5E20"),
        "II": ("#FFF8E1", "#E65100"),
        "III": ("#FFEBEE", "#B71C1C"),
    }
    bg_cat, fg_cat = colores_cat.get(cat, ("#ECEFF1", "#263238"))

    etiqueta_semaforo = {
        "verde": "<span style='color:#1B5E20;'><b>NORMAL (Verde)</b></span>",
        "amarillo": "<span style='color:#E65100;'><b>SOSPECHOSO (Ámbar)</b></span>",
        "rojo": "<span style='color:#B71C1C;'><b>PATOLÓGICO (Rojo)</b></span>",
    }

    contr = features.get("contracciones") or {}
    if contr.get("num") is not None:
        val_contr = f"{contr['num']} detectada(s)"
        if contr.get("por_10min") is not None:
            val_contr += f" ({contr['por_10min']}/10 min)"
        if contr.get("tachisistolia"):
            val_contr += " — Taquisistolia"
    else:
        val_contr = "Sin datos de UA"

    area_decel = features.get("area_desaceleraciones_lpm_s")
    val_decel = f"{len(features['desaceleraciones'])} detectada(s)"
    if area_decel is not None:
        val_decel += f" (área {area_decel:,} lpm·s)".replace(",", ".")

    val_sin = (
        f"Presente ({features['patron_sinusoidal'].get('frecuencia_dominante_cpm')} cpm)"
        if features["patron_sinusoidal"].get("presente")
        else "No detectado"
    )

    sec_plantilla = prompts.extraer_secciones_informe(informe_plantilla)
    if informe_llm and informe_llm.strip():
        sec_llm = prompts.extraer_secciones_informe(informe_llm)
        subtitulo_llm = f"Informe IA / LLM ({html.escape(modelo_llm or 'Modelo activo')})"
    else:
        sec_llm = {
            k: "<i>Informe con IA (LLM) no solicitado en esta sesión — se emite únicamente el informe determinístico por protocolo.</i>"
            for k, _ in prompts.DIMENSIONES_COMPARACION
        }
        subtitulo_llm = "Informe IA / LLM (No ejecutado)"

    archive = fitz.Archive()
    bloque_imagen_html = ""
    if overlay_img is not None:
        img_copia = overlay_img.copy().convert("RGB")
        max_w = 1100
        if img_copia.width > max_w:
            escala = max_w / img_copia.width
            img_copia = img_copia.resize((max_w, max(1, int(img_copia.height * escala))))
        buf_img = io.BytesIO()
        img_copia.save(buf_img, format="PNG")
        archive = fitz.Archive()
        archive.add(buf_img.getvalue(), "trazado_auditado.png")
        bloque_imagen_html = """
        <h3>2. Trazado Digitalizado y Auditado</h3>
        <p class="small">Curva celeste = lectura directa sobre el papel · Curva naranja = tramo interpolado.</p>
        <p><img src="trazado_auditado.png" width="510" /></p>
        """

    filas_comparativas = []
    for clave, titulo_dim in prompts.DIMENSIONES_COMPARACION:
        html_izq = _md_a_html(sec_plantilla.get(clave, ""))
        html_der = (
            _md_a_html(sec_llm.get(clave, ""))
            if (informe_llm and informe_llm.strip())
            else f"<p>{sec_llm[clave]}</p>"
        )
        filas_comparativas.append(
            f"""
            <tr class="dim-header">
                <td width="50%"><b>{html.escape(titulo_dim)} — Plantilla</b></td>
                <td width="50%"><b>{html.escape(titulo_dim)} — IA / LLM</b></td>
            </tr>
            <tr>
                <td width="50%" valign="top" class="cell-col">{html_izq}</td>
                <td width="50%" valign="top" class="cell-col">{html_der}</td>
            </tr>
            """
        )

    sintesis = prompts.generar_sintesis_concordancia(features, informe_plantilla, informe_llm)
    html_sintesis_puntos = _md_a_html("\n".join(f"- {p}" for p in sintesis["puntos"]))

    html_doc = f"""
    <html>
    <body>
        <div class="header-box">
            <h1>HOSPITAL DR. GUSTAVO FRICKE — ASESOR CLÍNICO MEFI</h1>
            <p class="subtitle">Reporte Consolidado de Cardiotocografía (Protocolo FIGO 2015 / NICE NG229 + Contraste IA)</p>
        </div>

        <div class="meta-table">
            <p><b>ID Registro:</b> {id_reg} &nbsp;·&nbsp; <b>Fecha/Hora Trazado:</b> {fecha_reg} &nbsp;·&nbsp; <b>Velocidad Papel:</b> {vel_reg} cm/min &nbsp;·&nbsp; <b>Emisión:</b> {ahora_str}</p>
            <p><b>Edad Gestacional:</b> {eg_reg} &nbsp;·&nbsp; <b>Contexto Clínico:</b> {ctx_reg} &nbsp;·&nbsp; <b>Uso de Oxitocina:</b> {oxi_reg} &nbsp;·&nbsp; <b>Evaluador:</b> {prof_reg if prof_reg else "Por firmar"}</p>
            <p><b>Meconio:</b> {mec_reg} &nbsp;·&nbsp; <b>Patología Antenatal:</b> {pat_reg} &nbsp;·&nbsp; <b>Comparación MEFI previos:</b> {comp_reg}</p>
        </div>

        <div class="cat-banner" style="background-color:{bg_cat}; color:{fg_cat};">
            <p><b>CLASIFICACIÓN DETERMINÍSTICA: CATEGORÍA FIGO {cat} — {desc_figo.upper()}</b><br/>
            <span class="small">Criterios: {razones_figo}</span></p>
        </div>

        <h3>1. Resumen Ejecutivo de Parámetros y Semáforo NICE NG229</h3>
        <table width="100%" class="params-table">
            <tr class="table-head">
                <td width="28%"><b>Variable CTG</b></td>
                <td width="44%"><b>Valor Cuantificado</b></td>
                <td width="28%"><b>Semáforo NICE NG229</b></td>
            </tr>
            <tr>
                <td><b>Línea Base FCF</b></td>
                <td>{features['linea_base']:.0f} lpm</td>
                <td>{etiqueta_semaforo[semaforo['linea_base']]}</td>
            </tr>
            <tr>
                <td><b>Variabilidad</b></td>
                <td>{features['variabilidad']['amplitud_media_lpm']} lpm ({html.escape(features['variabilidad']['categoria'])})</td>
                <td>{etiqueta_semaforo[semaforo['variabilidad']]}</td>
            </tr>
            <tr>
                <td><b>Aceleraciones</b></td>
                <td>{len(features['aceleraciones'])} detectada(s)</td>
                <td>Reactividad</td>
            </tr>
            <tr>
                <td><b>Desaceleraciones</b></td>
                <td>{html.escape(val_decel)}</td>
                <td>{etiqueta_semaforo[semaforo['desaceleraciones']]}</td>
            </tr>
            <tr>
                <td><b>Contracciones (UA)</b></td>
                <td>{html.escape(val_contr)}</td>
                <td>{etiqueta_semaforo[semaforo.get('contracciones', 'verde')]}</td>
            </tr>
            <tr>
                <td><b>Patrón Sinusoidal</b></td>
                <td>{html.escape(val_sin)}</td>
                <td>{"<span style='color:#B71C1C;'><b>PATOLÓGICO</b></span>" if features['patron_sinusoidal'].get('presente') else "Ausente"}</td>
            </tr>
        </table>

        {bloque_imagen_html}

        <h3>3. Análisis Clínico Consolidado y Comparado (Plantilla vs. IA)</h3>
        <div class="concordancia-box">
            <p><b>Síntesis Comparativa: {html.escape(sintesis['titulo'])}</b></p>
            {html_sintesis_puntos}
        </div>
        <table width="100%" class="comp-table">
            <tr class="table-head">
                <td width="50%"><b>A. Informe por Plantilla Protocolizada (Sin IA)</b></td>
                <td width="50%"><b>B. {subtitulo_llm}</b></td>
            </tr>
            {''.join(filas_comparativas)}
        </table>

        <h3>4. Validación Clínica Presencial</h3>
        <table width="100%" class="sign-table">
            <tr>
                <td width="55%" valign="top">
                    <p><b>Observaciones del profesional tratante:</b></p>
                    <p>{obs_reg if obs_reg else "&nbsp;<br/>&nbsp;"}</p>
                </td>
                <td width="45%" valign="top">
                    <p><b>Profesional responsable:</b> {prof_reg if prof_reg else "___________________________"}</p>
                    <p>&nbsp;</p>
                    <p><b>Firma y Timbre:</b> ___________________________</p>
                </td>
            </tr>
        </table>

        <div class="disclaimer">
            <p><b>AVISO CLÍNICO OBLIGATORIO:</b> Este documento es generado por una herramienta de apoyo a la decisión clínica y <b>no constituye un diagnóstico médico definitivo</b> ni reemplaza la evaluación presencial de la paciente. El ensayo clínico multicéntrico INFANT (<i>The Lancet</i>, 2017) demostró que la interpretación automatizada de CTG requiere juicio clínico integral junto a los antecedentes obstétricos.</p>
        </div>
    </body>
    </html>
    """

    css_doc = """
    body {
        font-family: sans-serif;
        font-size: 9.5pt;
        line-height: 1.35;
        color: #1F2937;
    }
    h1 {
        font-size: 13pt;
        color: #0F2942;
        margin-bottom: 2pt;
    }
    h3 {
        font-size: 10.5pt;
        color: #0F2942;
        margin-top: 10pt;
        margin-bottom: 4pt;
    }
    .subtitle {
        font-size: 8.5pt;
        color: #4B5563;
        margin-top: 0pt;
        margin-bottom: 6pt;
    }
    .small {
        font-size: 8pt;
        color: #4B5563;
    }
    .header-box {
        border-bottom: 1.5pt solid #0F2942;
        padding-bottom: 4pt;
        margin-bottom: 6pt;
    }
    .meta-table {
        font-size: 8.5pt;
        background-color: #F3F4F6;
        border: 0.5pt solid #D1D5DB;
        padding: 4pt;
        margin-bottom: 6pt;
    }
    .cat-banner {
        padding: 6pt;
        border: 1pt solid #9CA3AF;
        margin-bottom: 8pt;
    }
    .params-table, .comp-table, .sign-table {
        border-collapse: collapse;
        margin-bottom: 8pt;
    }
    .params-table td, .comp-table td, .sign-table td {
        border: 0.5pt solid #CBD5E1;
        padding: 4pt 6pt;
        font-size: 8.5pt;
    }
    .table-head td {
        background-color: #E2E8F0;
        color: #0F2942;
        font-size: 9pt;
    }
    .dim-header {
        background-color: #F8FAFC;
        color: #1E3A8A;
        font-size: 9pt;
    }
    .concordancia-box {
        background-color: #F0F9FF;
        border: 0.5pt solid #7DD3FC;
        padding: 5pt 8pt;
        margin-bottom: 6pt;
        font-size: 8.5pt;
    }
    .cell-col p {
        margin-top: 2pt;
        margin-bottom: 3pt;
    }
    .cell-col ul {
        margin-top: 2pt;
        margin-bottom: 3pt;
        padding-left: 12pt;
    }
    .disclaimer {
        margin-top: 8pt;
        padding: 5pt;
        background-color: #FFFBEB;
        border: 0.5pt solid #F59E0B;
        font-size: 7.5pt;
        color: #78350F;
    }
    """

    pdf_buffer = io.BytesIO()
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (32, 32, -32, -32)  # márgenes de 32 pt (~1.1 cm)

    story = fitz.Story(html=html_doc, user_css=css_doc, archive=archive)
    writer = fitz.DocumentWriter(pdf_buffer)

    more = 1
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()

    return pdf_buffer.getvalue()

