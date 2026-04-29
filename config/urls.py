from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # Esta línea deriva todo el tráfico hacia tu app "reservas"
    path('', include('reservas.urls')), 
]