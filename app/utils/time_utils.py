from app.engine import TimeDuration, TimeUnit
import re

def format_time(seconds: int)->str:
        days = int(seconds // (24 * 60 * 60))
        hours = int((seconds % (24 * 60 * 60)) // (60 * 60))
        minutes = int((seconds % (60 * 60)) // 60)
        seconds = int(seconds % 60)

        time_string = ""
        if days > 0:
            time_string += f"{days}d"
        if hours > 0:
                time_string += f"{hours}h"
        if minutes > 0:
            time_string += f"{minutes}m"
        if seconds > 0:
            time_string += f"{seconds}s"

        return time_string.rstrip(", ")
    
def format_time_with_unit(time_duration: TimeDuration) -> str:
    """
    Formatea una duración dada en una unidad de tiempo específica a un string legible.

    Args:
        time_duration (TimeDuration): La duración con su unidad de tiempo.

    Returns:
        str: La duración formateada como un string legible.
    """
    duration_seconds = time_duration.value * time_duration.unit.to_seconds()
    milliseconds = int((duration_seconds % 1) * 1000)

    days = int(duration_seconds // (24 * 60 * 60))
    hours = int((duration_seconds % (24 * 60 * 60)) // (60 * 60))
    minutes = int((duration_seconds % (60 * 60)) // 60)
    seconds = int(duration_seconds % 60)

    time_string = ""
    if days > 0:
        time_string += f"{days}day"
    if hours > 0:
        time_string += f"{hours}h"
    if minutes > 0:
        time_string += f"{minutes}min"
    if seconds > 0:
        time_string += f"{seconds}s"
    if milliseconds > 0:
        time_string += f"{milliseconds}ms"

    return time_string.rstrip(", ")

def select_best_time_unit(duration_ms: float) -> TimeDuration:
    """
    Selecciona la mejor unidad de tiempo para representar la duración, basado en la magnitud del valor en milisegundos.

    Args:
        duration_ms (float): La duración en milisegundos.

    Returns:
        TimeDuration: Una nueva instancia de TimeDuration con el valor convertido a la unidad más apropiada.
    """
    if duration_ms < 1000:
        # Menos de 1 segundo, usar milisegundos
        return TimeDuration(duration_ms, TimeUnit.MILLISECOND)
    elif duration_ms < 60000:
        # Menos de 1 minuto, usar segundos
        return TimeDuration(duration_ms / 1000, TimeUnit.SECOND)
    elif duration_ms < 3600000:
        # Menos de 1 hora, usar minutos
        return TimeDuration(duration_ms / 60000, TimeUnit.MINUTE)
    elif duration_ms < 86400000:
        # Menos de 1 día, usar horas
        return TimeDuration(duration_ms / 3600000, TimeUnit.HOUR)
    elif duration_ms < 604800000:
        # Menos de 1 semana, usar días
        return TimeDuration(duration_ms / 86400000, TimeUnit.DAY)
    elif duration_ms < 2592000000:
        # Menos de 1 mes, usar semanas
        return TimeDuration(duration_ms / 604800000, TimeUnit.WEEK)
    elif duration_ms < 31104000000:
        # Menos de 1 año, usar meses
        return TimeDuration(duration_ms / 2592000000, TimeUnit.MONTH)
    else:
        # Más de un año, usar años
        return TimeDuration(duration_ms / 31104000000, TimeUnit.YEAR)
    
def rearrange_time_axis_function(label, original_times_ms, calls, ax, fig, plan_name):
    new_time_unit = TimeUnit(label)

    times_in_new_unit = [time / new_time_unit.to_milliseconds() for time in original_times_ms]

    ax.clear()
    ax.step(times_in_new_unit, calls, where='post', color='blue', label='Llamadas acumuladas')
    ax.set_xlabel(f'Tiempo ({new_time_unit.value})')
    ax.set_ylabel('Número de llamadas')
    ax.set_ylim(0)
    ax.set_title(f'Curva de capacidad - {plan_name}')
    ax.grid(True)
    ax.legend()
    fig.canvas.draw_idle()

_SINGULAR_TIME_ALIASES = {
    'ms': '1ms',
    's': '1s', 'second': '1s', 'seconds': '1s',
    'min': '1min', 'minute': '1min', 'minutes': '1min',
    'h': '1h', 'hour': '1h', 'hours': '1h',
    'day': '1day', 'days': '1day',
    'week': '1week', 'weeks': '1week',
    'month': '1month', 'months': '1month',
    'year': '1year', 'years': '1year',
}


def parse_time_string_to_duration(time_string: str) -> TimeDuration:
    """
    Convierte una cadena de tiempo formateada (e.g., '2.5s') en una instancia de TimeDuration.

    Args:
        time_string (str): La cadena de tiempo formateada.

    Returns:
        TimeDuration: Una instancia de TimeDuration que representa la duración total.
    """
    time_units = {
        'ms': TimeUnit.MILLISECOND,
        's': TimeUnit.SECOND,
        'min': TimeUnit.MINUTE,
        'h': TimeUnit.HOUR,
        'day': TimeUnit.DAY,
        'week': TimeUnit.WEEK,
        'month': TimeUnit.MONTH,
        'year': TimeUnit.YEAR
    }

    time_string = time_string.replace(" ", "")
    # Soporta nombres singulares/plurales sin número: "second" → "1s", "day" → "1day", etc.
    time_string = _SINGULAR_TIME_ALIASES.get(time_string.lower(), time_string)
    pattern = r'(\d+(\.\d+)?)(ms|s|min|h|day|week|month|year)'
    matches = re.findall(pattern, time_string)

    total_duration_ms = 0
    for value, _, unit in matches:
        duration = TimeDuration(float(value), time_units[unit])
        total_duration_ms += duration.value * duration.unit.to_milliseconds()

    total_duration = select_best_time_unit(total_duration_ms)

    return total_duration