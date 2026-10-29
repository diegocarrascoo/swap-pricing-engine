from datetime import date, timedelta
from enum import Enum
from abc import ABC, abstractmethod
from dateutil.easter import easter
from dateutil.relativedelta import relativedelta
"""Para un swap podemos tener dos tipos de fechas diferentes
Las fechas teoricas (unadjusted dates), se refieren a las fechas objetivo,
si el swap empieza el 1 de Enero por 2 años con pagos semestrales, tus fechas teóricas son: 1-Jul, 1-Ene, 1-Jul, 1-Ene.
Las fechas reales (adjusted dates), las fechas en las que realmente se mueve el dinero

La regla mas importante es la Modified following, si la fecha cae en festivo/fin de semana,
muévela al siguiente día hábil. PERO, si al moverla te pasas al siguiente mes, entonces retrocede al día hábil anterior."""
class BusinessDayConvention(Enum):
    UNADJUSTED = "Unadjusted"
    FOLLOWING = "Following"
    MODIFIED_FOLLOWING = "ModFollowing"
    PRECEDING = "Preceding"
    MODIFIED_PRECEDING = "ModPreceding"
    #La simetrica de Modified Following: retrocede al dia habil anterior, pero si al retroceder nos vamos al mes anterior avanza al siguiente
"""Hay que definir las convenciones"""
MAX_DIAS_INHABILES = 30
#Ningun calendario real tiene tantos dias inhabiles seguidos (el maximo suele ser una semana, como el Año Nuevo chino con su fin de semana)
#Si los superamos es que is_holiday tiene un fallo, y es mejor dar un error que quedarse en un bucle infinito
class Calendar(ABC):
    @abstractmethod
    def is_holiday(self, d: date) -> bool:
        """Cada calendario debe ser capaz de definir sus vacaciones"""
        pass
    def is_weekend(self, d: date) -> bool:
        """Normalmente es sabado y domingo pero se puede sobreescribir para paises como israel que es viernes y sbado"""
        return d.weekday() >= 5
    def is_businessday(self, d: date) -> bool:
        """Tiene que devolver verdadero si el dia no es ni festivo ni fin de semana"""
        return not (self.is_weekend(d) or self.is_holiday(d))
    def adjust(self, d: date, convention: BusinessDayConvention) -> date:
        if not isinstance(convention, BusinessDayConvention):
            raise TypeError(f"convention tiene que ser un BusinessDayConvention (por ejemplo BusinessDayConvention.FOLLOWING), ha llegado {convention!r}")
            #Antes solo se comprobaba si la fecha no era habil: adjust(viernes, "Following") devolvia la fecha y adjust(sabado, "Following") fallaba
            #Ahora el error sale siempre, sea cual sea la fecha, asi no depende de la suerte de que el dia caiga en fin de semana
        if convention == BusinessDayConvention.UNADJUSTED or self.is_businessday(d):
            """Si es unadjusted o ya es dia habil no hay nada que mover"""
            return d
        if convention == BusinessDayConvention.FOLLOWING:
            return self._following(d)
        if convention == BusinessDayConvention.PRECEDING:
            return self._preceding(d)
        if convention == BusinessDayConvention.MODIFIED_FOLLOWING:
            d_following = self._following(d)
            if d_following.month != d.month:
                """Si al avanzar nos pasamos de mes, retrocedemos desde la fecha original"""
                return self._preceding(d)
            return d_following
        if convention == BusinessDayConvention.MODIFIED_PRECEDING:
            d_preceding = self._preceding(d)
            if d_preceding.month != d.month:
                #Si al retroceder nos vamos al mes anterior, avanzamos desde la fecha original
                return self._following(d)
            return d_preceding
        raise ValueError(f"Convencion no soportada: {convention}")
    def advance(self, d: date, business_days: int) -> date:
        """Avanza (o retrocede si es negativo) un numero de dias habiles, sirve para el spot lag: el spot de EUR es hoy + 2 dias habiles"""
        step = 1 if business_days >= 0 else -1
        for _ in range(abs(business_days)):
            d = self._roll(d + timedelta(days= step), step)
            #Damos un paso y, si caemos en un dia inhabil, seguimos en la misma direccion hasta el siguiente habil: eso es avanzar un dia habil
        return d
    def is_end_of_month(self, d: date) -> bool:
        """Verdadero si d es el ultimo dia habil de su mes (el siguiente dia habil ya es del mes que viene)"""
        return self._following(d + timedelta(days= 1)).month != d.month
    def end_of_month(self, d: date) -> date:
        """Ultimo dia habil del mes de d"""
        return self._preceding(d + relativedelta(day= 31))
        #relativedelta(day=31) lleva al ultimo dia natural del mes (si el mes tiene 30 dias se queda en el 30) y desde ahi retrocedemos hasta un dia habil
    def _following(self, d: date) -> date:
        return self._roll(d, 1)
    def _preceding(self, d: date) -> date:
        return self._roll(d, -1)
    def _roll(self, d: date, step: int) -> date:
        """Se mueve dia a dia en la direccion de step (+1 hacia delante, -1 hacia atras) hasta encontrar un dia habil"""
        #Antes _following y _preceding tenian cada uno su while sin limite, si un calendario marcaba todos los dias como festivos se quedaban colgados para siempre
        #Ahora los dos usan este metodo, que tiene un limite de dias y da un error que dice que calendario esta mal
        original = d
        for _ in range(MAX_DIAS_INHABILES):
            if self.is_businessday(d):
                return d
            d += timedelta(days= step)
        raise RuntimeError(f"{type(self).__name__}: no hay ningun dia habil en {MAX_DIAS_INHABILES} dias desde {original}, revisa is_holiday")
"""A partir de esta clase abstracta ya solo quedaria definir los festivos para cualquier calendario que queramos usar"""
class WeekendsOnly(Calendar):
    """Solo los fines de semana son inhabiles, util para pruebas"""
    def is_holiday(self, d: date) -> bool:
        return False
class TARGET(Calendar):
    """Calendario de los pagos en euros (y por tanto de los swaps Euribor/ESTR): 1 de enero, Viernes Santo, Lunes de Pascua, 1 de mayo, 25 y 26 de diciembre"""
    def is_holiday(self, d: date) -> bool:
        if (d.month, d.day) in {(1, 1), (5, 1), (12, 25), (12, 26)}:
            return True
        domingo_pascua = easter(d.year)
        return d in (domingo_pascua - timedelta(days= 2), domingo_pascua + timedelta(days= 1))
