from dataclasses import dataclass
from datetime import date
from enum import Enum
from CalendarSetup import Calendar, BusinessDayConvention
from typing import List
from dateutil.relativedelta import relativedelta
#Dateutil hace la misma funcion que timedelta, pero en vez de trabajar con tiempos absolutos, trabaja en el calendario, por lo que es mejor para trabajar con años bisiestos, meses de 30/31 dias, etc
class DateGenerationRule(Enum):
    """Desde donde se cuentan los periodos cuando el tenor no es multiplo de la frecuencia (13 meses con pagos semestrales, por ejemplo)"""
    BACKWARD = "Backward" #Desde el vencimiento hacia atras: el periodo corto (stub) queda al principio, es lo estandar en swaps
    FORWARD = "Forward" #Desde el inicio hacia delante: el stub queda al final, es lo que hacia el codigo antes
@dataclass
class ScheduleParams:
    startdate: date
    tenor_months: int #duracion total del swap en meses
    freq_months: int #frecuencia en la que se paga
    calendar: Calendar
    convention: BusinessDayConvention
    rule: DateGenerationRule = DateGenerationRule.BACKWARD
    end_of_month: bool = False
    #Si es True y el swap empieza el ultimo dia habil de un mes, todas las fechas caen en el ultimo dia habil de su mes (30-abr -> 31-jul -> 30-oct...)
    #Los dos campos nuevos tienen valor por defecto para que el codigo que ya creaba ScheduleParams siga funcionando igual
@dataclass
class Schedule:
    unadjusted: List[date] #Fechas teoricas, las que salen de sumar meses
    adjusted: List[date] #Fechas en las que se mueve el dinero, despues de ajustarlas con el calendario
    #Devolvemos las dos porque algunas convenciones calculan los devengos con las fechas teoricas y no con las ajustadas
def _month_offsets(tenor_months: int, freq_months: int, rule: DateGenerationRule) -> List[int]:
    """Cuantos meses hay que sumar a la fecha de inicio para obtener cada fecha del calendario"""
    if rule == DateGenerationRule.FORWARD:
        return list(range(0, tenor_months, freq_months)) + [tenor_months]
        #13 meses semestral: [0, 6, 12, 13], el ultimo periodo (12 -> 13) es el corto
    if rule == DateGenerationRule.BACKWARD:
        return [0] + sorted(range(tenor_months, 0, -freq_months))
        #13 meses semestral: range da 13, 7, 1 y queda [0, 1, 7, 13], el primer periodo (0 -> 1) es el corto
    raise ValueError(f"Regla no soportada: {rule}")
    #Con un tenor multiplo de la frecuencia las dos reglas dan las mismas fechas, solo cambian cuando hay un periodo corto
def build_schedule(params: ScheduleParams) -> Schedule:
    if params.freq_months <= 0 or params.tenor_months <= 0:
        raise ValueError("tenor_months y freq_months tienen que ser positivos.")
    eom = params.end_of_month and params.calendar.is_end_of_month(params.startdate)
    #La regla de fin de mes solo se aplica si el swap empieza a final de mes, si empieza un dia 15 no tiene sentido
    unadjusted = []
    for months_to_add in _month_offsets(params.tenor_months, params.freq_months, params.rule):
        """Siempre se calcula desde la fecha inicial para no acumular errores"""
        unadjusted_date = params.startdate + relativedelta(months= months_to_add)
        if eom and months_to_add > 0:
            unadjusted_date += relativedelta(day= 31)
            #Sin esto, empezando el 30-abr todas las fechas caerian el dia 30 (30-jul en vez de 31-jul) porque relativedelta mantiene el dia del mes
            #relativedelta(day=31) lleva al ultimo dia natural del mes, y luego el ajuste (Modified Following) lo deja en el ultimo dia habil
        unadjusted.append(unadjusted_date)
    adjusted = [params.calendar.adjust(d, params.convention) for d in unadjusted]
    return Schedule(unadjusted, adjusted)
def generate_swap_schedule(params: ScheduleParams) -> List[date]:
    """Devuelve solo las fechas ajustadas, como antes, asi el InstrumentBuilder y cualquier codigo que ya la usara no cambia"""
    return build_schedule(params).adjusted
"""Con esto ya tenemos las fechas de pago del swap"""
