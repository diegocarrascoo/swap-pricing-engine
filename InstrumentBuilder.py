import numpy as np
from dataclasses import dataclass
from datetime import date
from typing import Optional
from dateutil.relativedelta import relativedelta
from CalendarSetup import Calendar, BusinessDayConvention
from ScheduleGenerator import ScheduleParams, generate_swap_schedule
from ClasesConvencionesDias import CalculatorFactory, DayCountConvention
from ClasesInstrumetos import Deposit, FRA, Swap, Side
"""Une las dos mitades del proyecto: a partir de fechas y convenciones de mercado construye los instrumentos con plazos t en años,
que es lo unico que entienden las curvas y el bootstrapper"""
@dataclass
class MarketConventions:
    calendar: Calendar
    spot_lag: int = 2 #En EUR el spot es hoy + 2 dias habiles
    convention: BusinessDayConvention = BusinessDayConvention.MODIFIED_FOLLOWING
    time_dc: DayCountConvention = DayCountConvention.ACT_365F #Para pasar fechas a los t de la curva
    money_market_dc: DayCountConvention = DayCountConvention.ACT_360 #Depositos, FRAs y pata flotante
    fixed_dc: DayCountConvention = DayCountConvention.THIRTY_360 #Pata fija de los swaps
class InstrumentBuilder:
    def __init__(self, valuation_date: date, conventions: MarketConventions):
        self.valuation_date = valuation_date
        self.conv = conventions
        self._time_dc = CalculatorFactory.get_calculator(conventions.time_dc)
        self._mm_dc = CalculatorFactory.get_calculator(conventions.money_market_dc)
        self._fixed_dc = CalculatorFactory.get_calculator(conventions.fixed_dc)
        cal = conventions.calendar
        self.spot_date = cal.advance(cal.adjust(valuation_date, BusinessDayConvention.FOLLOWING), conventions.spot_lag)
    def year_frac(self, d: date) -> float:
        """Plazo t de una fecha, medido desde el dia de valoracion (el t = 0 de las curvas)"""
        return self._time_dc.DayFrac(self.valuation_date, d)
    def _date_after(self, months: int) -> date:
        return self.conv.calendar.adjust(self.spot_date + relativedelta(months= months), self.conv.convention)
    def deposit(self, name: str, tenor_months: int, rate: float, index: Optional[str] = None, side: Side = Side.PAYER) -> Deposit:
        end = self._date_after(tenor_months)
        return Deposit(name, self.year_frac(end), rate, t_start= self.year_frac(self.spot_date),
                       accrual= self._mm_dc.DayFrac(self.spot_date, end), index= index, side= side)
    def fra(self, name: str, start_months: int, end_months: int, rate: float, index: Optional[str] = None, side: Side = Side.PAYER) -> FRA:
        start, end = self._date_after(start_months), self._date_after(end_months)
        return FRA(name, self.year_frac(start), self.year_frac(end), rate, accrual= self._mm_dc.DayFrac(start, end), index= index, side= side)
    def swap(self, name: str, tenor_months: int, rate: float, fixed_freq_months: int = 12, float_freq_months: int = 6,
             notional: float = 1.0, index: Optional[str] = None, side: Side = Side.PAYER) -> Swap:
        #Cada pata tiene su propio calendario de pagos, en un swap Euribor 6M la fija es anual y la flotante semestral
        fixed_dates = generate_swap_schedule(ScheduleParams(self.spot_date, tenor_months, fixed_freq_months, self.conv.calendar, self.conv.convention))
        float_dates = generate_swap_schedule(ScheduleParams(self.spot_date, tenor_months, float_freq_months, self.conv.calendar, self.conv.convention))
        fixed_times = np.array([self.year_frac(d) for d in fixed_dates[1:]])
        fixed_accruals = np.array([self._fixed_dc.DayFrac(d1, d2) for d1, d2 in zip(fixed_dates[:-1], fixed_dates[1:])])
        floating_schedule = np.array([self.year_frac(d) for d in float_dates])
        return Swap(name, fixed_times, fixed_accruals, floating_schedule, rate, notional, index, side)
        #side se pasa tal cual al instrumento, por defecto pagador como antes
