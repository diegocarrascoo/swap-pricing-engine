from datetime import date
from typing import Dict, Optional, Tuple, Union
from YieldCurveClasses import YieldCurve, ExtrapolatedYieldCurve
from ClasesInstrumetos import Instrument, Swap
from Bootstrapper import Bootstrapper
class MarketData:
    def __init__(self, as_of_date: Union[date, str]):
        self.as_of_date = date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else as_of_date
        #Es el dia que corresponde a t = 0 en todas las curvas
        self._discount_curve: Optional[YieldCurve] = None
        self._projection_curves: Dict[str, YieldCurve] = {}
        self._bootstrappers: Dict[str, Bootstrapper] = {}
        #Guardamos con que se ha construido cada curva de proyeccion para poder recalibrarla si cambia la de descuento
    def set_discount_curve(self, curve: YieldCurve, index_name: Optional[str] = None):
        self._discount_curve = curve #Curva OIS
        if index_name is not None:
            #La OIS tambien es la curva de proyeccion de su propio indice (ESTR), asi los swaps OIS se precian igual que el resto
            self._projection_curves[index_name] = curve
    def add_projection_curve(self, index_name: str, curve: YieldCurve, bootstrapper: Optional[Bootstrapper] = None):
        self._projection_curves[index_name] = curve
        #Añade una curva de proyeccion para un indice especifico
        if bootstrapper is not None:
            self._bootstrappers[index_name] = bootstrapper
    def get_discount_curve(self) -> YieldCurve:
        if self._discount_curve is None:
            raise ValueError("La curva de descuento no ha sido inicializada.")
        return self._discount_curve
    def get_projection_curve(self, index_name: str) -> YieldCurve:
        if index_name not in self._projection_curves:
            raise ValueError(f"No se encontró curva de proyección para: {index_name}")
        return self._projection_curves[index_name]
    def get_bootstrapper(self, index_name: str) -> Optional[Bootstrapper]:
        return self._bootstrappers.get(index_name)

class PricingEngine:
    def __init__(self, market_data: MarketData):
        self.market = market_data
    def _resolve_index(self, instrument: Instrument, projection_index: Optional[str]) -> str:
        """El indice sale del propio instrumento, projection_index solo sirve para instrumentos que no lo tienen.
        Si no hay ninguno fallamos, antes se proyectaba con la OIS sin avisar y el precio salia mal"""
        if projection_index is not None and instrument.index is not None and projection_index != instrument.index:
            raise ValueError(f"{instrument.name} proyecta con {instrument.index}, no con {projection_index}")
        index = instrument.index if instrument.index is not None else projection_index
        if index is None:
            raise ValueError(f"{instrument.name} no tiene indice de proyeccion, indicalo al crearlo (index=...)")
        return index
    def calculate_npv(self, instrument: Instrument, projection_index: Optional[str] = None) -> float:
        disc_curve = self.market.get_discount_curve()
        proj_curve = self.market.get_projection_curve(self._resolve_index(instrument, projection_index))
        return instrument.npv(discount_curve= disc_curve, projection_curve= proj_curve)
    def calculate_par_rate(self, instrument: Swap, projection_index: Optional[str] = None) -> float:
        """Calcula la tasa par (Fair Rate) que haría que el NPV del swap sea 0."""
        disc_curve = self.market.get_discount_curve()
        proj_curve = self.market.get_projection_curve(self._resolve_index(instrument, projection_index))
        annuity = instrument.annuity(disc_curve)
        if annuity == 0:
            raise ValueError(f"La anualidad del swap {instrument.name} es 0, no se puede calcular la tasa par.")
        return instrument.float_leg_pv(disc_curve, proj_curve) / annuity
    def extrapolation_risk(self, instrument: Instrument, projection_index: Optional[str] = None, bump: float = 0.0001,
                           f_inf_shifts: Optional[Tuple[float, float]] = None) -> Dict[str, float]:
        """Mide cuanto depende el precio de la parte de la curva que no hemos observado en el mercado (la extrapolada)
        Lo ponemos aqui y no en la curva porque el riesgo depende del instrumento: un swap a 10Y sobre una curva hasta 15Y no tiene ningun riesgo de extrapolacion y uno a 30Y si"""
        index = self._resolve_index(instrument, projection_index)
        disc_curve = self.market.get_discount_curve()
        proj_curve = self.market.get_projection_curve(index)
        bootstrapper = self.market.get_bootstrapper(index)
        def mover(curve: YieldCurve, shift: float) -> YieldCurve:
            #Solo las curvas extrapoladas tienen f_inf, al resto las dejamos igual
            if isinstance(curve, ExtrapolatedYieldCurve):
                return curve.with_f_inf(curve.f_inf + shift)
            return curve
        def depende_de_extrapolacion() -> bool:
            #La curva de proyeccion se calibro con la de descuento, si tiene instrumentos mas alla del ultimo dato de la de descuento
            #ha usado su zona extrapolada y al mover f_inf hay que recalibrarla, si no los swaps de mercado dejan de valer 0
            return (bootstrapper is not None and bootstrapper.external_discount_curve is not None
                    and isinstance(disc_curve, ExtrapolatedYieldCurve) and bootstrapper.nudos[-1] > disc_curve.t_max)
        recalibrar = depende_de_extrapolacion()
        def escenario(shift: float) -> Tuple[YieldCurve, YieldCurve]:
            disc_movida = mover(disc_curve, shift)
            if proj_curve is disc_curve:
                return disc_movida, disc_movida
            if not recalibrar:
                return disc_movida, mover(proj_curve, shift)
            #Movemos el f_inf de todas las curvas lo mismo, asi se mantiene el spread entre la curva de descuento y la de proyeccion
            f_inf_proj = proj_curve.f_inf + shift if isinstance(proj_curve, ExtrapolatedYieldCurve) else bootstrapper.f_inf
            nueva = Bootstrapper(bootstrapper.instruments, external_discount_curve= disc_movida, f_inf= f_inf_proj).build()
            return disc_movida, nueva
        npv_base = instrument.npv(disc_curve, proj_curve)
        npv_up = instrument.npv(*escenario(bump))
        resultado = {"npv": npv_base, "sens_f_inf": (npv_up - npv_base) / bump * 0.0001}
        #La sensibilidad es por punto basico de f_inf, asi se lee igual que un DV01: cuanto cambia el NPV si f_inf sube un 0.01%
        if f_inf_shifts is not None:
            #Cuando calibremos con datos historicos estos desplazamientos serian por ejemplo los percentiles 5 y 95 de f_inf respecto a su valor central
            npvs = [instrument.npv(*escenario(s)) for s in f_inf_shifts]
            resultado["npv_min"] = min(npvs)
            resultado["npv_max"] = max(npvs)
            resultado["incertidumbre"] = (max(npvs) - min(npvs)) / 2
            #La mitad del rango es lo que nos podemos equivocar hacia cada lado por no conocer la curva mas alla de los datos
        return resultado
