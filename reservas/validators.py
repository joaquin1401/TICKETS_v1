"""
validators.py - Validadores personalizados para modelos y formularios.

Patrón: Validadores reutilizables
──────────────────────────────
Django permite separar validaciones en funciones reutilizables.
Esto evita duplicación en models.py, forms.py y serializers.

Beneficios:
✓ Validaciones centralizadas
✓ Reutilizables en forms, models y APIs
✓ Fácil de testear independientemente
✓ Claridad sobre reglas de negocio
"""

from datetime import datetime, timedelta
from django.core.exceptions import ValidationError
from django.utils import timezone
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Validadores de Usuario
# ─────────────────────────────────────────────────────────────────────────────

def validar_contrasena_fuerte(password: str) -> None:
    """
    Valida que la contraseña cumpla requisitos mínimos de seguridad.
    
    Parámetros:
        password: Contraseña a validar
    
    Lanza:
        ValidationError si no cumple requisitos
    
    Requisitos:
        - Mínimo 8 caracteres
        - Al menos 1 mayúscula
        - Al menos 1 minúscula
        - Al menos 1 número
    
    Uso:
        from django.core.exceptions import ValidationError
        try:
            validar_contrasena_fuerte(password)
        except ValidationError as e:
            # manejar error
    """
    if len(password) < 8:
        raise ValidationError("La contraseña debe tener al menos 8 caracteres.")
    
    if not any(c.isupper() for c in password):
        raise ValidationError("La contraseña debe tener al menos una mayúscula.")
    
    if not any(c.islower() for c in password):
        raise ValidationError("La contraseña debe tener al menos una minúscula.")
    
    if not any(c.isdigit() for c in password):
        raise ValidationError("La contraseña debe tener al menos un número.")


# ─────────────────────────────────────────────────────────────────────────────
# Validadores de Ticket
# ─────────────────────────────────────────────────────────────────────────────

def validar_rango_horario(hora_inicio: datetime, hora_fin: Optional[datetime]) -> None:
    """
    Valida que el rango horario del ticket sea válido.
    
    Parámetros:
        hora_inicio: Datetime de inicio
        hora_fin: Datetime de fin (opcional)
    
    Lanza:
        ValidationError si el rango es inválido
    
    Reglas:
        - hora_inicio no puede estar en el pasado
        - hora_fin (si existe) debe ser > hora_inicio
        - El rango no puede ser muy largo (máximo 24 horas)
    
    Nota: Separa reglas de validación de la lógica de negocio.
          La detección de conflictos está en services.py, no aquí.
    """
    ahora = timezone.now()
    
    # Validar que hora_inicio sea futura
    if hora_inicio <= ahora:
        raise ValidationError("La hora de inicio debe ser en el futuro.")
    
    # Si hay hora_fin, validar
    if hora_fin:
        if hora_fin <= hora_inicio:
            raise ValidationError(
                "La hora de fin debe ser posterior a la hora de inicio."
            )
        
        # Validar que no sea más de 24 horas
        duracion = hora_fin - hora_inicio
        if duracion > timedelta(hours=24):
            raise ValidationError(
                "El viaje no puede durar más de 24 horas."
            )


def validar_cantidad_pasajeros(cant_pasajeros: int, vehiculo_max: int) -> None:
    """
    Valida que la cantidad de pasajeros sea válida para el vehículo.
    
    Parámetros:
        cant_pasajeros: Cantidad de pasajeros a reservar
        vehiculo_max: Capacidad máxima del vehículo
    
    Lanza:
        ValidationError si excede capacidad
    
    Nota: Esta validación debe ejecutarse antes de crear el ticket
          para garantizar integridad de datos.
    """
    if cant_pasajeros <= 0:
        raise ValidationError("La cantidad de pasajeros debe ser mayor a 0.")
    
    if cant_pasajeros > vehiculo_max:
        raise ValidationError(
            f"El vehículo tiene capacidad para {vehiculo_max} pasajeros, "
            f"no puede reservar {cant_pasajeros}."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Validadores de Cargo
# ─────────────────────────────────────────────────────────────────────────────

def validar_prioridad_unica(prioridad: int, exclude_cargo_id: Optional[int] = None) -> None:
    """
    Valida que no exista otro cargo con la misma prioridad.
    
    Parámetros:
        prioridad: Número de prioridad a validar
        exclude_cargo_id: ID de cargo a excluir (útil para ediciones)
    
    Lanza:
        ValidationError si ya existe cargo con esa prioridad
    
    Nota: Esta validación debe llamarse desde forms.py o admin.py
          cuando se crea/edita un cargo.
    """
    from .models import Cargo
    
    query = Cargo.objects.filter(prioridad=prioridad)
    if exclude_cargo_id:
        query = query.exclude(pk=exclude_cargo_id)
    
    if query.exists():
        raise ValidationError(
            f"Ya existe un cargo con prioridad {prioridad}."
        )
