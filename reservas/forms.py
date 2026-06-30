"""
Forms para validación y captura de datos del sistema de reservas.

Incluye formularios para autenticación, creación de tickets,
búsqueda y administración de vehículos. Todos heredan de Django forms
y aplican validaciones tanto a nivel de campo como de formulario.

Convención de sesión utilizada en vistas:
    request.session["usuario_id"]   → PK del usuario logueado
    request.session["es_admin"]     → bool (True si prioridad == 0)
"""

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Usuario, Cargo, Vehiculo, Ticket


# ══════════════════════════════════════════════
# Épica 1 — Autenticación
# ══════════════════════════════════════════════

class RegistroForm(forms.ModelForm):
    """
    Formulario para registro de cuenta de usuario (HU 1.1).

    Valida que las contraseñas coincidan y asegura que los nuevos
    usuarios se crean con estado pendiente (valido=False, rechazado=False).

    Fields:
        nombre (CharField): Nombre de pila.
        apellido (CharField): Apellido.
        correo (EmailField): Email único (validado por modelo).
        id_cargo (ModelChoiceField): Cargo a solicitar.
        contrasena (CharField): Contraseña en texto plano (se hashea en save()).
        confirmar_contrasena (CharField): Validación de coincidencia.

    Validaciones:
        - Las dos contraseñas deben coincidir (método clean).
        - Email debe ser único (validación del modelo).

    Save behavior:
        - Hashea la contraseña usando Usuario.set_password().
        - Establece valido=False y rechazado=False por defecto.
    """

    contrasena = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Contraseña"}),
        label="Contraseña",
    )
    confirmar_contrasena = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Confirmar contraseña"}),
        label="Confirmar contraseña",
    )

    class Meta:
        model = Usuario
        fields = ["nombre", "apellido", "correo", "id_cargo", "departamento", "contrasena"]
        labels = {
            "nombre": "Nombre",
            "apellido": "Apellido",
            "correo": "Correo electrónico",
            "id_cargo": "Cargo",
            "departamento": "Departamento",
        }
        widgets = {
            "nombre":   forms.TextInput(attrs={"placeholder": "Nombre"}),
            "apellido": forms.TextInput(attrs={"placeholder": "Apellido"}),
            "correo":   forms.EmailInput(attrs={"placeholder": "correo@empresa.com"}),
            "departamento": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        """
        Inicializa el formulario excluyendo el cargo de Administrador (prioridad 0).
        """
        super().__init__(*args, **kwargs)
        self.fields["id_cargo"].queryset = Cargo.objects.exclude(prioridad=0)

    def clean(self):
        """
        Valida que ambas contraseñas coincidan y la lógica del departamento.
        """
        cleaned = super().clean()
        p1 = cleaned.get("contrasena")
        p2 = cleaned.get("confirmar_contrasena")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Las contraseñas no coinciden.")
            
        cargo = cleaned.get("id_cargo")
        departamento = cleaned.get("departamento")
        if cargo and cargo.nombre == Cargo.USUARIO:
            if not departamento:
                self.add_error("departamento", "Debe seleccionar un departamento si su cargo es Usuario.")
        else:
            if "departamento" in cleaned:
                cleaned["departamento"] = None
                
        return cleaned

    def save(self, commit=True):
        """
        Guarda el usuario con contraseña hasheada y estado inicial.

        Args:
            commit (bool): Si False, retorna instancia sin guardar en BD.

        Returns:
            Usuario: Instancia guardada o no según commit.

        Notes:
            Se aseguran los valores iniciales:
            - valido=False (requiere aprobación del admin).
            - rechazado=False (no está explícitamente rechazado).
        """
        usuario = super().save(commit=False)
        usuario.set_password(self.cleaned_data["contrasena"])
        usuario.valido = False
        usuario.rechazado = False
        if commit:
            usuario.save()
        return usuario


class AdminCrearUsuarioForm(RegistroForm):
    """
    Formulario para que el administrador cree usuarios directamente (validados).
    Permite asignar cualquier cargo, incluyendo Administrador.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # El administrador puede asignar cualquier cargo
        self.fields["id_cargo"].queryset = Cargo.objects.all()

    def save(self, commit=True):
        usuario = super(RegistroForm, self).save(commit=False)
        usuario.set_password(self.cleaned_data["contrasena"])
        # Los usuarios creados por el admin nacen válidos y verificados
        usuario.valido = True
        usuario.rechazado = False
        usuario.correo_verificado = True
        if commit:
            usuario.save()
        return usuario


class AdminEditarUsuarioForm(forms.ModelForm):
    """
    Formulario para que el administrador edite datos de un usuario existente.
    """
    class Meta:
        model = Usuario
        fields = ["nombre", "apellido", "correo", "id_cargo", "departamento", "valido"]
        labels = {
            "nombre": "Nombre",
            "apellido": "Apellido",
            "correo": "Correo electrónico",
            "id_cargo": "Cargo",
            "departamento": "Departamento",
            "valido": "Usuario activo (válido)",
        }
        widgets = {
            "nombre":   forms.TextInput(attrs={"placeholder": "Nombre", "class": "form-control"}),
            "apellido": forms.TextInput(attrs={"placeholder": "Apellido", "class": "form-control"}),
            "correo":   forms.EmailInput(attrs={"placeholder": "correo@empresa.com", "class": "form-control"}),
            "id_cargo": forms.Select(attrs={"class": "form-control"}),
            "departamento": forms.Select(attrs={"class": "form-control"}),
            "valido": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["id_cargo"].queryset = Cargo.objects.all()

    def clean(self):
        cleaned = super().clean()
        cargo = cleaned.get("id_cargo")
        departamento = cleaned.get("departamento")
        if cargo and cargo.nombre == Cargo.USUARIO:
            if not departamento:
                self.add_error("departamento", "Debe seleccionar un departamento si el cargo es Usuario.")
        else:
            if "departamento" in cleaned:
                cleaned["departamento"] = None
        return cleaned

    def clean_valido(self):
        valido = self.cleaned_data.get("valido")
        # Si se intenta desactivar y el usuario es Administrador SEU
        if not valido and self.instance.pk and self.instance.id_cargo.prioridad == 0:
            raise ValidationError("No podés desactivar a un Administrador SEU.")
        return valido

    def save(self, commit=True):
        usuario = super().save(commit=False)
        # Sincronizamos el campo rechazado con valido para que no vuelva al estado pendiente
        if not usuario.valido:
            usuario.rechazado = True
        else:
            usuario.rechazado = False
        if commit:
            usuario.save()
        return usuario

class LoginForm(forms.Form):
    """
    Formulario para inicio de sesión (HU 1.2).

    Captura credenciales sin crear registros en BD. La autenticación
    se realiza manualmente en vistas.login_view() contra Usuario.check_password().

    Fields:
        correo (EmailField): Identificador único del usuario.
        contrasena (CharField): Contraseña en texto plano.
    """

    correo = forms.EmailField(
        widget=forms.EmailInput(attrs={"placeholder": "correo@empresa.com"}),
        label="Correo electrónico",
    )
    contrasena = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Contraseña"}),
        label="Contraseña",
    )


# ══════════════════════════════════════════════
# Épica 2 — Creación de Tickets
# ══════════════════════════════════════════════

class TicketForm(forms.ModelForm):
    """
    Formulario para creación rápida de ticket (HU 2.1).

    Captura datos de una reserva de vehículo. Solo muestra vehículos
    activos. La validación temporal y la lógica de conflictos se aplican
    en services.crear_ticket_con_reglas() (HU 4.2, 4.3).

    Fields:
        id_vehiculo (ModelChoiceField): Vehículo a reservar (solo activos).
        destino (CharField): Ubicación de viaje.
        cant_pasajeros (PositiveIntegerField): Ocupantes.
        descripcion (TextField): Motivo, notas.
        hora_inicio (DateTimeField): Fecha y hora de salida.
        hora_fin (DateTimeField, optional): Estimado de regreso.

    Validaciones:
        - hora_inicio debe ser en el futuro.
        - hora_fin, si se proporciona, debe ser > hora_inicio.
        - hora_fin es opcional en el formulario pero requerido en servicios
          (vistas asignan default si está vacío).

    Notes:
        No valida la capacidad del vehículo vs. pasajeros solicitados.
        Esa lógica puede añadirse a nivel de servicios en futuras iteraciones.
    """

    tercero_nombre = forms.CharField(required=False, label="Nombre de la persona")
    tercero_contacto = forms.CharField(required=False, label="Información de contacto (teléfono o correo)")

    class Meta:
        model = Ticket
        fields = ["id_vehiculo", "destino", "cant_pasajeros", "descripcion", "hora_inicio", "hora_fin", "requiere_chofer", "para_tercero"]
        labels = {
            "id_vehiculo":    "Vehículo",
            "destino":        "Destino",
            "cant_pasajeros": "Cantidad de pasajeros",
            "descripcion":    "Descripción / motivo",
            "hora_inicio":    "Fecha y hora de salida",
            "hora_fin":       "Fecha y hora de regreso (estimado)",
        }
        widgets = {
            "destino":     forms.TextInput(attrs={"placeholder": "Ej: San Martín 1050, San Miguel de Tucumán"}),
            "descripcion": forms.Textarea(attrs={"rows": 3, "placeholder": "Motivo del viaje"}),
            "hora_inicio": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}, format="%Y-%m-%dT%H:%M"
            ),
            "hora_fin": forms.DateTimeInput(
                attrs={"type": "datetime-local", "class": "form-control"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, **kwargs):
        """
        Inicializa el formulario con configuración de campos.

        - Filtra vehículos para mostrar solo los activos.
        - Establece formatos de entrada para datetime.
        - hora_fin es opcional (required=False).
        """
        self.es_admin = kwargs.pop('es_admin', False)
        self.es_usuario_general = kwargs.pop('es_usuario_general', False)
        super().__init__(*args, **kwargs)
        # Solo mostrar vehículos activos
        self.fields["id_vehiculo"].queryset = Vehiculo.objects.filter(activo=True)
        self.fields["hora_inicio"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["hora_fin"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["hora_fin"].required = False
        self.fields["descripcion"].required = True

    def clean(self):
        """
        Valida la lógica temporal del ticket y comprueba la validez del destino.

        Raises:
            ValidationError: Si incumple reglas de tiempo o si el destino no es válido.

        Returns:
            dict: Datos limpios del formulario.
        """
        from datetime import timedelta
        import requests
        
        cleaned = super().clean()
        hora_inicio = cleaned.get("hora_inicio")
        hora_fin = cleaned.get("hora_fin")
        destino = cleaned.get("destino")
        ahora = timezone.now()

        if hora_inicio:
            if not self.es_admin:
                if hora_inicio <= ahora:
                    raise ValidationError("La fecha de inicio debe ser en el futuro.")
                
                if hora_inicio > ahora + timedelta(days=60):
                    self.add_error("hora_inicio", "No se pueden realizar reservas con más de 2 meses (60 días) de antelación.")
                    
                if hora_inicio < ahora + timedelta(days=3):
                    self.add_error("hora_inicio", "Debe reservar con al menos 3 días de anticipación.")

        if hora_inicio and hora_fin:
            if hora_fin <= hora_inicio:
                self.add_error("hora_fin", "La hora de regreso debe ser posterior a la de salida.")

        para_tercero = cleaned.get("para_tercero")
        if para_tercero:
            tercero_nombre = cleaned.get("tercero_nombre")
            tercero_contacto = cleaned.get("tercero_contacto")
            if not tercero_nombre or not tercero_contacto:
                self.add_error("para_tercero", "Debe completar el nombre y contacto de la persona para la cual solicita el ticket.")
            else:
                desc = cleaned.get("descripcion", "")
                nueva_desc = f"{desc}\n\n[Solicitado para tercero]\nNombre: {tercero_nombre}\nContacto: {tercero_contacto}"
                cleaned["descripcion"] = nueva_desc

        if self.es_usuario_general:
            cleaned["requiere_chofer"] = True

        return cleaned


# ══════════════════════════════════════════════
# Épica 3 — Consulta de Calendario
# ══════════════════════════════════════════════

class VehiculoSelectorForm(forms.Form):
    """
    Formulario para seleccionar vehículo en vista de calendario (HU 3.1, 3.2).

    Fields:
        vehiculo (ModelChoiceField): Vehículo cuyo calendario se quiere ver.
            Solo muestra vehículos activos.
    """

    vehiculo = forms.ModelChoiceField(
        queryset=Vehiculo.objects.filter(activo=True),
        label="Seleccionar vehículo",
        empty_label="-- Elegir vehículo --",
    )


# ══════════════════════════════════════════════
# Épica 5 — Administración
# ══════════════════════════════════════════════

class FiltroUsuariosForm(forms.Form):
    """
    Formulario de filtrado para directorio de usuarios (HU 5.1).

    Permite buscar usuarios por nombre/apellido/correo y filtrar por cargo.

    Fields:
        busqueda (CharField): Búsqueda libre (icontains en BD).
        cargo (ModelChoiceField): Filtro por cargo (opcional).
    """

    busqueda = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Buscar por nombre o correo..."}),
        label="",
    )
    cargo = forms.ModelChoiceField(
        queryset=Cargo.objects.all(),
        required=False,
        empty_label="Todos los cargos",
        label="Cargo",
    )


class FiltroTicketsForm(forms.Form):
    """
    Formulario de filtrado para monitor de tickets y auditoría.

    Permite buscar tickets por solicitante o destino, y filtrar por vehículo.
    """

    busqueda = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Buscar por solicitante o destino..."}),
        label="",
    )
    conductor = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Buscar por conductor..."}),
        label="Conductor",
    )
    vehiculo = forms.ModelChoiceField(
        queryset=Vehiculo.objects.all(),
        required=False,
        empty_label="Todos los vehículos",
        label="Vehículo",
    )
    cargo = forms.ModelChoiceField(
        queryset=Cargo.objects.all(),
        required=False,
        empty_label="Todos los cargos",
        label="Cargo",
    )
    fecha_inicio = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        label="Desde",
    )
    fecha_fin = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        label="Hasta",
    )



# ══════════════════════════════════════════════
# Épica 6 — ABM de Vehículos
# ══════════════════════════════════════════════

class VehiculoForm(forms.ModelForm):
    """
    Formulario para alta y edición de vehículos (HU 6.2, 6.3).

    Permite crear y modificar registros de vehículos en los vehículos.
    El flag 'activo' controla si el vehículo aparece en formularios de reserva.

    Fields:
        marca (CharField): Fabricante del vehículo.
        modelo (CharField): Modelo específico.
        cant_pasajeros (PositiveIntegerField): Capacidad.
        activo (BooleanField): Disponibilidad operativa.
    """

    class Meta:
        model = Vehiculo
        fields = ["marca", "modelo", "patente", "cant_pasajeros", "activo", "exclusivo_decanato", "requiere_chofer"]
        labels = {
            "marca":          "Marca",
            "modelo":         "Modelo",
            "patente":        "Patente (Dominio)",
            "cant_pasajeros": "Capacidad de pasajeros",
            "activo":         "Vehículo activo (disponible para reservas)",
            "exclusivo_decanato": "Exclusivo del Decano",
            "requiere_chofer": "Requiere Chofer asignado",
        }
        widgets = {
            "marca":  forms.TextInput(attrs={"placeholder": "Ej: Toyota"}),
            "modelo": forms.TextInput(attrs={"placeholder": "Ej: Hilux 2023"}),
            "patente": forms.TextInput(attrs={"placeholder": "Ej: AB 123 CD"}),
        }



# ══════════════════════════════════════════════
# NUEVO: Verificación de correo electrónico
# ══════════════════════════════════════════════

class VerificacionCodigoForm(forms.Form):
    """
    Formulario para ingresar el código de 6 dígitos (extensión HU 1.1).

    Se muestra en /verificar-correo/ inmediatamente después del registro.
    Solo acepta dígitos. La validación de vigencia y corrección del código
    se delega a email_verification.verificar_por_codigo(), no a este form.

    Fields:
        codigo (CharField): Código numérico de 6 dígitos recibido por email.

    Atributos del widget:
        inputmode="numeric"        → teclado numérico en dispositivos móviles.
        autocomplete="one-time-code" → autorrelleno en navegadores modernos
                                       (Chrome, Safari sugieren el SMS/email code).

    Validaciones propias:
        - Exactamente 6 caracteres (min_length + max_length del CharField).
        - Solo dígitos numéricos (clean_codigo, no se aceptan letras ni símbolos).
    """

    codigo = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            "placeholder": "000000",
            "inputmode": "numeric",
            "autocomplete": "one-time-code",
            # Estilo tipo OTP: centrado, grande y espaciado para fácil lectura
            "style": (
                "text-align:center;"
                "font-size:28px;"
                "letter-spacing:10px;"
                "font-family:monospace;"
            ),
        }),
        label="Código de verificación",
        error_messages={
            "min_length": "El código debe tener exactamente 6 dígitos.",
            "max_length": "El código debe tener exactamente 6 dígitos.",
            "required":   "Ingresá el código de 6 dígitos enviado a tu correo.",
        }
    )

    def clean_codigo(self):
        """
        Valida que el código contenga únicamente caracteres numéricos.

        Se ejecuta automáticamente por Django al llamar form.is_valid().
        Elimina espacios accidentales antes de validar.

        Returns:
            str: Código limpio sin espacios.

        Raises:
            ValidationError: Si contiene letras, símbolos u otros no-dígitos.
        """
        codigo = self.cleaned_data.get("codigo", "").strip()
        if not codigo.isdigit():
            raise ValidationError("El código debe contener solo números (sin letras ni símbolos).")
        return codigo

# ══════════════════════════════════════════════════════════════════════════════
# Formularios de Recuperación de Contraseña
# ══════════════════════════════════════════════════════════════════════════════

class SolicitarRecuperacionForm(forms.Form):
    correo = forms.EmailField(
        label="Correo electrónico",
        widget=forms.EmailInput(attrs={"placeholder": "tu.nombre@universidad.edu.ar"})
    )

class VerificarRecuperacionForm(forms.Form):
    codigo = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            "placeholder": "······",
            "autocomplete": "one-time-code",
            "style": "text-align:center; font-size:28px; letter-spacing:10px; font-family:monospace;"
        }),
        error_messages={
            "min_length": "El código debe tener exactamente 6 dígitos.",
            "max_length": "El código debe tener exactamente 6 dígitos.",
            "required":   "Ingresá el código de 6 dígitos enviado a tu correo.",
        }
    )

    def clean_codigo(self):
        codigo = self.cleaned_data.get("codigo", "").strip()
        if not codigo.isdigit():
            raise forms.ValidationError("El código debe contener solo números.")
        return codigo

class NuevaContrasenaForm(forms.Form):
    contrasena_nueva = forms.CharField(
        label="Nueva contraseña",
        widget=forms.PasswordInput(attrs={"placeholder": "Mínimo 8 caracteres"}),
        min_length=8
    )
    contrasena_confirmacion = forms.CharField(
        label="Confirmar contraseña",
        widget=forms.PasswordInput(attrs={"placeholder": "Repetí tu nueva contraseña"}),
        min_length=8
    )

    def clean(self):
        cleaned_data = super().clean()
        c1 = cleaned_data.get("contrasena_nueva")
        c2 = cleaned_data.get("contrasena_confirmacion")
        if c1 and c2 and c1 != c2:
            raise forms.ValidationError("Las contraseñas no coinciden.")
        return cleaned_data
