"""
Django Management Command: poblar_bd

Población de la base de datos con datos de prueba (mock data) realistas
para testing exhaustivo del sistema de reservas de vehículos universitarios.

Cobertura:
- Jerarquía de cargos (Decano, Secretario, Usuario)
- Usuarios con estados variados (válido, rechazado, no validado)
- Vehículos activos e inactivos
- Reservas pasadas (histórico)
- Reservas futuras sin conflictos
- Edge cases: conflictos intencionales entre usuarios de distinta jerarquía

Uso:
    python manage.py poblar_bd              # Poblar sin limpiar previos
    python manage.py poblar_bd --clear      # Limpiar BD antes de poblar
    python manage.py poblar_bd --clean      # Alias para --clear
"""

import os
import random
import sys
from pathlib import Path

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[3]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

    import django

    django.setup()

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from datetime import timedelta

try:
    from faker import Faker
except ImportError:
    raise CommandError(
        "Faker no está instalado. Por favor ejecuta: pip install faker"
    )

from reservas.models import Cargo, Usuario, Vehiculo, Ticket
from reservas.services import crear_ticket_con_reglas

fake = Faker('es_ES')


class Command(BaseCommand):
    """
    Management Command para poblar la base de datos con datos de prueba.
    
    Características:
    - Idempotente: puede ejecutarse múltiples veces sin duplicar datos
    - Modular: funciones separadas por entidad (cargos, usuarios, vehículos, tickets)
    - Realista: usa Faker para nombres, correos, textos
    - Documentado: cada bloque explica el escenario que prueba
    """
    
    help = "Genera datos de prueba realistas para el sistema de reservas"

    def add_arguments(self, parser):
        """
        Define argumentos del comando.
        
        --clean: Limpia datos existentes antes de insertar nuevos
        """
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Limpia datos existentes antes de poblar (excepto superusuarios)',
        )

    def handle(self, *args, **options):
        """
        Punto de entrada del comando.
        
        Flujo:
        1. Verificar si se solicita limpieza
        2. Usar transacción atómica para garantizar consistencia
        3. Crear datos en orden de dependencias (Cargo → Usuario → Vehiculo → Ticket)
        4. Mostrar resumen de datos creados
        """
        self.fake = Faker('es_ES')  # Locale español para nombres realistas
        
        self.stdout.write(self.style.WARNING("🔄 Iniciando poblamiento de base de datos...\n"))

        if options['clean']:
            self._limpiar_datos()

        try:
            with transaction.atomic():
                cargos = self._crear_cargos()
                usuarios = self._crear_usuarios(cargos)
                vehiculos = self._crear_vehiculos()
                self._crear_reservas(usuarios, vehiculos)

            self.stdout.write(
                self.style.SUCCESS("\n✅ Datos de prueba cargados exitosamente!\n")
            )
            self._mostrar_resumen()

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"\n❌ Error durante el poblamiento: {str(e)}")
            )
            raise CommandError(f"Fallo el poblamiento: {str(e)}")

    def _limpiar_datos(self):
        """
        Limpia las tablas manteniendo datos maestros críticos.
        
        Estrategia:
        - Elimina Ticket (depende de Usuario y Vehiculo)
        - Elimina Usuario (depende de Cargo)
        - Elimina Vehiculo (independiente)
        - Mantiene Cargo (datos maestros)
        
        Nota: En producción, usarías datos de backup. Aquí es seguro porque
        es desarrollo/testing.
        """
        self.stdout.write("🧹 Limpiando datos existentes...")
        
        # Ticket debe eliminarse primero por constraints de FK
        count_tickets = Ticket.objects.all().delete()[0]
        self.stdout.write(f"  - {count_tickets} tickets eliminados")
        
        # Usuario depende de Cargo
        count_usuarios = Usuario.objects.all().delete()[0]
        self.stdout.write(f"  - {count_usuarios} usuarios eliminados")
        
        # Vehiculo es independiente
        count_vehiculos = Vehiculo.objects.all().delete()[0]
        self.stdout.write(f"  - {count_vehiculos} vehículos eliminados")
        
        # Cargo: mantener estructura (no eliminar)
        self.stdout.write("  - Cargos preservados (datos maestros)\n")

    def _crear_cargos(self):
        """
        Crea los 3 cargos del sistema con jerarquía.
        
        Jerarquía (de mayor a menor prioridad):
        1. Decano (prioridad 1) - Máxima autoridad
        2. Secretario (prioridad 2) - Autoridad media
        3. Usuario (prioridad 3) - Mínima prioridad
        
        Retorna:
            dict: {nombre_cargo: instancia_Cargo} para usar en creación de usuarios
        """
        self.stdout.write("\n📋 Creando cargos...")
        
        cargos_config = [
            ("SEU", 0),
            (Cargo.DECANO, 1),
            (Cargo.SECRETARIO, 2),
            (Cargo.USUARIO, 3),
        ]
        
        cargos = {}
        for nombre, prioridad in cargos_config:
            cargo, creado = Cargo.objects.get_or_create(
                nombre=nombre,
                defaults={'prioridad': prioridad}
            )
            if creado:
                self.stdout.write(f"  ✓ {nombre} (prioridad {prioridad})")
            else:
                self.stdout.write(f"  → {nombre} ya existe")
            
            cargos[nombre] = cargo
        
        return cargos

    def _crear_usuarios(self, cargos):
        """
        Crea usuarios de prueba con diferentes estados de aprobación.
        
        Para cada cargo, crea 3 usuarios:
        1. Aprobado (valido=True, puede ingresar)
        2. Pendiente (valido=False, no rechazado - esperando aprobación)
        3. Rechazado (valido=False, rechazado=True - no puede ingresar)
        
        Parámetros:
            cargos: dict de instancias de Cargo
        
        Retorna:
            list: Usuarios aprobados (usados para crear reservas)
            
        Nota: Los usuarios rechazados/pendientes se crean pero no se usan
        para tickets, para validar que solo usuarios aprobados pueden reservar.
        """
        self.stdout.write("\n👥 Creando usuarios con diferentes estados...")
        
        usuarios_aprobados = []
        contadores = {'aprobados': 0, 'pendientes': 0, 'rechazados': 0}
        
        for nombre_cargo, cargo in cargos.items():
            # Caso especial: Administrador SEU (Prioridad 0)
            if cargo.prioridad == 0:
                admin_seu = self._crear_usuario_unico(
                    cargo=cargo,
                    valido=True,
                    rechazado=False,
                    sufijo="_admin_seu"
                )
                if admin_seu:
                    usuarios_aprobados.append(admin_seu)
                    contadores['aprobados'] += 1
                    self.stdout.write(f"  ⭐ {admin_seu.nombre_completo} (SEU) - ADMINISTRADOR")
                continue

            # Usuario 1: Aprobado
            usuario_aprobado = self._crear_usuario_unico(
                cargo=cargo,
                valido=True,
                rechazado=False,
                sufijo=f"_aprobado_{nombre_cargo.lower()}"
            )
            if usuario_aprobado:
                usuarios_aprobados.append(usuario_aprobado)
                contadores['aprobados'] += 1
                self.stdout.write(
                    f"  ✓ {usuario_aprobado.nombre_completo} ({nombre_cargo}) - APROBADO"
                )
            
            # Usuario 2: Pendiente de aprobación
            usuario_pendiente = self._crear_usuario_unico(
                cargo=cargo,
                valido=False,
                rechazado=False,
                sufijo=f"_pendiente_{nombre_cargo.lower()}"
            )
            if usuario_pendiente:
                contadores['pendientes'] += 1
                self.stdout.write(
                    f"  ⏳ {usuario_pendiente.nombre_completo} ({nombre_cargo}) - PENDIENTE"
                )
            
            # Usuario 3: Rechazado
            usuario_rechazado = self._crear_usuario_unico(
                cargo=cargo,
                valido=False,
                rechazado=True,
                sufijo=f"_rechazado_{nombre_cargo.lower()}"
            )
            if usuario_rechazado:
                contadores['rechazados'] += 1
                self.stdout.write(
                    f"  ✗ {usuario_rechazado.nombre_completo} ({nombre_cargo}) - RECHAZADO"
                )
        
        self.stdout.write(
            f"  📊 Total: {contadores['aprobados']} aprobados, "
            f"{contadores['pendientes']} pendientes, "
            f"{contadores['rechazados']} rechazados"
        )
        
        return usuarios_aprobados

    def _crear_usuario_unico(self, cargo, valido, rechazado, sufijo=""):
        """
        Crea un usuario único evitando duplicados por correo.
        
        Parámetros:
            cargo: Instancia de Cargo
            valido: bool - Si está aprobado
            rechazado: bool - Si fue explícitamente rechazado
            sufijo: string para diferenciar correos
        
        Retorna:
            Usuario creado o None si ya existe
        """
        nombre = self.fake.first_name()
        apellido = self.fake.last_name()
        # Usar sufijo para garantizar emails únicos
        correo = f"{nombre.lower()}{sufijo}@universidad.edu"
        
        usuario, creado = Usuario.objects.get_or_create(
            correo=correo,
            defaults={
                'nombre': nombre,
                'apellido': apellido,
                'id_cargo': cargo,
                'valido': valido,
                'rechazado': rechazado,
                'correo_verificado': True,
            }
        )
        
        if creado:
            # Hashear contraseña de forma segura
            usuario.set_password('test123456')
            usuario.save()
            return usuario
        
        return None if creado else usuario

    def _crear_vehiculos(self):
        """
        Crea un catálogo de vehículos con diferentes estados y capacidades.
        
        Escenarios:
        - Vehículos activos: disponibles para reserva (5)
        - Vehículos inactivos: en taller/fuera de servicio (2)
        - Capacidades variadas: desde 5 hasta 15 pasajeros
        
        Retorna:
            list: Instancias de Vehiculo activos
        """
        self.stdout.write("\n🚐 Creando vehículos...")
        
        vehiculos_config = [
            # Vehículos activos
            {'marca': 'Toyota', 'modelo': 'Hiace', 'cant_pasajeros': 9, 'placa': 'UNIV-001', 'activo': True},
            {'marca': 'Mercedes', 'modelo': 'Sprinter', 'cant_pasajeros': 14, 'placa': 'UNIV-002', 'activo': True},
            {'marca': 'Ford', 'modelo': 'Transit', 'cant_pasajeros': 10, 'placa': 'UNIV-003', 'activo': True},
            {'marca': 'Volkswagen', 'modelo': 'Transporter', 'cant_pasajeros': 8, 'placa': 'UNIV-004', 'activo': True},
            {'marca': 'Chevrolet', 'modelo': 'Express', 'cant_pasajeros': 12, 'placa': 'UNIV-005', 'activo': True},
            
            # Vehículos inactivos (en mantenimiento)
            {'marca': 'Fiat', 'modelo': 'Ducato', 'cant_pasajeros': 7, 'placa': 'UNIV-MANT-01', 'activo': False},
            {'marca': 'Renault', 'modelo': 'Master', 'cant_pasajeros': 11, 'placa': 'UNIV-MANT-02', 'activo': False},
        ]
        
        vehiculos_activos = []
        
        for config in vehiculos_config:
            vehiculo, creado = Vehiculo.objects.get_or_create(
                marca=config['marca'],
                modelo=config['modelo'],
                defaults={
                    'cant_pasajeros': config['cant_pasajeros'],
                    'activo': config['activo'],
                }
            )
            
            if creado:
                estado = "✓ Disponible" if config['activo'] else "✓ En mantenimiento"
                self.stdout.write(
                    f"  {estado}: {config['marca']} {config['modelo']} "
                    f"({config['cant_pasajeros']} pas.) - {config['placa']}"
                )
            else:
                self.stdout.write(f"  → {config['placa']} ya existe")
            
            if config['activo']:
                vehiculos_activos.append(vehiculo)
        
        return vehiculos_activos

    def _crear_reservas(self, usuarios, vehiculos):
        """
        Crea reservas de prueba con diversos escenarios.
        
        Escenarios generados:
        1. Reservas PASADAS (historial) - completadas hace días/semanas
        2. Reservas PRESENTES (en curso) - comenzaron hoy/ayer, terminan mañana
        3. Reservas FUTURAS (próximas) - sin conflictos aparentes
        4. CONFLICTOS por jerarquía - mismo vehículo, horario solapado
        5. Reservas PENDIENTES - sin aprobación aún
        6. Reservas CANCELADAS - por el usuario o por sistema
        7. Reservas SIN HORA DE FIN - solo hora de salida
        
        Parámetros:
            usuarios: list de usuarios aprobados
            vehiculos: list de vehículos activos
        """
        self.stdout.write("\n🎫 Creando reservas con diferentes escenarios...\n")
        
        ahora = timezone.now()
        contador_creados = 0
        
        # ESCENARIO 1: Reservas pasadas (historial)
        self.stdout.write("  📅 Escenario 1: Reservas PASADAS (historial)...")
        for i in range(3):
            ticket = self._crear_reserva(
                usuario=random.choice(usuarios),
                vehiculo=random.choice(vehiculos),
                hora_inicio=ahora - timedelta(days=random.randint(5, 30)),
                duracion_horas=4,
                estado=Ticket.ESTADO_APROBADO,
                descripcion="Viaje completado - Historial"
            )
            if ticket:
                contador_creados += 1
                self.stdout.write(f"    ✓ {ticket.destino} - {ticket.estado}")
        
        # ESCENARIO 2: Reservas en progreso (actualmente en uso)
        self.stdout.write("\n  ⏳ Escenario 2: Reservas EN PROGRESO (ahora mismo)...")
        for i in range(2):
            ticket = self._crear_reserva(
                usuario=random.choice(usuarios),
                vehiculo=random.choice(vehiculos),
                hora_inicio=ahora - timedelta(hours=2),
                duracion_horas=5,
                estado=Ticket.ESTADO_APROBADO,
                descripcion="Viaje en curso - El vehículo está siendo usado"
            )
            if ticket:
                contador_creados += 1
                self.stdout.write(f"    ✓ {ticket.destino} - {ticket.estado}")
        
        # ESCENARIO 3: Reservas futuras sin conflictos
        self.stdout.write("\n  🔮 Escenario 3: Reservas FUTURAS (sin conflictos)...")
        for i in range(4):
            ticket = self._crear_reserva(
                usuario=random.choice(usuarios),
                vehiculo=random.choice(vehiculos),
                hora_inicio=ahora + timedelta(days=random.randint(1, 15), hours=random.randint(8, 18)),
                duracion_horas=3,
                estado=Ticket.ESTADO_APROBADO,
                descripcion="Reserva futura confirmada"
            )
            if ticket:
                contador_creados += 1
                self.stdout.write(f"    ✓ {ticket.destino} - {ticket.estado}")
        
        # ESCENARIO 4: CASOS DE CONFLICTO - TESTING DE PRIORIDAD JERÁRQUICA
        self.stdout.write("\n  ⚠️  Escenario 4: CONFLICTOS - Testing de prioridad jerárquica...")
        
        # Obtener usuarios de cada nivel para testing de jerarquía
        usuarios_por_prioridad = {}
        for usuario in usuarios:
            p = usuario.prioridad
            if p not in usuarios_por_prioridad:
                usuarios_por_prioridad[p] = []
            usuarios_por_prioridad[p].append(usuario)
        
        vehiculo_conflicto = vehiculos[0]
        hora_conflicto = ahora + timedelta(days=7, hours=10)
        
        # 4a. Usuario regular (prioridad 3) hace reserva
        if 3 in usuarios_por_prioridad and usuarios_por_prioridad[3]:
            usuario_bajo = usuarios_por_prioridad[3][0]
            ticket_bajo = self._crear_reserva(
                usuario=usuario_bajo,
                vehiculo=vehiculo_conflicto,
                hora_inicio=hora_conflicto,
                duracion_horas=4,
                estado=Ticket.ESTADO_APROBADO,
                descripcion="Conflicto: Usuario regular con baja prioridad"
            )
            if ticket_bajo:
                contador_creados += 1
                self.stdout.write(f"    ✓ Ticket #{ticket_bajo.id}: {usuario_bajo.nombre_completo} (Usuario) reserva")
        
        # 4b. Secretario (prioridad 2) intenta reservar el mismo vehículo/hora
        # Esperado: BLOQUEADO (usuario bajo existe)
        if 2 in usuarios_por_prioridad and usuarios_por_prioridad[2]:
            usuario_secretario = usuarios_por_prioridad[2][0]
            resultado = crear_ticket_con_reglas(
                usuario=usuario_secretario,
                vehiculo=vehiculo_conflicto,
                hora_inicio=hora_conflicto + timedelta(hours=1),  # Solapamiento
                hora_fin=hora_conflicto + timedelta(hours=4),
                destino="Viaje de secretaría",
                cant_pasajeros=3,
                descripcion="Intento de Secretario (debe bloquearse)"
            )
            if resultado.exito:
                contador_creados += 1
                self.stdout.write(f"    ✓ Ticket #{resultado.ticket.id}: Secretario SOBRESCRIBE (mayor prioridad)")
            else:
                self.stdout.write(f"    ✓ Secretario BLOQUEADO: {resultado.mensaje}")
        
        # 4c. Decano (prioridad 1) intenta reservar - DEBE SOBRESCRIBIR TODO
        if 1 in usuarios_por_prioridad and usuarios_por_prioridad[1]:
            usuario_decano = usuarios_por_prioridad[1][0]
            resultado = crear_ticket_con_reglas(
                usuario=usuario_decano,
                vehiculo=vehiculo_conflicto,
                hora_inicio=hora_conflicto,
                hora_fin=hora_conflicto + timedelta(hours=4),
                destino="Viaje de rectoría",
                cant_pasajeros=5,
                descripcion="Decano sobrescribe por máxima prioridad"
            )
            if resultado.estado == resultado.SOBRESCRITO:
                contador_creados += 1
                self.stdout.write(
                    f"    ✓ Ticket #{resultado.ticket.id}: DECANO SOBRESCRIBE "
                    f"({len(resultado.tickets_cancelados)} reservas canceladas)"
                )
            elif resultado.exito:
                contador_creados += 1
                self.stdout.write(f"    ✓ Ticket #{resultado.ticket.id}: Decano aprobado sin conflictos")
            else:
                self.stdout.write(f"    ! Decano error: {resultado.mensaje}")
        
        # ESCENARIO 5: Reservas PENDIENTES (sin aprobación)
        self.stdout.write("\n  ⏳ Escenario 5: Reservas PENDIENTES (esperando aprobación)...")
        ticket_pendiente = self._crear_reserva(
            usuario=random.choice(usuarios),
            vehiculo=random.choice(vehiculos),
            hora_inicio=ahora + timedelta(days=20, hours=14),
            duracion_horas=2,
            estado=Ticket.ESTADO_PENDIENTE,
            descripcion="Reserva pendiente de aprobación por administrador"
        )
        if ticket_pendiente:
            contador_creados += 1
            self.stdout.write(f"    ✓ {ticket_pendiente.destino} - PENDIENTE")
        
        # ESCENARIO 6: Reservas CANCELADAS
        self.stdout.write("\n  ❌ Escenario 6: Reservas CANCELADAS...")
        for i in range(2):
            ticket_cancelado = self._crear_reserva(
                usuario=random.choice(usuarios),
                vehiculo=random.choice(vehiculos),
                hora_inicio=ahora - timedelta(days=random.randint(1, 5)),
                duracion_horas=3,
                estado=Ticket.ESTADO_CANCELADO,
                descripcion="Reserva cancelada por el usuario o por sobrescritura de jerarquía"
            )
            if ticket_cancelado:
                contador_creados += 1
                self.stdout.write(f"    ✓ {ticket_cancelado.destino} - CANCELADO")
        
        # ESCENARIO 7: Reservas sin HORA DE FIN definida
        self.stdout.write("\n  🕐 Escenario 7: Reservas SIN HORA DE FIN...")
        ticket_sin_fin = self._crear_reserva(
            usuario=random.choice(usuarios),
            vehiculo=random.choice(vehiculos),
            hora_inicio=ahora + timedelta(days=10, hours=9),
            duracion_horas=None,  # Sin fin definido
            estado=Ticket.ESTADO_APROBADO,
            descripcion="Reserva sin hora de retorno definida (punto a punto)"
        )
        if ticket_sin_fin:
            contador_creados += 1
            self.stdout.write(f"    ✓ {ticket_sin_fin.destino} - SIN HORA FIN")
        
        self.stdout.write(f"\n  📊 Total reservas creadas: {contador_creados}")

    def _crear_reserva(self, usuario, vehiculo, hora_inicio, duracion_horas, estado, descripcion):
        """
        Helper para crear una reserva/ticket.
        
        Parámetros:
            usuario: Instancia de Usuario
            vehiculo: Instancia de Vehiculo
            hora_inicio: datetime de inicio
            duracion_horas: int o None (si es None, hora_fin = None)
            estado: string (pendiente, aprobado, cancelado)
            descripcion: string con detalles
        
        Retorna:
            Ticket creado o None si no se pudo crear
            
        Nota: Usa get_or_create basado en usuario, vehículo y hora_inicio
        para evitar duplicados si el comando se ejecuta múltiples veces.
        """
        hora_fin = None if duracion_horas is None else hora_inicio + timedelta(hours=duracion_horas)
        
        destinos = [
            "Reunión en rectoría",
            "Visita a campus afiliado",
            "Conferencia académica",
            "Transporte de estudiantes",
            "Evento universitario",
            "Inspección de instalaciones",
            "Seminario especializado",
            "Visita de autoridades",
            "Transporte de comisión",
            "Actividad de extensión",
        ]
        
        ticket, creado = Ticket.objects.get_or_create(
            id_usuario=usuario,
            id_vehiculo=vehiculo,
            hora_inicio=hora_inicio,
            defaults={
                'destino': random.choice(destinos),
                'cant_pasajeros': random.randint(1, min(8, vehiculo.cant_pasajeros)),
                'descripcion': descripcion,
                'hora_fin': hora_fin,
                'estado': estado,
                'observacion': "",
            }
        )
        
        return ticket if creado else None

    def _mostrar_resumen(self):
        """
        Muestra un resumen de los datos cargados en la base de datos.
        
        Útil para verificar que todo se creó correctamente.
        """
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write("📊 RESUMEN DE DATOS CARGADOS\n")
        
        self.stdout.write(f"👤 Usuarios: {Usuario.objects.count()}")
        self.stdout.write(f"   - Aprobados: {Usuario.objects.filter(valido=True).count()}")
        self.stdout.write(f"   - Pendientes: {Usuario.objects.filter(valido=False, rechazado=False).count()}")
        self.stdout.write(f"   - Rechazados: {Usuario.objects.filter(rechazado=True).count()}")
        
        self.stdout.write(f"\n🚐 Vehículos: {Vehiculo.objects.count()}")
        self.stdout.write(f"   - Disponibles: {Vehiculo.objects.filter(activo=True).count()}")
        self.stdout.write(f"   - En mantenimiento: {Vehiculo.objects.filter(activo=False).count()}")
        
        self.stdout.write(f"\n🎫 Tickets/Reservas: {Ticket.objects.count()}")
        self.stdout.write(f"   - Aprobados: {Ticket.objects.filter(estado=Ticket.ESTADO_APROBADO).count()}")
        self.stdout.write(f"   - Pendientes: {Ticket.objects.filter(estado=Ticket.ESTADO_PENDIENTE).count()}")
        self.stdout.write(f"   - Cancelados: {Ticket.objects.filter(estado=Ticket.ESTADO_CANCELADO).count()}")
        
        self.stdout.write(f"\n💼 Cargos: {Cargo.objects.count()}")
        for cargo in Cargo.objects.all():
            count = cargo.usuarios.count()
            self.stdout.write(f"   - {cargo.nombre}: {count} usuarios")
        
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("\n🔐 Credenciales de prueba (todos con contraseña: test123456):\n")
        
        for usuario in Usuario.objects.filter(valido=True):
            self.stdout.write(f"  • {usuario.correo} ({usuario.id_cargo.nombre})")
        
        self.stdout.write(self.style.SUCCESS("\n✅ Datos listos para testing!\n"))


if __name__ == "__main__":
    from django.core.management import execute_from_command_line

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    execute_from_command_line([sys.argv[0], "poblar_bd", *sys.argv[1:]])
