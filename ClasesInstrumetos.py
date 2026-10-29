import numpy as np
from YieldCurveClasses import YieldCurve
from abc import ABC, abstractmethod
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum
class Side(Enum):
    """Quien paga el tipo fijo del instrumento. El valor es el signo por el que se multiplica el NPV"""
    PAYER = 1 #Pagas el tipo fijo: swap pagador, FRA comprado, deposito tomado (pides prestado)
    RECEIVER = -1 #Recibes el tipo fijo: swap receptor, FRA vendido, deposito prestado
    #Antes todos los instrumentos eran pagadores sin decirlo en ningun sitio, y la unica forma de tener un receptor era poner el nocional en negativo
def _validar_plazos(nombre: str, etiqueta: str, tiempos: np.ndarray):
    """Comprueba que unos plazos son un array 1D no vacio, sin NaN, sin negativos y estrictamente crecientes (sin repetidos)
    Lo comprobamos al crear el instrumento para que el error salga donde entra el dato malo y no como un NaN en mitad del bootstrap"""
    #La usan los tres instrumentos, asi la regla de "plazos validos" esta escrita en un solo sitio
    if tiempos.ndim != 1 or len(tiempos) == 0:
        raise ValueError(f"{nombre}: {etiqueta} tiene que ser una lista de plazos no vacia, recibido {tiempos}")
    if not np.all(np.isfinite(tiempos)):
        raise ValueError(f"{nombre}: {etiqueta} contiene NaN o infinitos: {tiempos}")
    if tiempos[0] < 0:
        raise ValueError(f"{nombre}: {etiqueta} no puede tener plazos negativos: {tiempos}")
        #Basta con mirar el primero porque justo debajo comprobamos que van de menor a mayor
    if np.any(np.diff(tiempos) <= 0):
        raise ValueError(f"{nombre}: {etiqueta} tiene que estar ordenado de menor a mayor y sin repetidos: {tiempos}")
        #Con fechas desordenadas el bootstrapper cogia un vencimiento equivocado, y un plazo repetido es un periodo de duracion 0 que acaba dividiendo por cero
@dataclass
class CashFlow:
    t: float
    amount: float
    def pv(self, curve: YieldCurve) -> float:
        return self.amount*curve.get_discount_factor(self.t)
class Leg:
    def __init__(self, cashflows: List[CashFlow]):
        self.cashflows= cashflows
    def npv(self, curve: YieldCurve) -> float:
        return sum(cf.pv(curve) for cf in self.cashflows)
class Instrument(ABC):
    def __init__(self, name: str, market_rate: float, index: Optional[str] = None, side: Side = Side.PAYER):
        if not np.isfinite(market_rate):
            raise ValueError(f"{name}: el tipo de mercado no es un numero valido ({market_rate})")
            #Un NaN en una sola cotizacion contamina toda la curva en el bootstrap, mejor pararlo aqui
        if not isinstance(side, Side):
            raise TypeError(f"{name}: side tiene que ser Side.PAYER o Side.RECEIVER, ha llegado {side!r}")
        self.name = name
        self.rate = market_rate
        self.index = index
        #Nombre de la curva con la que se proyecta (ej. "EURIBOR6M" o "ESTR"), asi el instrumento sabe que curva le toca y no depende de que nos acordemos al preciar
        self.side = side
        #Por defecto pagador, que es lo que eran todos antes, asi el codigo que ya creaba instrumentos sigue dando los mismos NPV
    @abstractmethod
    def npv(self, discount_curve: YieldCurve, projection_curve: Optional[YieldCurve]= None) -> float:
        """Calcula el Valor Presente Neto del instrumento dado el mercado, desde el punto de vista de self.side"""
        pass
    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name} @ {self.rate:.4%} ({self.side.name.lower()})>"
