import numpy as np
from scipy.optimize import least_squares
from typing import List, Optional
from YieldCurveClasses import InterpolatedYieldCurve, ExtrapolatedYieldCurve, YieldCurve
from ClasesInstrumetos import Instrument, Deposit, FRA, Swap
"""Aprovechamos el codigo que ya hemos hecho antes"""
class Bootstrapper:
    def __init__(self, instruments: List[Instrument], external_discount_curve: Optional[YieldCurve]= None, f_inf: Optional[float]= None):
        self.instruments = sorted(instruments, key = self._get_maturity)
        self.nudos = np.array([self._get_maturity(inst) for inst in self.instruments])
        self.external_discount_curve = external_discount_curve
        self.f_inf = f_inf #Forward de largo plazo hacia el que converge la curva despues del ultimo instrumento, si es None se queda en flat forward
        self._validate_inputs()
    def _get_maturity(self, inst:Instrument) -> float:
        if isinstance(inst, (Deposit, FRA)):
            return inst.t_end
        elif isinstance(inst, Swap):
            return inst.fixed_times[-1] #Swap ya comprueba al crearse que las fechas vienen ordenadas y que las dos patas vencen a la vez, asi que el ultimo pago fijo es el vencimiento
        else:
            raise TypeError(f"Instrumento no soportado: {type(inst)}")
    def _validate_inputs(self):
        if len(self.nudos) == 0:
            raise ValueError("No se han proporcionado instrumentos.")
        if np.any(np.diff(self.nudos) <= 0):
            raise ValueError("Hay instrumentos con el mismo vencimiento, el spline necesita nudos distintos.")
    def _build_curve_from_rates(self, rates: np.ndarray) -> InterpolatedYieldCurve:
        t_knots = np.concatenate(([0.0], self.nudos))
        r_knots = np.concatenate(([rates[0]], rates))
        """Hay que añadir manualmente el punto (0,0)"""
        dfs = np.exp(-r_knots * t_knots) #Obtenemos de las tasas continuas los factores de descuento
        return InterpolatedYieldCurve(t_knots, dfs)
    def _objective_function(self, current_rates: np.ndarray) -> np.ndarray:
        if not np.all(np.isfinite(current_rates)):
            return np.full(len(self.instruments), 1e6) #Esto es bastante util ya que con el metodo que usamos es posible que den infinitos sin esta restriccion
        candidate_curve = self._build_curve_from_rates(current_rates)
        disc_curve = self.external_discount_curve if self.external_discount_curve is not None else candidate_curve
        residuals = np.array([inst.residual(discount_curve= disc_curve, projection_curve= candidate_curve)
        for inst in self.instruments], dtype= float)
        return np.where(np.isfinite(residuals), residuals, 1e6)
        #Los inf/nan de tasas locas se penalizan, asi los errores de codigo aparecen
    def build(self) -> YieldCurve:
        n_instruments = len(self.instruments)
        first_rate = self.instruments[0].rate #Hay que poner una buena primera estimacion por lo que usamos la del primer instrumento
        initial_guess = np.full(n_instruments, first_rate)
        result = least_squares(
            fun= self._objective_function,
            x0= initial_guess,
            method= 'lm',
            xtol= 1e-13, # Tolerancia extrema en el paso (eje X)
            ftol= 1e-13, # Tolerancia extrema en el error (eje Y)
            gtol= 1e-13, # Tolerancia en el gradiente (planitud)
        )
        max_res = np.max(np.abs(result.fun))
        if not result.success or max_res > 1e-8:
            raise RuntimeError(f"El bootstrap no ha convergido: {result.message} (residuo max = {max_res:.2e})")
        final_rates = result.x
        curva_interpolada = self._build_curve_from_rates(final_rates)
        return ExtrapolatedYieldCurve(curva_interpolada, self.nudos[-1], f_inf= self.f_inf)
        #Durante la optimizacion usamos solo la curva interpolada porque no hay instrumentos mas alla del ultimo nudo, la extrapolacion solo se añade a la curva final
if __name__ == "__main__":
    market_data = [
        # (Nombre, Vencimiento/Frecuencia, Tasa)
        Deposit("Depo 6M", 0.5, 0.0250),
        FRA("FRA 6x12", 0.5, 1.0, 0.0280),
        Swap.from_market_data("Swap 2Y", np.array([1.0, 2.0]), 0.0300),
        Swap.from_market_data("Swap 3Y", np.array([1.0, 2.0, 3.0]), 0.0320),
        Swap.from_market_data("Swap 5Y", np.array([1.0, 2.0, 3.0, 4.0, 5.0]), 0.0350),
        Swap.from_market_data("Swap 10Y", np.arange(1, 11), 0.0400),
        Swap.from_market_data("Swap 15Y", np.arange(1, 16), 0.0420),
    ]
    """Cogemos los datos que sean, estos son solo de muestra"""
    engine = Bootstrapper(market_data)
    my_curve = engine.build()
    max_error = 0.0
    for inst in market_data:
        err = inst.residual(my_curve)
        max_error = max(max_error, abs(err))
        status = "OK" if abs(err) < 1e-8 else "FAIL"
        print(f"{inst.name:10s} residual = {float(err):+.2e} {status}")
    print(f"Error maximo: {max_error:.2e}")
    import matplotlib.pyplot as plt
    t_plot = np.linspace(0, 15, 100)
    zeros = my_curve.get_zero_rate(t_plot)
    plt.figure(figsize=(10, 6))
    plt.plot(t_plot, zeros * 100, label='Curva Zero Bootstrapped', linewidth=2)
    pillar_t = engine.nudos
    pillar_r = my_curve.get_zero_rate(pillar_t)
    plt.scatter(pillar_t, pillar_r*100, color='red', zorder=5, label='Nudos (Instrumentos)')
    plt.title("Estructura Temporal de Tipos de Interés (Bootstrapped)")
    plt.xlabel("Tiempo (Años)")
    plt.ylabel("Tasa Zero (%)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.show()
    print("\nGráfico generado.")