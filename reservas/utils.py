"""
utils.py - Funciones auxiliares reutilizables.

Propósito: Centralizar pequeñas funciones que se usan en múltiples lugares.
Evita duplicación y mejora el principio DRY.

Estructura:
- Helpers de fecha/hora
- Helpers de formato
- Helpers de validación simple
"""

from datetime import timedelta
from typing import Tuple
from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de Fecha y Hora
# ─────────────────────────────────────────────────────────────────────────────

def obtener_rango_mes(anio: int, mes: int) -> Tuple[any, any]:
    """
    Obtiene los límites de un mes (primer y último segundo del mes).
    
    Parámetros:
        anio: Año
        mes: Mes (1-12)
    
    Retorna:
        (datetime inicio del mes, datetime fin del mes)
    
    Ejemplo:
        inicio, fin = obtener_rango_mes(2025, 5)
        # inicio = 2025-05-01 00:00:00
        # fin = 2025-05-31 23:59:59
    
    Nota: Útil para queries que filtran por rango de fecha.
          Centralizar aquí evita duplicar la lógica en múltiples selectors.
    """
    from datetime import datetime as dt
    
    inicio = dt(anio, mes, 1, 0, 0, 0)
    
    # Calcular último día del mes
    if mes == 12:
        fin = dt(anio + 1, 1, 1, 0, 0, 0) - timedelta(seconds=1)
    else:
        fin = dt(anio, mes + 1, 1, 0, 0, 0) - timedelta(seconds=1)
    
    return inicio, fin


def es_pasado(datetime_obj) -> bool:
    """
    Determina si un datetime ya pasó.
    
    Parámetros:
        datetime_obj: datetime a verificar
    
    Retorna:
        True si el datetime está en el pasado
    
    Nota: Compara con timezone.now() (timezone-aware).
    """
    return datetime_obj < timezone.now()


def minutos_hasta(datetime_obj) -> int:
    """
    Calcula minutos hasta un datetime futuro.
    
    Parámetros:
        datetime_obj: datetime destino
    
    Retorna:
        Minutos hasta ese momento (negativo si está en el pasado)
    """
    diff = datetime_obj - timezone.now()
    return int(diff.total_seconds() / 60)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de Formato
# ─────────────────────────────────────────────────────────────────────────────

def formatear_duracion(hora_inicio, hora_fin) -> str:
    """
    Formatea la duración entre dos datetimes de forma legible.
    
    Parámetros:
        hora_inicio: datetime de inicio
        hora_fin: datetime de fin
    
    Retorna:
        String formateado (ej: "2h 30min")
    
    Ejemplo:
        formatear_duracion(inicio, fin) → "2h 30min"
        formatear_duracion(inicio, fin) → "45min"
        formatear_duracion(inicio, fin) → "1h"
    """
    if not hora_fin:
        return "Indeterminado"
    
    diff = hora_fin - hora_inicio
    horas = diff.seconds // 3600
    minutos = (diff.seconds % 3600) // 60
    
    partes = []
    if horas > 0:
        partes.append(f"{horas}h")
    if minutos > 0:
        partes.append(f"{minutos}min")
    
    return " ".join(partes) if partes else "0min"


def formatear_hora_legible(datetime_obj) -> str:
    """
    Formatea un datetime de forma legible (ej: "15:30 - 24 May").
    
    Parámetros:
        datetime_obj: datetime a formatear
    
    Retorna:
        String formateado
    
    Nota: Útil para templates donde queremos mostrar horas de forma clara.
    """
    return datetime_obj.strftime("%H:%M - %d %b").capitalize()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de Validación
# ─────────────────────────────────────────────────────────────────────────────

def es_email_valido(email: str) -> bool:
    """
    Validación rápida de formato de email.
    
    Parámetros:
        email: String a validar
    
    Retorna:
        True si parece un email válido
    
    Nota: Esta es una validación básica. Django ya valida EmailField,
          esto es para validaciones adicionales en servicios.
    """
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def normalizar_nombre(nombre: str) -> str:
    """
    Normaliza un nombre: capitaliza palabras, elimina espacios extra.
    
    Parámetros:
        nombre: String a normalizar
    
    Retorna:
        String normalizado
    
    Ejemplo:
        normalizar_nombre("  juan  pérez  ") → "Juan Pérez"
    """
    return " ".join(palabra.capitalize() for palabra in nombre.split())