class Deposit(Instrument):
    def __init__(self, name: str, t_end: float, rate: float, t_start: float = 0.0, accrual: Optional[float] = None, index: Optional[str] = None,
                 side: Side = Side.PAYER):
        super().__init__(name, rate, index, side)
        self.t_start = t_start
        self.t_end = t_end
        self.accrual = accrual if accrual is not None else t_end - t_start
        #El devengo sale de la convencion del deposito (ACT/360), que no tiene por que coincidir con los plazos t de la curva (ACT/365F)
        _validar_plazos(name, "(t_start, t_end)", np.array([t_start, t_end], dtype= np.float64))
        #Pasando el par (t_start, t_end) por la misma funcion comprobamos de golpe que 0 <= t_start < t_end
        if not self.accrual > 0:
            raise ValueError(f"{name}: el devengo tiene que ser positivo, recibido {self.accrual}")
            #Ponemos "not > 0" y no "<= 0" porque cualquier comparacion con NaN da False, asi un devengo NaN tambien falla
    @property
    def _target_df(self) -> float:
        #Se calcula cada vez a partir de self.rate, asi si movemos el tipo (bump para el DV01) la calibracion lo ve
        return 1 / (1 + self.rate * self.accrual)
    def _model_df(self, curve: YieldCurve) -> float:
        #DF entre el inicio (spot) y el vencimiento, si el deposito empieza hoy es simplemente DF(t_end)
        return curve.get_discount_factor(self.t_end) / curve.get_discount_factor(self.t_start)
    def npv(self, discount_curve: YieldCurve, projection_curve: Optional[YieldCurve]= None) -> float:
        #Pagador del tipo fijo (como el FRA y el Swap): recibes 1 en el inicio y devuelves 1 + r*accrual al vencimiento
        #El receptor es el que presta: el mismo NPV cambiado de signo, por eso multiplicamos por self.side.value (+1 o -1)
        curve = projection_curve if projection_curve is not None else discount_curve
        npv_pagador = curve.get_discount_factor(self.t_start) - (1 + self.rate * self.accrual) * curve.get_discount_factor(self.t_end)
        return self.side.value * npv_pagador
    def residual(self, discount_curve: YieldCurve, projection_curve: Optional[YieldCurve]= None):
        curve = projection_curve if projection_curve is not None else discount_curve
        return self._target_df - self._model_df(curve)
class FRA(Instrument):
    def __init__(self, name: str, t_start: float, t_end: float, rate: float, accrual: Optional[float] = None, index: Optional[str] = None,
                 side: Side = Side.PAYER):
        super().__init__(name, rate, index, side)
        self.t_start = t_start
        self.t_end = t_end
        self.dt = accrual if accrual is not None else t_end - t_start
        _validar_plazos(name, "(t_start, t_end)", np.array([t_start, t_end], dtype= np.float64))
        #Antes un FRA con t_start == t_end daba dt = 0 y el forward salia NaN con solo un aviso, ahora falla aqui diciendo que instrumento es
        if not self.dt > 0:
            raise ValueError(f"{name}: el devengo tiene que ser positivo, recibido {self.dt}")
    def _model_forward(self, discount_curve: YieldCurve, projection_curve: Optional[YieldCurve]= None) -> float:
        """El forward lo necesitan tanto npv como residual, asi lo calculamos en un solo sitio y no pueden dejar de coincidir"""
        proj = projection_curve if projection_curve is not None else discount_curve
        df_start = proj.get_discount_factor(self.t_start)
        df_end = proj.get_discount_factor(self.t_end)
        return (df_start / df_end - 1.0) / self.dt
    def npv(self, discount_curve: YieldCurve, projection_curve: Optional[YieldCurve]= None) -> float:
        model_forward = self._model_forward(discount_curve, projection_curve)
        #Antes: return (model_forward - self.rate) * self.dt * discount_curve.get_discount_factor(self.t_end)
        #Eso es pagar la diferencia al FINAL del periodo, pero un FRA de mercado se liquida al PRINCIPIO (en t_start, cuando se conoce el Euribor)
        #Como se paga dt antes de lo normal, la diferencia se descuenta con el propio Euribor: (F - K)*dt / (1 + F*dt), y luego se trae a hoy con DF(t_start)
        #Con una sola curva las dos formulas dan lo mismo, porque DF(t_start) / (1 + F*dt) = DF(t_end), pero con dos curvas el F sale de la de proyeccion y el DF de la de descuento y ya no coinciden
        liquidacion = (model_forward - self.rate) * self.dt / (1 + model_forward * self.dt)
        return self.side.value * liquidacion * discount_curve.get_discount_factor(self.t_start)
    def residual(self, discount_curve: YieldCurve, projection_curve: Optional[YieldCurve]= None):
        return self._model_forward(discount_curve, projection_curve) - self.rate
