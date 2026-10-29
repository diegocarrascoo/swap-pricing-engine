import numpy as np
from abc import ABC, abstractmethod
from typing import Optional, Union
from numpy.typing import ArrayLike, NDArray
from scipy.interpolate import CubicSpline
FloatOrArray = Union[float, NDArray[np.float64]]
#Las curvas aceptan un plazo suelto o un array de plazos: con un numero devuelven un float y con un array devuelven un array de la misma forma
#Antes las anotaciones decian t: float -> float, pero el codigo necesitaba arrays (get_zero_rate, el swap vectorizado...) y Python no comprueba las anotaciones,
#asi que una curva nueva hecha con math.exp parecia funcionar hasta que algo le pasaba un array. Ahora el contrato esta escrito y ademas se comprueba
class YieldCurve(ABC):
    """Las subclases solo implementan _discount_factor (y si saben, _forward_rate), que SIEMPRE reciben un array de numpy y devuelven otro de la misma forma.
    Los metodos publicos get_... convierten la entrada y la salida, asi esa logica esta en un solo sitio y ninguna curva tiene que repetirla
    Es el patron "template method": la clase padre fija los pasos (convertir, calcular, comprobar, devolver) y las hijas solo rellenan el calculo"""
    def get_discount_factor(self, t: ArrayLike) -> FloatOrArray:
        t_arr = self._to_array(t)
        return self._from_array(t, self._evaluate("_discount_factor", t_arr))
        #El resto del codigo (instrumentos, bootstrapper, pricer) sigue llamando a get_discount_factor como siempre, para ellos no cambia nada
    def get_zero_rate(self, t: ArrayLike) -> FloatOrArray:
        t_arr = self._to_array(t)
        df = self._evaluate("_discount_factor", t_arr)
        zeros = np.empty_like(t_arr)
        mask = t_arr > 1e-12
        zeros[mask] = -np.log(df[mask]) / t_arr[mask]
        #Como t_arr siempre es un array, df tambien lo es y df[mask] ya no falla aunque la curva este hecha por otra persona
        if not mask.all():
            """Para t=0 usamos una aproximacion con un delta pequeño, asi evitamos dividir por 0"""
            zeros[~mask] = -np.log(self.get_discount_factor(1e-5)) / 1e-5
        return self._from_array(t, zeros)
    def get_forward_rate(self, t: ArrayLike) -> FloatOrArray:
        """Forward instantaneo f(t) = -d(log DF)/dt"""
        #Antes era (DF(t)/DF(t+dt) - 1)/dt con dt = 0.001, que pide un DF 0.001 años mas alla de t y por eso fallaba en el ultimo tramo de la curva interpolada,
        #incluido el propio ultimo nudo. Ahora cada curva calcula su forward en _forward_rate: las que pueden de forma exacta y el resto con la derivada numerica de abajo
        t_arr = self._to_array(t)
        return self._from_array(t, self._evaluate("_forward_rate", t_arr))
    @abstractmethod
    def _discount_factor(self, t: NDArray[np.float64]) -> NDArray[np.float64]:
        """Cada curva solo tiene que saber dar el DF para un array de plazos"""
        pass
    def _forward_rate(self, t: NDArray[np.float64]) -> NDArray[np.float64]:
        #Por defecto derivamos numericamente, las curvas que saben calcularlo de forma exacta lo sobreescriben (la interpolada y la extrapolada)
        h = 1e-6
        #Con h tan pequeño el error de la aproximacion es despreciable, y como solo lo usan curvas sin limite por la derecha (plana, Nelson-Siegel) mirar t + h no da problemas
        log_df = np.log(self._evaluate("_discount_factor", t))
        log_df_h = np.log(self._evaluate("_discount_factor", t + h))
        return (log_df - log_df_h) / h
    @staticmethod
    def _to_array(t: ArrayLike) -> NDArray[np.float64]:
        t_arr = np.atleast_1d(np.asarray(t, dtype= np.float64))
        #atleast_1d convierte un numero suelto en un array de 1 elemento, asi las subclases nunca tienen que preocuparse de si les llega un numero o un array
        if not t_arr.min() >= 0:
            raise ValueError(f"Los plazos tienen que ser numeros >= 0 (t = 0 es el dia de valoracion), ha llegado t = {t}")
            #Un plazo negativo seria una fecha anterior al dia de valoracion: antes la curva daba DF(-1) = 1.03 sin quejarse
            #Con "not >= 0" tambien pillamos los NaN: el minimo de un array con un NaN es NaN, y cualquier comparacion con NaN da False
            #Usamos t_arr.min() y no np.all(t_arr >= 0) porque esto se ejecuta en cada llamada a la curva (decenas de miles en un bootstrap) y es mas del doble de rapido
        return t_arr
    @staticmethod
    def _from_array(t_original: ArrayLike, values: NDArray[np.float64]) -> FloatOrArray:
        #Si nos pasaron un numero devolvemos un float de Python, no un array de dimension 0 (por eso antes hacia falta poner float(err) al imprimir)
        return float(values[0]) if np.ndim(t_original) == 0 else values.reshape(np.shape(t_original))
    def _evaluate(self, metodo: str, t: NDArray[np.float64]) -> NDArray[np.float64]:
        """Llama a _discount_factor o _forward_rate y comprueba que cumplen el contrato, asi un error en una curva nueva salta en el primer uso con un mensaje claro"""
        contrato = (f"{type(self).__name__}.{metodo} recibe siempre un array de numpy y tiene que devolver otro de la misma forma, "
                    f"usa funciones de numpy (np.exp) y no de math (math.exp)")
        try:
            values = np.asarray(getattr(self, metodo)(t), dtype= np.float64)
        except TypeError as e:
            raise TypeError(f"{contrato}. Error original: {e}") from e
            #El TypeError tipico es usar math.exp con un array, explicamos el contrato pero con "from e" para no perder el error original
        if values.shape != t.shape:
            raise TypeError(f"{contrato}. Con t de forma {t.shape} ha devuelto {values.shape}")
            #Esto pilla las curvas que devuelven un unico numero para todos los plazos
        return values
