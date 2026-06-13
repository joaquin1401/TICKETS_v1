import sys
import os

with open("reservas/views.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """            km_real_str = request.POST.get("kilometraje_real", "").replace(',', '.')
            if not km_real_str:
                messages.error(request, "Debes ingresar el kilometraje real para finalizar el ticket.")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))
            
            try:
                ticket.kilometraje_real = float(km_real_str)
            except ValueError:
                messages.error(request, "Kilometraje real inválido.")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))
                
            ticket.estado = Ticket.ESTADO_FINALIZADO
            ticket.save(update_fields=['estado', 'kilometraje_real'])
            messages.success(request, f"El ticket #{ticket.pk} ha sido finalizado con {ticket.kilometraje_real} km.")"""

replacement = """            km_real_str = request.POST.get("kilometraje_real", "").replace(',', '.')
            hora_inicio_real_str = request.POST.get("hora_inicio_real")
            hora_fin_real_str = request.POST.get("hora_fin_real")

            if not km_real_str or not hora_inicio_real_str or not hora_fin_real_str:
                messages.error(request, "Debes ingresar todos los datos reales (km y horarios) para finalizar.")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))
            
            from django.utils.dateparse import parse_datetime
            from django.utils.timezone import make_aware, is_naive
            
            try:
                ticket.kilometraje_real = float(km_real_str)
                
                dt_inicio = parse_datetime(hora_inicio_real_str)
                if dt_inicio and is_naive(dt_inicio):
                    dt_inicio = make_aware(dt_inicio)
                ticket.hora_inicio_real = dt_inicio
                
                dt_fin = parse_datetime(hora_fin_real_str)
                if dt_fin and is_naive(dt_fin):
                    dt_fin = make_aware(dt_fin)
                ticket.hora_fin_real = dt_fin
                
            except (ValueError, TypeError):
                messages.error(request, "Datos reales inválidos.")
                return redirect(request.META.get('HTTP_REFERER', 'inicio'))
                
            ticket.estado = Ticket.ESTADO_FINALIZADO
            ticket.save(update_fields=['estado', 'kilometraje_real', 'hora_inicio_real', 'hora_fin_real'])
            messages.success(request, f"El ticket #{ticket.pk} ha sido finalizado.")"""

if target in content:
    content = content.replace(target, replacement)
    with open("reservas/views.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("REPLACED")
else:
    print("TARGET NOT FOUND")
    # let's try a softer replace
    # we just search for a snippet and print it
    idx = content.find('km_real_str = request.POST.get("kilometraje_real"')
    if idx != -1:
        print("Found at", idx)
        print("Snippet:", repr(content[idx:idx+500]))
