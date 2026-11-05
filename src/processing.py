"""Procesamiento básico de registros de Frecuencia Cardíaca Fetal (FCF)."""

import os

import pandas as pd

import rutas

# Rango clínico normal de FCF (latidos por minuto)
FCF_MIN_NORMAL = 110
FCF_MAX_NORMAL = 160


def procesar_mefi(ruta_archivo):
    """Lee un CSV de monitoreo fetal desde data/ y calcula media y variabilidad de la FCF.

    Args:
        ruta_archivo: nombre del archivo CSV dentro de la carpeta data/.

    Returns:
        dict con 'media_fcf' y 'std_fcf'.
    """
    # Construir la ruta completa al archivo dentro de data/ (escribible
    # segun rutas: MEFI_HOME en instalado, raiz del proyecto en desarrollo)
    ruta_completa = os.path.join(str(rutas.ruta_escritura("data")), ruta_archivo)

    # Leer el archivo CSV en un DataFrame de pandas
    df = pd.read_csv(ruta_completa)

    # Verificar que las columnas necesarias existan antes de procesar
    columnas_requeridas = {"tiempo", "fcf"}
    columnas_faltantes = columnas_requeridas - set(df.columns)
    if columnas_faltantes:
        raise ValueError(
            f"El archivo {ruta_archivo} no contiene las columnas requeridas: {columnas_faltantes}"
        )

    # Calcular la media y la desviación estándar (variabilidad) de la FCF
    media_fcf = df["fcf"].mean()
    std_fcf = df["fcf"].std()

    # Alertar si la FCF media está fuera del rango clínico normal
    if media_fcf < FCF_MIN_NORMAL or media_fcf > FCF_MAX_NORMAL:
        print(
            f"ADVERTENCIA: FCF media ({media_fcf:.1f} lpm) fuera del rango "
            f"normal ({FCF_MIN_NORMAL}-{FCF_MAX_NORMAL} lpm)."
        )

    return {"media_fcf": media_fcf, "std_fcf": std_fcf}


if __name__ == "__main__":
    # Ejemplo de uso: procesar_mefi("sample.csv")
    resultado = procesar_mefi("sample.csv")
    print(resultado)
