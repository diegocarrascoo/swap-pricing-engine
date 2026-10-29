# Swap Pricing Engine: Calculo de tipos de interés en Python

**Esto ha sido un proyecto pedagogico** 
El fin de este repositorio ha sido para aprender sobre instrumentos y familiarizarme con la renta fija, asi como con la construccion de las curvas de tipos y la aplicacion de los metodos cuantitativos a finanzas

## Contiene

El proyecto se basa en varios scripts en los que paso a paso va construyendo una curva de tipos:

**Convenciones** 
El motor ha de valorar las posibles opciones de convenciones que se usan y los diferentes calendarios, asi como computar el numero de dias.

**Generacion de calendarios de pago**

**Instrumentos**
Depositos, FRAs y swaps de tipo fijo contra flotante

**Curvas de tipos**
Interpola usando splines cubicos sobre el log de los factores de descuento, extrapola con convergencia a un forward de largo plazo y curvas de Nelson-Siegel

**Bootstrapping**
Calibra la curva a partir de las cotizaciones de mercado (datos dados)

**Dual curve** 
Utiliza un metodo de curva dual (estandar tras 2008) ya que descuenta con la curva OIS y proyecta con euribor

**Pricing**
NPV, tipos par y sensibilidad de la zona extrapolada de la curva

## Estructura
| Archivo | Contenido |
|---|---|
| `ClasesConvencionesDias.py` | Convenciones de cómputo de días |
| `CalendarSetup.py` | Calendarios y ajuste de fechas |
| `ScheduleGenerator.py` | Calendarios de pago |
| `YieldCurveClasses.py` | Curvas de tipos (interpolada, extrapolada, plana, Nelson-Siegel) |
| `ClasesInstrumetos.py` | Depósitos, FRAs y swaps |
| `InstrumentBuilder.py` | Construye instrumentos a partir de fechas y convenciones reales |
| `Bootstrapper.py` | Calibración de curvas |
| `PricingEngine.py` | Datos de mercado y valoración |
| `solver_playground.py` | Demo completa: curvas OIS y Euribor (dual curve) |
| `vis_interpolation.py` | Comparación visual entre interpolación lineal y spline |

## Ejecucion
ecesitas Python 3.10 o superior.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r Requirements.txt
```

Demos:

```bash
python solver_playground.py   # Dual curve OIS + Euribor 6M
python Bootstrapper.py        # Bootstrap de una sola curva
python vis_interpolation.py   # Lineal vs spline cúbico
```

## Notas
Ademas los datos de mercado que aparecen en el codigo son inventados para usar de ejemplo y que de lugar a curvas sencillas de entender. Los comentarios son mios para entender yo el porque de cada cosa