class InterpolatedYieldCurve(YieldCurve):
    def __init__(self, times: np.ndarray, discount_factors: np.ndarray):
        self.times = np.asarray(times)
        self.dfs = np.asarray(discount_factors)
        if self.times.ndim != 1 or self.times.shape != self.dfs.shape:
            raise ValueError(f"times y discount_factors tienen que ser dos listas del mismo tamaño ({self.times.shape} y {self.dfs.shape})")
        if not np.all(self.dfs > 0) or not np.all(np.isfinite(self.dfs)):
            raise ValueError(f"Los factores de descuento tienen que ser positivos y finitos: {self.dfs}")
            #Interpolamos el log del DF y el log de un numero <= 0 no existe: antes salia NaN y scipy fallaba con un "y must contain only finite values" que no dice cual es el problema
        self._logs_df = np.log(self.dfs)
        self._interpolator = CubicSpline(self.times, self._logs_df, bc_type='natural', extrapolate=True)
    def _check_range(self, t: NDArray[np.float64]):
        #Lo sacamos a su propio metodo porque ahora lo necesitan tanto _discount_factor como _forward_rate
        if np.any(t > self.times[-1] + 1e-12):
            raise ValueError(f"t = {np.max(t):.4f} esta fuera de la curva (ultimo nudo {self.times[-1]}), para plazos mas largos hay que usar ExtrapolatedYieldCurve")
            #Preferimos que falle a que use la extrapolacion cubica del spline, que se inventa los forwards sin que ningun dato lo justifique
    def _discount_factor(self, t: NDArray[np.float64]) -> NDArray[np.float64]:
        #Ya no hace falta el np.asarray del principio, la clase base nos pasa siempre un array
        self._check_range(t)
        return np.exp(self._interpolator(t))
    def _forward_rate(self, t: NDArray[np.float64]) -> NDArray[np.float64]:
        self._check_range(t)
        return -self._interpolator(t, 1)
        #Como interpolamos log DF con un spline, el spline nos da su derivada exacta (el 1 es el orden de la derivada) y el forward es menos esa derivada
        #Asi no hay que mirar un dt mas alla de t, por lo que funciona hasta el ultimo nudo, y ademas es exacto en vez de una aproximacion
