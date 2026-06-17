import io
import base64
import matplotlib
matplotlib.use('Agg')  # Usar backend no interactivo
import matplotlib.pyplot as plt
import numpy as np

COLOR_PRIMARIO = '#38bdf8'
COLOR_TEXTO = '#cbd5e1'

def get_base64_image(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', transparent=True, dpi=120)
    buf.seek(0)
    image_base64 = base64.b64encode(buf.read()).decode('utf-8')
    plt.close(fig)
    return f"data:image/png;base64,{image_base64}"

def generar_grafico_barras_horizontal(labels, data, formato_valores="{}"):
    # Limitar y revertir para que el mayor quede arriba
    labels = list(reversed(labels))
    data = list(reversed(data))
    
    fig, ax = plt.subplots(figsize=(6, len(labels) * 0.28 + 0.4))
    
    bars = ax.barh(labels, data, color=COLOR_PRIMARIO, height=0.4)
    
    # Remover bordes arriba y derecha, dejar abajo e izquierda
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color(COLOR_TEXTO)
    ax.spines['left'].set_color(COLOR_TEXTO)
    
    ax.tick_params(axis='x', colors=COLOR_TEXTO, labelsize=9)
    ax.tick_params(axis='y', which='both', length=0, labelsize=10, colors=COLOR_TEXTO)
    
    # Agregar etiquetas de datos
    for bar in bars:
        width = bar.get_width()
        val_str = formato_valores.format(int(width) if width == int(width) else round(width, 1))
        ax.text(width + (max(data)*0.02), bar.get_y() + bar.get_height()/2, 
                val_str, ha='left', va='center', color=COLOR_TEXTO, fontweight='bold', fontsize=10)
    
    plt.tight_layout()
    return get_base64_image(fig)

def generar_grafico_torta(labels, data):
    fig, ax = plt.subplots(figsize=(5, 5))
    colores = ['#4ade80', '#38bdf8', '#fbbf24', '#f87171', '#a78bfa']
    
    # Filtrar datos en cero
    l_d = [(l, d) for l, d in zip(labels, data) if d > 0]
    if not l_d:
        return ""
    
    f_labels = [i[0] for i in l_d]
    f_data = [i[1] for i in l_d]
    
    wedges, texts, autotexts = ax.pie(
        f_data, 
        colors=colores, 
        autopct='%1.0f', 
        startangle=90, 
        textprops=dict(color='white', fontsize=10, fontweight='bold')
    )
    
    # Formatear el autotext para mostrar el valor absoluto en vez de porcentaje
    for i, autotext in enumerate(autotexts):
        autotext.set_text(str(f_data[i]))
        autotext.set_color('white')
        
    ax.legend(wedges, f_labels, loc="center left", bbox_to_anchor=(1, 0.5), frameon=False, labelcolor=COLOR_TEXTO)
    
    plt.tight_layout()
    return get_base64_image(fig)
