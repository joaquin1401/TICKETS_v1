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

from reservas.models import Cargo, Usuario, Vehiculo, Ticket
from reservas.utils.services import crear_ticket_con_reglas

class Command(BaseCommand):
    """
    Management Command para poblar la base de datos con datos de prueba.
    
    Características:
    - Idempotente: puede ejecutarse múltiples veces sin duplicar datos
    - Modular: funciones separadas por entidad (cargos, usuarios, vehículos, tickets)
    - Manual: usa listas predefinidas para usuarios, correos y vehículos (fácil de editar)
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
        
        import sys
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
            
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
            (Cargo.ADMIN_SEU, 0),
            (Cargo.DECANO, 1),
            (Cargo.VICEDECANO, 1),
            (Cargo.SECRETARIO, 2),
            (Cargo.SUBSECRETARIO, 2),
            (Cargo.USUARIO, 3),
            (Cargo.CHOFER, 4),
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
        Crea usuarios de prueba predefinidos con diferentes estados de aprobación.
        
        Se usan diccionarios explícitos para que el desarrollador pueda modificar
        nombres, correos y roles fácilmente.
        """
        self.stdout.write("\n👥 Creando usuarios predefinidos...")
        
        # LISTA DE USUARIOS PREDEFINIDOS PARA EDITAR
        usuarios_config = [
            # Administrador SEU
            {'nombre': 'Denise', 'apellido': 'Mur', 'correo': 'admin@universidad.edu', 'cargo': Cargo.ADMIN_SEU, 'valido': True, 'rechazado': False},
            
            # Decanos
            {'nombre': 'Dorotea', 'apellido': 'Lucena', 'correo': 'decano_aprobado@universidad.edu', 'cargo': Cargo.DECANO, 'valido': True, 'rechazado': False},
            {'nombre': 'Ani', 'apellido': 'Laguna', 'correo': 'decano_pendiente@universidad.edu', 'cargo': Cargo.DECANO, 'valido': False, 'rechazado': False},
            {'nombre': 'Danilo', 'apellido': 'Barba', 'correo': 'decano_rechazado@universidad.edu', 'cargo': Cargo.DECANO, 'valido': False, 'rechazado': True},
            
            # Secretarios
            {'nombre': 'Celia', 'apellido': 'Mascaró', 'correo': 'secretario_aprobado@universidad.edu', 'cargo': Cargo.SECRETARIO, 'valido': True, 'rechazado': False},
            {'nombre': 'Jerónimo', 'apellido': 'Pareja', 'correo': 'secretario_pendiente@universidad.edu', 'cargo': Cargo.SECRETARIO, 'valido': False, 'rechazado': False},
            {'nombre': 'Anastasia', 'apellido': 'Rueda', 'correo': 'secretario_rechazado@universidad.edu', 'cargo': Cargo.SECRETARIO, 'valido': False, 'rechazado': True},
            
            # Usuarios regulares
            {'nombre': 'Nydia', 'apellido': 'Pereira', 'correo': 'usuario_aprobado@universidad.edu', 'cargo': Cargo.USUARIO, 'valido': True, 'rechazado': False},
            {'nombre': 'Jaime', 'apellido': 'Ferrera', 'correo': 'usuario_pendiente@universidad.edu', 'cargo': Cargo.USUARIO, 'valido': False, 'rechazado': False},
            {'nombre': 'Wilfredo', 'apellido': 'Iglesia', 'correo': 'usuario_rechazado@universidad.edu', 'cargo': Cargo.USUARIO, 'valido': False, 'rechazado': True},

            # Choferes
            {'nombre': 'Carlos', 'apellido': 'Piloto', 'correo': 'chofer1@universidad.edu', 'cargo': Cargo.CHOFER, 'valido': True, 'rechazado': False},
            {'nombre': 'Miguel', 'apellido': 'Rueda', 'correo': 'chofer2@universidad.edu', 'cargo': Cargo.CHOFER, 'valido': True, 'rechazado': False},
        ]
        
        nombres = ["Ana", "Juan", "Pedro", "Maria", "Luis", "Elena", "Sofía", "Carlos", "Javier", "Lucía", "Diego", "Marta", "Pablo", "Laura", "Andrés", "Paula", "Fernando", "Raquel"]
        apellidos = ["Gómez", "López", "García", "Fernández", "Pérez", "Rodríguez", "Sánchez", "Martínez", "González", "Romero", "Navarro", "Torres", "Ruiz", "Díaz", "Vargas", "Ríos", "Molina"]
        
        # Generar 20 usuarios adicionales al azar para llegar a >20
        for i in range(25):
            nombre = random.choice(nombres)
            apellido = random.choice(apellidos)
            cargo_rand = random.choice([Cargo.USUARIO, Cargo.USUARIO, Cargo.USUARIO, Cargo.SECRETARIO, Cargo.SUBSECRETARIO, Cargo.DECANO, Cargo.VICEDECANO])
            usuarios_config.append({
                'nombre': nombre,
                'apellido': apellido,
                'correo': f'user_{i}_{nombre.lower()}_{apellido.lower()}@universidad.edu',
                'cargo': cargo_rand,
                'valido': True,
                'rechazado': False
            })
        
        usuarios_aprobados = []
        contadores = {'aprobados': 0, 'pendientes': 0, 'rechazados': 0}
        
        for config in usuarios_config:
            cargo_nombre = config['cargo']
            if cargo_nombre not in cargos:
                self.stdout.write(f"  [Warning] Cargo {cargo_nombre} no encontrado, omitiendo usuario {config['correo']}")
                continue
                
            cargo_instancia = cargos[cargo_nombre]
            
            departamento = None
            if cargo_nombre == Cargo.USUARIO:
                departamento = random.choice([c[0] for c in Usuario.DEPARTAMENTOS_CHOICES])

            usuario, creado = Usuario.objects.get_or_create(
                correo=config['correo'],
                defaults={
                    'nombre': config['nombre'],
                    'apellido': config['apellido'],
                    'id_cargo': cargo_instancia,
                    'valido': config['valido'],
                    'rechazado': config['rechazado'],
                    'correo_verificado': True,  # Para pruebas siempre verificado
                    'departamento': departamento,
                }
            )
            
            if creado:
                usuario.set_password('test123456')
                usuario.save()
            
            estado_str = ""
            if config['valido']:
                estado_str = "APROBADO"
                contadores['aprobados'] += 1
                usuarios_aprobados.append(usuario)
            elif config['rechazado']:
                estado_str = "RECHAZADO"
                contadores['rechazados'] += 1
            else:
                estado_str = "PENDIENTE"
                contadores['pendientes'] += 1
                
            simbolo = "✓" if config['valido'] else ("✗" if config['rechazado'] else "⏳")
            if cargo_nombre == Cargo.ADMIN_SEU: simbolo = "⭐"
            
            self.stdout.write(f"  {simbolo} {usuario.nombre_completo} ({cargo_nombre}) - {estado_str} [{usuario.correo}]")
            
        self.stdout.write(
            f"  📊 Total: {contadores['aprobados']} aprobados, "
            f"{contadores['pendientes']} pendientes, "
            f"{contadores['rechazados']} rechazados"
        )
        
        return usuarios_aprobados

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
                    'patente': config.get('placa'),
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
        
        # ESCENARIO 8: Relleno masivo hasta llegar a 100 tickets
        self.stdout.write(f"\n  📈 Escenario 8: Generación masiva (hasta >100 tickets)...")
        choferes = [u for u in usuarios if u.id_cargo.nombre == Cargo.CHOFER]
        tickets_faltantes = 100 - contador_creados
        for i in range(max(0, tickets_faltantes + 5)):  # Asegurar más de 100
            es_en_curso = random.random() < 0.1
            es_finalizado = random.random() < 0.3 and not es_en_curso
            
            estado_ticket = Ticket.ESTADO_APROBADO
            conductor_asignado = None
            if es_en_curso and choferes:
                estado_ticket = Ticket.ESTADO_EN_CURSO
                conductor_asignado = random.choice(choferes)
            elif es_finalizado and choferes:
                estado_ticket = Ticket.ESTADO_FINALIZADO
                conductor_asignado = random.choice(choferes)
                
            ticket = self._crear_reserva(
                usuario=random.choice(usuarios),
                vehiculo=random.choice(vehiculos),
                hora_inicio=ahora + timedelta(days=random.randint(-40, 40), hours=random.randint(-12, 12)),
                duracion_horas=random.randint(2, 8),
                estado=estado_ticket,
                descripcion="Reserva masiva generada automáticamente",
                conductor=conductor_asignado
            )
            if ticket:
                contador_creados += 1
                
        self.stdout.write(f"\n  📊 Total reservas creadas: {contador_creados}")

    def _crear_reserva(self, usuario, vehiculo, hora_inicio, duracion_horas, estado, descripcion, conductor=None):
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
        
        # Simular kilometraje calculado y variables reales
        distancia_est = round(random.uniform(5.0, 150.0), 2)
        kilometraje_inicio = None
        kilometraje_fin = None
        hora_inicio_real = None
        hora_fin_real = None
        
        if estado == Ticket.ESTADO_FINALIZADO:
            kilometraje_inicio = round(random.uniform(10000.0, 150000.0), 2)
            kilometraje_fin = round(kilometraje_inicio + (distancia_est * random.uniform(0.9, 1.1)), 2)
            hora_inicio_real = hora_inicio + timedelta(minutes=random.randint(-15, 30))
            if hora_fin:
                hora_fin_real = hora_fin + timedelta(minutes=random.randint(-20, 60))
            else:
                hora_fin_real = hora_inicio_real + timedelta(hours=duracion_horas if duracion_horas else 2)
        elif estado == Ticket.ESTADO_EN_CURSO:
            kilometraje_inicio = round(random.uniform(10000.0, 150000.0), 2)
            hora_inicio_real = hora_inicio + timedelta(minutes=random.randint(-15, 30))
        
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
                'conductor': conductor,
                'distancia_est': distancia_est,
                'kilometraje_inicio': kilometraje_inicio,
                'kilometraje_fin': kilometraje_fin,
                'hora_inicio_real': hora_inicio_real,
                'hora_fin_real': hora_fin_real,
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