class ExtrapolatedYieldCurve(YieldCurve):
    """Envuelve cualquier curva y solo actua cuando se piden plazos mas alla del ultimo dato, asi separamos la interpolacion (que la hace la curva base) de la extrapolacion (que la hace esta clase).
    Es el mismo patron que con las convenciones de dias: si queremos otro metodo de extrapolacion solo hay que crear otra clase, sin tocar la curva base.
    A partir de t_max el forward va convergiendo hacia un forward de largo plazo (f_inf), que es la misma idea que usa Smith-Wilson en Solvencia II con el UFR"""
    def __init__(self, base_curve: YieldCurve, t_max: float, f_inf: Optional[float] = None, a: float = 0.1):
        if a <= 0:
            raise ValueError("La velocidad de convergencia a tiene que ser positiva.")
        self.base_curve = base_curve
        self.t_max = t_max
        self._log_df_max = float(np.log(base_curve.get_discount_factor(t_max)))
        h = 1e-6
        self._fwd_max = (float(np.log(base_curve.get_discount_factor(t_max - h))) - self._log_df_max) / h
        #El forward instantaneo es menos la derivada del log DF, lo sacamos con una diferencia hacia atras para usar solo puntos de dentro de la curva base
        #Si la base es el spline natural, su segunda derivada es 0 en el extremo, asi que el forward llega plano a t_max y la extrapolacion empieza sin saltos ni picos
        self.f_inf = f_inf if f_inf is not None else self._fwd_max
        #Si todavia no tenemos un f_inf calibrado con datos historicos usamos el forward de t_max, que es lo mismo que un flat forward
        self.a = a
        #a es la velocidad de convergencia, con a = 0.1 a los ln(2)/0.1 = 7 años ya hemos recorrido la mitad del camino hasta f_inf
        #Es un valor razonable para empezar pero lo suyo es calibrarlo tambien con datos historicos
    def _log_df_extrapolado(self, t: np.ndarray) -> np.ndarray:
        """El forward que queremos es f(s) = f_inf + (f_T - f_inf)*e^(-a(s-T)), y como log DF(t) = log DF(T) - integral de f entre T y t,
        integrando a mano sale una formula cerrada, asi no hace falta integrar numericamente en cada llamada"""
        dt = t - self.t_max
        integral_fwd = self.f_inf * dt + (self._fwd_max - self.f_inf) * (1 - np.exp(-self.a * dt)) / self.a
        return self._log_df_max - integral_fwd
    def _discount_factor(self, t: NDArray[np.float64]) -> NDArray[np.float64]:
        df_base = self.base_curve.get_discount_factor(np.minimum(t, self.t_max))
        #Con el minimum a la curva base nunca le pedimos plazos fuera de sus datos, asi no salta su error ni se usa su extrapolacion
        df_extra = np.exp(self._log_df_extrapolado(np.maximum(t, self.t_max)))
        #Con el maximum los t de dentro de la curva dan dt = 0 en la formula, asi no calculamos exponenciales raras que luego no vamos a usar
        return np.where(t <= self.t_max, df_base, df_extra)
        #np.where elige para cada t si usamos la curva base (dentro) o la extrapolacion (fuera), y funciona igual con un numero que con un array
    def _forward_rate(self, t: NDArray[np.float64]) -> NDArray[np.float64]:
        #Mismo esquema que _discount_factor: dentro le preguntamos a la curva base y fuera usamos directamente la formula del forward que hemos elegido
        f_base = self.base_curve.get_forward_rate(np.minimum(t, self.t_max))
        f_extra = self.f_inf + (self._fwd_max - self.f_inf) * np.exp(-self.a * (np.maximum(t, self.t_max) - self.t_max))
        #Es el f(s) del docstring de _log_df_extrapolado, asi el forward es exacto y coherente con los DF que damos
        return np.where(t <= self.t_max, f_base, f_extra)
    def is_extrapolated(self, t: float) -> np.ndarray:
        """Nos dice que plazos caen fuera de los datos, sirve para saber si un precio depende de algo que no hemos observado en el mercado"""
        return np.asarray(t, dtype= np.float64) > self.t_max
    def with_f_inf(self, f_inf: float) -> "ExtrapolatedYieldCurve":
        """Devuelve la misma curva con otro forward de largo plazo, asi podemos mover f_inf para medir el riesgo sin rehacer el bootstrap
        Se puede porque f_inf no interviene en la calibracion, solo cambia la zona extrapolada"""
        return ExtrapolatedYieldCurve(self.base_curve, self.t_max, f_inf= f_inf, a= self.a)
class FlatYieldCurve(YieldCurve):
    def __init__(self, flat_rate: float):
        self.r = flat_rate
    def _discount_factor(self, t: NDArray[np.float64]) -> NDArray[np.float64]:
        #Solo damos el DF, la conversion de numeros a arrays y el forward los pone la clase base
        return np.exp(-self.r*t)
class NelsonSiegelCurve(YieldCurve):
    def __init__(self, beta0: float, beta1: float, beta2: float, tau: float):
        if not np.all(np.isfinite([beta0, beta1, beta2])):
            raise ValueError(f"Las betas tienen que ser numeros finitos: {beta0}, {beta1}, {beta2}")
        if not tau > 0:
            raise ValueError(f"tau tiene que ser positivo, ha llegado {tau}")
            #tau es la escala de tiempo de la curva y aparece dividiendo en t/tau: con tau = 0 se divide por cero y con tau < 0 las exponenciales explotan
        self.beta0 = beta0
        self.beta1 = beta1
        self.beta2 = beta2
        self.tau = tau
    def _nelson_siegel_spot(self, t: NDArray[np.float64]) -> NDArray[np.float64]:
        t_safe = np.maximum(t, 1e-12) #Asi nos deshacemos de las divisiones por cero
        term1 = (1 - np.exp(-t_safe/self.tau)) / (t_safe/self.tau)
        term2 = term1 - np.exp(-t_safe/self.tau)
        return self.beta0 + self.beta1 * term1 + self.beta2 * term2
    def _discount_factor(self, t: NDArray[np.float64]) -> NDArray[np.float64]:
        #Igual que en la curva plana, solo damos el DF y el resto lo pone la clase base
        r = self._nelson_siegel_spot(t)
        return np.exp(-r * t)
