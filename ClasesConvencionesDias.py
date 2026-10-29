import datetime
import functools
from abc import ABC, abstractmethod
from enum import Enum, unique
from typing import Dict
def memoize_year_frac(func):
    cache: Dict[tuple[type, datetime.date, datetime.date], float] = {}
    @functools.wraps(func)
    def wrapper(self, start_date: datetime.date, end_date:datetime.date) -> float:
        key = (type(self), start_date, end_date) #La clase va en la clave para que una subclase no use resultados del padre
        if key in cache:
            return cache[key]
        result = func(self, start_date, end_date)
        cache[key] = result
        return result
    return wrapper
def _as_dates(start_date, end_date):
    """Las convenciones cuentan dias enteros: si nos llega un datetime nos quedamos solo con la fecha, y si llega otra cosa damos un error claro"""
    #Antes con datetimes ACT/360 contaba 0 dias entre el 1-ene a las 18h y el 2-ene a las 6h (solo pasan 12 horas), y ACT/ACT ISDA directamente fallaba
    res = []
    for d in (start_date, end_date):
        if isinstance(d, datetime.datetime):
            d = d.date()
            #Va primero porque datetime es una subclase de date, si no lo miraramos antes pasaria por la comprobacion de abajo sin convertirse
        elif not isinstance(d, datetime.date):
            raise TypeError(f"Se esperaba una fecha (datetime.date) y ha llegado {type(d).__name__}: {d!r}")
        res.append(d)
    return res
@unique
class DayCountConvention(Enum):
    ACT_360 = "ACT/360"
    ACT_365F = "ACT/365F"
    THIRTY_360 = "30/360"
    ACT_ACT_ISDA = "ACT/ACT_ISDA"
class DayCountStrat(ABC):
    #Esta clase define la interfaz para calcular fracciones de año
    __slots__ = () #Slots es muy bueno para optimizar la RAM mientras que cache optimiza el tiempo de ejecucion
    @abstractmethod
    def DayCount(self, start_date:datetime.date, end_date:datetime.date) -> int:
        #Devuelve la cantidad de dias
        pass
    @abstractmethod
    def DayFrac(self, start_date:datetime.date, end_date:datetime.date) -> float:
        #Devuelve la fraccion del año normalizada
        pass
class ACT360(DayCountStrat):
    #Este sera evidentemente para la convencion ACT/360
    __slots__ = ()
    def DayCount(self, start_date:datetime.date, end_date: datetime.date) -> int:
        start_date, end_date = _as_dates(start_date, end_date)
        delta = end_date - start_date
        return delta.days
    @memoize_year_frac
    def DayFrac(self, start_date, end_date):
        days = self.DayCount(start_date, end_date)
        res = days/360
        return res
class ACT365F(DayCountStrat):
    #Dias reales entre 365 siempre, aunque el año sea bisiesto. Es la que usamos para pasar fechas a los plazos t de las curvas
    __slots__ = ()
    def DayCount(self, start_date: datetime.date, end_date: datetime.date) -> int:
        start_date, end_date = _as_dates(start_date, end_date)
        return (end_date - start_date).days
    def DayFrac(self, start_date: datetime.date, end_date: datetime.date) -> float:
        return self.DayCount(start_date, end_date) / 365
class Thirty360(DayCountStrat):
    __slots__ = ()
    def DayCount(self, start_date: datetime.date, end_date: datetime.date) -> int:
        start_date, end_date = _as_dates(start_date, end_date)
        d1 = start_date.day
        d2 = end_date.day
        m1 = start_date.month
        m2 = end_date.month
        y1 = start_date.year
        y2 = end_date.year
        if d1 == 31: d1 = 30
        if d2 == 31 and d1 == 30: d2 = 30
        #Estos if son la logica estandar de la convencion
        delta = 360*(y2 - y1) + 30*(m2 - m1) + d2 - d1
        return delta
    @memoize_year_frac
    def DayFrac(self, start_date: datetime.date, end_date: datetime.date) -> float:
        days = self.DayCount(start_date, end_date)
        res = days/360
        return res
class ActActISDA(DayCountStrat):
    __slots__ = ()
    def DayCount(self, start_date: datetime.date, end_date: datetime.date) -> int:
        start_date, end_date = _as_dates(start_date, end_date)
        return (end_date - start_date).days
    @memoize_year_frac
    def DayFrac(self, start_date: datetime.date, end_date: datetime.date) -> float:
        start_date, end_date = _as_dates(start_date, end_date)
        #Esta no pasa por DayCount, asi que convertimos aqui tambien. El resto de DayFrac llaman a DayCount y ya quedan cubiertas
        if end_date < start_date:
            return -self.DayFrac(end_date, start_date)
        res = 0.0
        current = start_date
        while current < end_date:
            #Partimos el periodo por años naturales y cada trozo se divide por los dias de su año
            inicio_sig = datetime.date(current.year + 1, 1, 1)
            fin_tramo = min(inicio_sig, end_date)
            dias_ano = (inicio_sig - datetime.date(current.year, 1, 1)).days #365 o 366
            res += (fin_tramo - current).days / dias_ano
            current = fin_tramo
        return res
class CalculatorFactory:
    _instances: Dict[DayCountConvention, DayCountStrat] = {}
    @staticmethod
    def get_calculator(convention: DayCountConvention) -> DayCountStrat:
        if convention in CalculatorFactory._instances:
            return CalculatorFactory._instances[convention]
        strat: DayCountStrat
        match convention:
            case DayCountConvention.ACT_360:
                strat = ACT360()
            case DayCountConvention.ACT_365F:
                strat = ACT365F()
            case DayCountConvention.THIRTY_360:
                strat = Thirty360()
            case DayCountConvention.ACT_ACT_ISDA:
                strat = ActActISDA()
            case _:
                raise ValueError(f"Convencion no soportada: {convention}")
        CalculatorFactory._instances[convention] = strat
        return strat
if __name__ == "__main__":
    start = datetime.date(2005, 3, 14)
    end = datetime.date.today()
    conventions = [DayCountConvention.ACT_360, DayCountConvention.THIRTY_360, DayCountConvention.ACT_ACT_ISDA]
    for conv in conventions:
        calc = CalculatorFactory.get_calculator(conv)
        dias = calc.DayCount(start, end)
        yf = calc.DayFrac(start, end)
        print(f"\nConvención: {conv.value}")
        print(f"Tipo de objeto: {type(calc).__name__}")
        print(f"Periodo: {start} -> {end}")
        print(f"Días calculados: {dias}")
        print(f"Year Fraction: {yf:.6f}")