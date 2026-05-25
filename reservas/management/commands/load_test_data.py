"""
load_test_data.py - Management command para cargar datos de prueba.

Propósito:
    Pobla la base de datos con datos realistas que permiten probar todas las
    funcionalidades del sistema de reservas (prioridades, colisiones, etc.).

Uso:
    python manage.py load_test_data

Datos generados:
    - 3 cargos (Decano, Secretario, Usuario) con prioridades
    - 3 usuarios por cada cargo (aprobados, pendientes, rechazados)
    - 5 vehículos disponibles
    - 10+ tickets de prueba con diferentes escenarios (sin conflictos, con conflictos, etc.)
    - Datos de fecha/hora realistas para simular reservas pasadas, actuales y futuras
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from reservas.models import Cargo, Usuario, Vehiculo, Ticket


class Command(BaseCommand):
    """
    Django management command para cargar datos de prueba en la BD.
    
    Hereda de BaseCommand y proporciona:
    - handle(): Método llamado por manage.py
    - self.stdout.write(): Para imprimir mensajes
    """
    
    help = "Carga datos de prueba para testear el sistema de reservas"

    def handle(self, *args, **options):
        """
        Punto de entrada del comando.
        
        Parámetros:
            *args: Argumentos posicionales (no usados aquí)
            **options: Opciones del comando (ej: --verbosity)
        
        Nota: Usa transacciones implícitas de Django para garantizar
        atomicidad (si falla algo, todo se revierte).
        """
        self.stdout.write("🔄 Iniciando carga de datos de prueba...\n")

        # Paso 1: Crear cargos
        cargos = self._crear_cargos()
        
        # Paso 2: Crear usuarios
        usuarios = self._crear_usuarios(cargos)
        
        # Paso 3: Crear vehículos
        vehiculos = self._crear_vehiculos()
        
        # Paso 4: Crear tickets/reservas con diferentes escenarios
        self._crear_tickets(usuarios, vehiculos)

        self.stdout.write(
            self.style.SUCCESS("✅ Datos de prueba cargados exitosamente!\n")
        )

    def _crear_cargos(self):
        """
        Crea los 3 cargos del sistema con sus prioridades.
        
        Prioridad: 0 (Decano) < 1 (Secretario) < 2 (Usuario)
        Menor número = Mayor autoridad
        
        Retorna:
            dict: {nombre_cargo: instancia_Cargo}
        """
        cargos_data = [
            (Cargo.DECANO, 0),
            (Cargo.SECRETARIO, 1),
            (Cargo.USUARIO, 2),
        ]
        
        cargos = {}
        for nombre, prioridad in cargos_data:
            cargo, creado = Cargo.objects.get_or_create(
                nombre=nombre,
                defaults={"prioridad": prioridad}
            )
            if creado:
                self.stdout.write(
                    f"  ✓ Cargo creado: {nombre} (prioridad {prioridad})"
                )
            else:
                self.stdout.write(
                    f"  → Cargo ya existe: {nombre}"
                )
            cargos[nombre] = cargo
        
        return cargos

    def _crear_usuarios(self, cargos):
        """
        Crea usuarios de prueba en diferentes estados.
        
        Parámetros:
            cargos: dict con instancias de Cargo
        
        Escenarios creados:
        - Decano: 1 aprobado, 1 pendiente, 1 rechazado
        - Secretario: 1 aprobado, 1 pendiente, 1 rechazado
        - Usuario: 1 aprobado, 1 pendiente, 1 rechazado
        
        Retorna:
            dict: {email: instancia_Usuario} de usuarios aprobados (para tickets)
        """
        usuarios_aprobados = {}
        
        usuarios_data = [
            # Decano
            {
                "cargo": cargos[Cargo.DECANO],
                "nombre": "Juan",
                "apellido": "García",
                "correo": "juan.garcia@universidad.edu",
                "contrasena": "decano123",
                "valido": True,
                "rechazado": False,
                "rol": "Decano (Aprobado)"
            },
            {
                "cargo": cargos[Cargo.DECANO],
                "nombre": "Carlos",
                "apellido": "López",
                "correo": "carlos.lopez@universidad.edu",
                "contrasena": "decano456",
                "valido": False,
                "rechazado": False,
                "rol": "Decano (Pendiente)"
            },
            {
                "cargo": cargos[Cargo.DECANO],
                "nombre": "Raúl",
                "apellido": "Martínez",
                "correo": "raul.martinez@universidad.edu",
                "contrasena": "decano789",
                "valido": False,
                "rechazado": True,
                "rol": "Decano (Rechazado)"
            },
            # Secretario
            {
                "cargo": cargos[Cargo.SECRETARIO],
                "nombre": "María",
                "apellido": "Fernández",
                "correo": "maria.fernandez@universidad.edu",
                "contrasena": "secretario123",
                "valido": True,
                "rechazado": False,
                "rol": "Secretario (Aprobado)"
            },
            {
                "cargo": cargos[Cargo.SECRETARIO],
                "nombre": "Rosa",
                "apellido": "Sánchez",
                "correo": "rosa.sanchez@universidad.edu",
                "contrasena": "secretario456",
                "valido": False,
                "rechazado": False,
                "rol": "Secretario (Pendiente)"
            },
            {
                "cargo": cargos[Cargo.SECRETARIO],
                "nombre": "Ana",
                "apellido": "Rodríguez",
                "correo": "ana.rodriguez@universidad.edu",
                "contrasena": "secretario789",
                "valido": False,
                "rechazado": True,
                "rol": "Secretario (Rechazado)"
            },
            # Usuario
            {
                "cargo": cargos[Cargo.USUARIO],
                "nombre": "Pedro",
                "apellido": "González",
                "correo": "pedro.gonzalez@universidad.edu",
                "contrasena": "usuario123",
                "valido": True,
                "rechazado": False,
                "rol": "Usuario (Aprobado)"
            },
            {
                "cargo": cargos[Cargo.USUARIO],
                "nombre": "Luis",
                "apellido": "Pérez",
                "correo": "luis.perez@universidad.edu",
                "contrasena": "usuario456",
                "valido": False,
                "rechazado": False,
                "rol": "Usuario (Pendiente)"
            },
            {
                "cargo": cargos[Cargo.USUARIO],
                "nombre": "Diego",
                "apellido": "Moreno",
                "correo": "diego.moreno@universidad.edu",
                "contrasena": "usuario789",
                "valido": False,
                "rechazado": True,
                "rol": "Usuario (Rechazado)"
            },
        ]
        
        for datos in usuarios_data:
            rol = datos.pop("rol")
            contrasena = datos.pop("contrasena")
            
            usuario, creado = Usuario.objects.get_or_create(
                correo=datos["correo"],
                defaults=datos
            )
            
            if creado:
                # Hashear la contraseña de forma segura
                usuario.set_password(contrasena)
                usuario.save()
                self.stdout.write(f"  ✓ Usuario creado: {rol}")
                
                # Guardar usuarios aprobados para usar en tickets
                if usuario.valido and not usuario.rechazado:
                    usuarios_aprobados[usuario.correo] = usuario
            else:
                self.stdout.write(f"  → Usuario ya existe: {rol}")
                if usuario.valido and not usuario.rechazado:
                    usuarios_aprobados[usuario.correo] = usuario
        
        return usuarios_aprobados

    def _crear_vehiculos(self):
        """
        Crea vehículos de prueba.
        
        Escenarios:
        - 5 vehículos disponibles con diferentes capacidades
        - 1 vehículo inactivo (dado de baja) para validar filtros
        
        Retorna:
            list: Instancias de Vehiculo disponibles
        """
        vehiculos_data = [
            {
                "marca": "Toyota",
                "modelo": "Hiace",
                "cant_pasajeros": 9,
                "placa": "UNIV-001",
                "activo": True,
            },
            {
                "marca": "Mercedes",
                "modelo": "Sprinter",
                "cant_pasajeros": 12,
                "placa": "UNIV-002",
                "activo": True,
            },
            {
                "marca": "Ford",
                "modelo": "Transit",
                "cant_pasajeros": 8,
                "placa": "UNIV-003",
                "activo": True,
            },
            {
                "marca": "Volkswagen",
                "modelo": "Transporter",
                "cant_pasajeros": 7,
                "placa": "UNIV-004",
                "activo": True,
            },
            {
                "marca": "Chevrolet",
                "modelo": "N300",
                "cant_pasajeros": 5,
                "placa": "UNIV-005",
                "activo": True,
            },
            # Vehículo inactivo (para validar que no se asigna)
            {
                "marca": "Fiat",
                "modelo": "Ducato",
                "cant_pasajeros": 6,
                "placa": "UNIV-OLD",
                "activo": False,
            },
        ]
        
        vehiculos = []
        for datos in vehiculos_data:
            activo = datos.get("activo", True)
            vehiculo, creado = Vehiculo.objects.get_or_create(
                placa=datos["placa"],
                defaults=datos
            )
            if creado:
                estado = "✓ Disponible" if activo else "✓ Inactivo"
                self.stdout.write(
                    f"  {estado}: {datos['marca']} {datos['modelo']} "
                    f"({datos['cant_pasajeros']} pasajeros) - {datos['placa']}"
                )
            else:
                self.stdout.write(
                    f"  → Vehículo ya existe: {datos['placa']}"
                )
            
            if activo:
                vehiculos.append(vehiculo)
        
        return vehiculos

    def _crear_tickets(self, usuarios_aprobados, vehiculos):
        """
        Crea tickets de prueba con diversos escenarios.
        
        Parámetros:
            usuarios_aprobados: dict de usuarios válidos para asignar
            vehiculos: list de vehículos disponibles
        
        Escenarios creados:
        1. Tickets sin conflictos (espacios libres)
        2. Tickets en el mismo rango (para validar detección de colisiones)
        3. Tickets pasados (histórico)
        4. Tickets pendientes de aprobación
        5. Tickets cancelados
        
        Nota: Los tickets se crean como APROBADOS directamente.
        La lógica de prioridad en crear_ticket_con_reglas() es un servicio
        que se testea por separado (vía servicios, no aquí).
        """
        ahora = timezone.now()
        usuarios_list = list(usuarios_aprobados.values())
        
        if not usuarios_list or not vehiculos:
            self.stdout.write(
                self.style.WARNING(
                    "⚠️ No hay suficientes usuarios o vehículos. "
                    "Saltando creación de tickets."
                )
            )
            return
        
        tickets_data = [
            # Scenario 1: Ticket pasado (histórico)
            {
                "usuario": usuarios_list[0],  # Juan García (Decano)
                "vehiculo": vehiculos[0],  # Toyota Hiace
                "destino": "Reunión en rectoría",
                "cant_pasajeros": 3,
                "descripcion": "Transporte del decano para reunión administrativa",
                "hora_inicio": ahora - timedelta(days=5, hours=2),
                "hora_fin": ahora - timedelta(days=5, hours=4),
                "estado": Ticket.ESTADO_APROBADO,
            },
            # Scenario 2: Ticket actual (en progreso)
            {
                "usuario": usuarios_list[1],  # María Fernández (Secretario)
                "vehiculo": vehiculos[1],  # Mercedes Sprinter
                "destino": "Visita a campus aliado",
                "cant_pasajeros": 8,
                "descripcion": "Transporte de estudiantes para visita académica",
                "hora_inicio": ahora - timedelta(hours=1),
                "hora_fin": ahora + timedelta(hours=3),
                "estado": Ticket.ESTADO_APROBADO,
            },
            # Scenario 3: Ticket futuro (sin conflictos)
            {
                "usuario": usuarios_list[2],  # Pedro González (Usuario)
                "vehiculo": vehiculos[2],  # Ford Transit
                "destino": "Conferencia en centro de convenciones",
                "cant_pasajeros": 5,
                "descripcion": "Transporte para asistir a conferencia académica",
                "hora_inicio": ahora + timedelta(days=7, hours=9),
                "hora_fin": ahora + timedelta(days=7, hours=17),
                "estado": Ticket.ESTADO_APROBADO,
            },
            # Scenario 4: Otro ticket futuro mismo vehículo (CONFLICTO POTENCIAL)
            {
                "usuario": usuarios_list[0],  # Juan García (Decano - mayor prioridad)
                "vehiculo": vehiculos[2],  # Ford Transit (mismo que scenario 3)
                "destino": "Inspección de instalaciones",
                "cant_pasajeros": 2,
                "descripcion": "Inspección de nuevas instalaciones académicas",
                "hora_inicio": ahora + timedelta(days=7, hours=10),  # Solapamiento
                "hora_fin": ahora + timedelta(days=7, hours=16),
                "estado": Ticket.ESTADO_APROBADO,
                "observacion": "Creado para probar reglas de jerarquía",
            },
            # Scenario 5: Ticket futuro diferente vehículo
            {
                "usuario": usuarios_list[1],  # María Fernández
                "vehiculo": vehiculos[3],  # Volkswagen Transporter
                "destino": "Seminario de educación",
                "cant_pasajeros": 4,
                "descripcion": "Transporte para seminario especializado",
                "hora_inicio": ahora + timedelta(days=14, hours=10),
                "hora_fin": ahora + timedelta(days=14, hours=14),
                "estado": Ticket.ESTADO_APROBADO,
            },
            # Scenario 6: Ticket cancelado por usuario
            {
                "usuario": usuarios_list[2],  # Pedro González
                "vehiculo": vehiculos[4],  # Chevrolet N300
                "destino": "Visita cancelada",
                "cant_pasajeros": 2,
                "descripcion": "Reserva que fue cancelada",
                "hora_inicio": ahora - timedelta(days=2, hours=10),
                "hora_fin": ahora - timedelta(days=2, hours=12),
                "estado": Ticket.ESTADO_CANCELADO,
                "observacion": "Cancelada por el usuario",
            },
            # Scenario 7: Ticket pendiente (estado intermedio)
            {
                "usuario": usuarios_list[0],  # Juan García
                "vehiculo": vehiculos[0],  # Toyota Hiace
                "destino": "Evento especial",
                "cant_pasajeros": 6,
                "descripcion": "Reserva en estado pendiente de aprobación",
                "hora_inicio": ahora + timedelta(days=30, hours=15),
                "hora_fin": ahora + timedelta(days=30, hours=20),
                "estado": Ticket.ESTADO_PENDIENTE,
            },
            # Scenario 8: Rango corto (sin hora_fin definida)
            {
                "usuario": usuarios_list[1],  # María Fernández
                "vehiculo": vehiculos[1],  # Mercedes Sprinter
                "destino": "Transporte punto a punto",
                "cant_pasajeros": 5,
                "descripcion": "Reserva sin hora de retorno definida",
                "hora_inicio": ahora + timedelta(days=21, hours=11),
                "hora_fin": None,  # Sin hora de fin
                "estado": Ticket.ESTADO_APROBADO,
            },
        ]
        
        contador = 0
        for datos in tickets_data:
            ticket, creado = Ticket.objects.get_or_create(
                id_usuario=datos["usuario"],
                id_vehiculo=datos["vehiculo"],
                hora_inicio=datos["hora_inicio"],
                defaults={k: v for k, v in datos.items() 
                         if k not in ["usuario", "vehiculo"]}
            )
            
            if creado:
                self.stdout.write(
                    f"  ✓ Ticket #{ticket.pk}: {datos['usuario'].nombre_completo} "
                    f"→ {datos['destino']} "
                    f"(Estado: {datos['estado']})"
                )
                contador += 1
            else:
                self.stdout.write(
                    f"  → Ticket ya existe: #{ticket.pk}"
                )
        
        self.stdout.write(f"\n  📊 Total tickets creados: {contador}")