class Swap(Instrument):
    def __init__(self, name: str, fixed_times: np.ndarray, fixed_accruals: np.ndarray, floating_schedule: np.ndarray, rate: float, notional: float = 1.0,
                 index: Optional[str] = None, side: Side = Side.PAYER):
        super().__init__(name, rate, index, side)
        self.fixed_times = np.asarray(fixed_times, dtype= np.float64)
        self.fixed_accruals = np.asarray(fixed_accruals, dtype= np.float64)
        self.floating_schedule = np.asarray(floating_schedule, dtype= np.float64)
        self.notional = notional
        self._validate()
        #Validamos en el __init__ porque los swaps se crean por tres caminos (directamente, from_market_data y el InstrumentBuilder) y todos pasan por aqui
        #Ojo: si despues cambiamos un atributo a mano (swap.fixed_times = ...) no se vuelve a comprobar, para mover el tipo en un bump no hace falta
    def _validate(self):
        _validar_plazos(self.name, "fixed_times", self.fixed_times)
        if self.floating_schedule.size > 0 and self.fixed_times[0] <= self.floating_schedule[0]:
            raise ValueError(f"{self.name}: el primer pago fijo ({self.fixed_times[0]}) tiene que ser posterior al inicio del swap ({self.floating_schedule[0]})")
            #Lo miramos antes que el calendario flotante para que con un pago en t=0 salga este mensaje, que dice lo que pasa de verdad
        _validar_plazos(self.name, "floating_schedule", self.floating_schedule)
        if len(self.floating_schedule) < 2:
            raise ValueError(f"{self.name}: floating_schedule necesita al menos el inicio y un pago")
        if self.fixed_accruals.shape != self.fixed_times.shape:
            raise ValueError(f"{self.name}: hay {self.fixed_times.size} pagos fijos pero {self.fixed_accruals.size} devengos")
            #Sin esto zip se comia los pagos que sobran sin avisar (la anualidad salia 1.92 en vez de 2.83)
            #Y con la version vectorizada es todavia mas necesario: con 3 pagos y 1 devengo numpy repetiria ese devengo para los 3 pagos sin dar ningun error (broadcasting)
        if not np.all(self.fixed_accruals > 0):
            raise ValueError(f"{self.name}: los devengos de la pata fija tienen que ser positivos: {self.fixed_accruals}")
        if abs(self.fixed_times[-1] - self.floating_schedule[-1]) > 1e-9:
            raise ValueError(f"{self.name}: las dos patas tienen que vencer a la vez (fija {self.fixed_times[-1]}, flotante {self.floating_schedule[-1]})")
            #El bootstrapper usa el ultimo pago fijo como vencimiento, si la flotante acabara mas tarde se saldria de la curva
        if not np.isfinite(self.notional) or not self.notional > 0:
            raise ValueError(f"{self.name}: el nocional tiene que ser positivo, recibido {self.notional}. Para un swap receptor usa side= Side.RECEIVER")
            #Con nocional 0 la anualidad es 0 y no se puede sacar el tipo par
            #Antes dejabamos el nocional negativo para los receptores, ahora que existe side hay una sola forma de decirlo y no dos que se pueden contradecir
    @property
    def fixed_leg(self) -> Leg:
        """Se construye cada vez a partir de self.rate, asi nunca se queda desactualizada"""
        return Leg([CashFlow(t, self.notional * self.rate * dt) for t, dt in zip(self.fixed_times, self.fixed_accruals)])
    def annuity(self, discount_curve: YieldCurve) -> float:
        """Valor de la pata fija por unidad de tasa: N * suma(dt * DF)"""
        #Version anterior, la dejamos comentada para comparar:
        #return sum(self.notional * dt * discount_curve.get_discount_factor(t) for t, dt in zip(self.fixed_times, self.fixed_accruals))
        #Por que se cambia: pedia un DF por cada pago, y cada llamada a la curva tiene un coste fijo (convertir a array, evaluar el spline, np.where...)
        #Como el bootstrap reprecia cada instrumento muchisimas veces (en cada iteracion y para cada derivada numerica), con 35 instrumentos hasta 50Y
        #eran 1,19 millones de llamadas y 6 segundos, y un DV01 por buckets (un bootstrap por instrumento) se iba a unos 3,5 minutos
        #Como se ha hecho: la curva ya acepta arrays, asi que le pedimos todos los DF de una vez y la suma la hace numpy. El bootstrap baja a 0.28 segundos (x22) con el mismo resultado
        dfs = discount_curve.get_discount_factor(self.fixed_times)
        #dfs es un array con un DF por cada pago fijo, en el mismo orden que fixed_times y fixed_accruals
        return float(self.notional * np.sum(self.fixed_accruals * dfs))
        #fixed_accruals * dfs multiplica elemento a elemento (dt_i * DF_i) y np.sum hace el sumatorio que antes hacia el bucle
    def float_leg_pv(self, discount_curve: YieldCurve, projection_curve: Optional[YieldCurve]= None) -> float:
        proj = projection_curve if projection_curve is not None else discount_curve
        #Version anterior, la dejamos comentada para comparar:
        #pv_float = 0.0
        #starts = self.floating_schedule[:-1]
        #ends = self.floating_schedule[1:]
        #for t_start, t_end in zip(starts, ends):
        #    dt = t_end - t_start
        #    p_start = proj.get_discount_factor(t_start)
        #    p_end = proj.get_discount_factor(t_end)
        #    fwd_rate = (p_start / p_end - 1.0) / dt
        #    cf_float = self.notional * fwd_rate * dt
        #    df_pay = discount_curve.get_discount_factor(t_end)
        #    pv_float += cf_float * df_pay
        #return pv_float
        #Por que se cambia: igual que en annuity, hacia 3 llamadas a la curva por cada periodo (p_start, p_end y df_pay), un swap a 50Y semestral eran 300 llamadas
        #Como se ha hecho: es exactamente la misma formula, pero en vez de ir periodo a periodo trabajamos con todos los periodos a la vez usando arrays
        p = proj.get_discount_factor(self.floating_schedule)
        #Todos los DF de proyeccion de una vez, uno por cada fecha del calendario flotante
        dts = np.diff(self.floating_schedule)
        #np.diff resta cada fecha de la anterior, son los dt = t_end - t_start de todos los periodos
        fwd_rates = (p[:-1] / p[1:] - 1.0) / dts
        #p[:-1] son los DF de inicio de cada periodo (el antiguo p_start) y p[1:] los de final (el antiguo p_end), asi sacamos todos los forwards a la vez
        df_pay = discount_curve.get_discount_factor(self.floating_schedule[1:])
        #Los DF de descuento de las fechas de pago, que son el final de cada periodo
        return float(np.sum(self.notional * fwd_rates * dts * df_pay))
        #Cupon de cada periodo (N * forward * dt) por su DF de pago, y np.sum hace lo que antes hacia pv_float +=
    def _npv_pagador(self, discount_curve: YieldCurve, projection_curve: Optional[YieldCurve]= None) -> float:
        #Recibes la flotante y pagas la fija
        return self.float_leg_pv(discount_curve, projection_curve) - self.rate * self.annuity(discount_curve)
    def npv(self, discount_curve: YieldCurve, projection_curve: Optional[YieldCurve]= None) -> float:
        return self.side.value * self._npv_pagador(discount_curve, projection_curve)
        #El receptor tiene los mismos flujos al reves, asi que su NPV es el del pagador cambiado de signo
    #Como puede ser que los datos sean arrays crudos, necesitamos algo que convierta los arrays de fechas de pago en los plazos y fracciones de año del Swap
    @classmethod
    def from_market_data(cls, name: str, payment_times: np.ndarray, rate: float, notional: float = 1.0,
                         float_period: Optional[float] = None, index: Optional[str] = None, side: Side = Side.PAYER):
        """payment_times son los pagos de la pata fija. float_period es el periodo de la pata flotante en años (0.5 para Euribor 6M),
        si es None la flotante paga en las mismas fechas que la fija, que solo es correcto para swaps OIS"""
        times = np.asarray(payment_times, dtype= np.float64)
        times_with_zero = np.concatenate(([0.0], times))
        dts = np.diff(times_with_zero)
        if float_period is None:
            floating_schedule = times_with_zero
        else:
            #Generamos hacia atras desde el vencimiento, asi si sobra un trozo queda al principio como en el mercado
            float_dates = np.arange(times[-1], 0.0, -float_period)[::-1]
            floating_schedule = np.concatenate(([0.0], float_dates[float_dates > 1e-9]))
        return cls(name, times, dts, floating_schedule, rate, notional, index, side)
        #No hace falta validar nada aqui: cls(...) llama al __init__ y _validate ya comprueba los plazos que salen
    def residual(self, discount_curve: YieldCurve, projection_curve: Optional[YieldCurve] = None) -> float:
        return self._npv_pagador(discount_curve, projection_curve)
        #Para calibrar da igual quien paga (el swap de mercado vale 0 para los dos), asi el bootstrap no depende de side
