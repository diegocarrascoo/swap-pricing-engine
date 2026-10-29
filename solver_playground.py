import numpy as np
import matplotlib.pyplot as plt
from datetime import date
from typing import List, Tuple
from ClasesInstrumetos import Deposit, FRA, Swap, Instrument
from Bootstrapper import Bootstrapper
from CalendarSetup import TARGET
from InstrumentBuilder import InstrumentBuilder, MarketConventions
from PricingEngine import MarketData, PricingEngine
from YieldCurveClasses import YieldCurve
#Antes todo el codigo estaba suelto en el fichero, y Python ejecuta todo lo que esta suelto cada vez que alguien hace import de este fichero
#Si otro script hacia "from solver_playground import ois_curve" para reutilizar la curva, se ejecutaban los dos bootstraps, se imprimia la verificacion y se abria el grafico
#Ahora la construccion del mercado esta en funciones (que se pueden importar sin ejecutar nada) y lo que imprime y pinta esta en main(), que solo se ejecuta al lanzar este fichero
valuation_date = date(2026, 10, 23) #Es el t = 0 de todas las curvas
E6M = "EURIBOR6M"
def build_ois_curve() -> YieldCurve:
    market_data_ois = [
        Deposit("OIS Depo 1D", 0.0027, 0.0150, index="ESTR"), # Muy corto plazo
        Swap.from_market_data("OIS 1Y", np.array([1.0]), 0.0155, index="ESTR"),
        Swap.from_market_data("OIS 2Y", np.array([1.0, 2.0]), 0.0160, index="ESTR"),
        Swap.from_market_data("OIS 5Y", np.arange(1, 6), 0.0175, index="ESTR"),
        Swap.from_market_data("OIS 10Y", np.arange(1, 11), 0.0190, index="ESTR"),
    ]
    engine_ois = Bootstrapper(market_data_ois)
    return engine_ois.build()
def build_market() -> Tuple[MarketData, InstrumentBuilder, List[Instrument]]:
    """Construye las dos curvas y las mete en un MarketData. Devuelve tambien el builder y los instrumentos del Euribor por si los queremos usar fuera"""
    ois_curve = build_ois_curve()
    #El builder pasa las fechas y convenciones del mercado (spot T+2, TARGET, ACT/360, 30/360) a los plazos t que entienden las curvas
    #Por defecto la pata fija es anual y la flotante semestral, como en un swap Euribor 6M
    builder = InstrumentBuilder(valuation_date, MarketConventions(TARGET()))
    market_data_ibor = [
        # Normalmente el primer punto viene de un FRA o Depo Euribor
        builder.deposit("Euribor 6M Depo", 6, 0.0250, index= E6M), # Notar que es 2.5% vs 1.5% OIS (Spread de crédito)
        builder.swap("Swap 2Y", 24, 0.0300, index= E6M),
        builder.swap("Swap 5Y", 60, 0.0350, index= E6M),
        builder.swap("Swap 10Y", 120, 0.0400, index= E6M),
    ]
    engine_ibor = Bootstrapper(market_data_ibor, external_discount_curve=ois_curve)
    ibor_curve = engine_ibor.build()
    market = MarketData(valuation_date)
    market.set_discount_curve(ois_curve, index_name= "ESTR")
    market.add_projection_curve(E6M, ibor_curve, engine_ibor) #Con el bootstrapper, asi extrapolation_risk puede recalibrarla
    return market, builder, market_data_ibor
def main():
    market, builder, market_data_ibor = build_market()
    pricer = PricingEngine(market)
    ois_curve = market.get_discount_curve()
    ibor_curve = market.get_projection_curve(E6M)

    # Verificación de un instrumento
    swap_check = market_data_ibor[-1] # El Swap de 10Y al 4.00%
    # Preciamos usando ambas curvas, el pricer sabe por el index del swap que tiene que proyectar con la curva Euribor
    print(f"Spot: {builder.spot_date}")
    print(f"NPV {swap_check.name}: {float(pricer.calculate_npv(swap_check)):+.2e} (deberia ser 0, es un instrumento de calibracion)")
    print(f"Tipo par {swap_check.name}: {pricer.calculate_par_rate(swap_check):.4%}")

    t_plot = np.linspace(0.1, 10, 100)
    ois_zeros = ois_curve.get_zero_rate(t_plot)
    ibor_zeros = ibor_curve.get_zero_rate(t_plot)

    plt.figure(figsize=(10, 6))
    plt.plot(t_plot, ois_zeros * 100, label='OIS Curve (Descuento)', color='green', linestyle='--')
    plt.plot(t_plot, ibor_zeros * 100, label='Euribor 6M Curve (Proyección)', color='blue')
    plt.title("Dual Curve Stripping: El Spread de Crédito")
    plt.xlabel("Años")
    plt.ylabel("Tasa Zero (%)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.show()
if __name__ == "__main__":
    main()
    #__name__ vale "__main__" solo cuando ejecutamos este fichero directamente (python solver_playground.py)
    #Cuando otro fichero lo importa, __name__ vale "solver_playground" y main() no se llama: el import solo define las funciones, no ejecuta nada
