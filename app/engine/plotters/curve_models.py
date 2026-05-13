from dataclasses import dataclass, field
from typing import List


@dataclass
class CapacityCurvePoints:
    """
    Salida canónica de todos los plotters.

    t_ms      : valores del eje de tiempo en milisegundos (agnóstico de unidad).
    capacity  : capacidad acumulada disponible en cada instante t.

    Invariantes:
      - len(t_ms) == len(capacity) siempre.
      - t_ms[0] == 0.0 siempre.
      - t_ms[-1] == t_max (el extremo del intervalo solicitado) siempre.
      - t_ms está ordenado de menor a mayor.
    """
    t_ms: List[float] = field(default_factory=list)
    capacity: List[float] = field(default_factory=list)

    def downsample(self) -> "CapacityCurvePoints":
        """Elimina puntos redundantes consecutivos conservando los escalones y el último punto."""
        t, c = self.t_ms, self.capacity
        if len(t) <= 2:
            return self
        keep = [0]
        for i in range(1, len(t) - 1):
            if c[i] != c[i - 1] or c[i] != c[i + 1]:
                keep.append(i)
        keep.append(len(t) - 1)
        return CapacityCurvePoints(
            t_ms=[t[i] for i in keep],
            capacity=[c[i] for i in keep],
        )