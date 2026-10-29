import numpy as np
import matplotlib.pyplot as plt
from scipy.interpolate import CubicSpline
"""Vamos a poner unos datos arbitrarios ya que esto es solo para ver las diferencias entre las interpolaciones"""
times = np.array([0.0, 1.0, 2.0, 5.0, 10.0, 30.0, 50.0, 75.0])
rates = np.array([0.02, 0.025, 0.028, 0.035, 0.040, 0.038, 0.029, 0.03]) # Tipos zero
dfs = np.exp(-rates * times) # DFs correspondientes
log_dfs = np.log(dfs)
"""Para la interpolacion lineal"""
def linear_interp(t):
    return np.interp(t, times, log_dfs)
#Antes usabamos interp1d de scipy, pero esta marcada como "legacy": la mantienen pero recomiendan no usarla en codigo nuevo. Para la lineal np.interp hace exactamente lo mismo
#Ojo: fuera de los nudos np.interp no da error, repite el valor del extremo. Por eso mas abajo no le pedimos plazos mas alla de 75
"""Para la interpolacion cubica, es mejor porque es suave"""
#El spline cubico es un polinomio de grado 3 entre cada par de nudos, elegido para que en cada nudo los dos tramos que se juntan tengan el mismo valor,
#la misma primera derivada y la misma segunda derivada. Eso es lo que lo hace suave: no hay esquinas ni cambios bruscos de curvatura
#"natural" significa que la segunda derivada es 0 solo en los dos extremos (t=0 y t=75). En los nudos de dentro ni la primera ni la segunda derivada son 0
#(antes el comentario decia que lo eran, y no es asi: por ejemplo en t=1 la primera derivada es -0.028 y la segunda -0.0077)
#Como el forward es menos la derivada del log DF: con la interpolacion lineal el forward es plano en cada tramo y salta en cada nudo, con el spline es una curva continua
cubic_interp = CubicSpline(times, log_dfs, bc_type='natural')
"""Para ver los forwards que nos dan esta interpolaciones definimos una funcion que nos los de"""
def get_fwd(interpolator, t, dt = 0.001):
    y_t = interpolator(t)
    y_t_dt = interpolator(t+dt)
    return (y_t - y_t_dt) / dt
t_fine = np.linspace(0.1, 74.9, 1000) #Los tiempos que tenemos llegan hasta 75 y get_fwd tambien mira t + dt, asi que cogemos 1000 valores entre 0.1 y 74.9 para no salirnos de los datos
fwd_linear = get_fwd(linear_interp, t_fine)
fwd_cubic = get_fwd(cubic_interp, t_fine)
zero_linear = -linear_interp(t_fine) / t_fine
zero_cubic = -cubic_interp(t_fine) / t_fine
#El tipo zero es -log DF / t, asi tambien vemos como queda la curva zero con cada interpolacion
"""Ahora solo queda plotear para ver la diferencia entre los forwards"""
fig, (ax_zero, ax_fwd) = plt.subplots(2, 1, figsize=(10, 9), sharex= True)
#Antes los puntos rojos (los tipos zero de entrada) estaban en el grafico de forwards, pero un tipo zero y un forward son cosas distintas:
#el zero es la media de los forwards desde hoy hasta t, por eso en 30Y el punto rojo marcaba 3.80% cuando el forward real del spline era 2.32%
#Ahora cada cosa va en su grafico: arriba los tipos zero junto con los datos de entrada, y abajo los forwards. sharex hace que los dos compartan el eje de tiempo
ax_zero.plot(t_fine, zero_linear, label='Zero (Interpolación Lineal)', linestyle='--')
ax_zero.plot(t_fine, zero_cubic, label='Zero (Spline Cúbico)', linewidth=2)
ax_zero.scatter(times[1:], rates[1:], color='red', zorder=5, label='Nudos (Input)')
ax_zero.set_title("Tipos zero: las dos interpolaciones pasan por los mismos nudos")
ax_zero.set_ylabel("Tasa Zero")
ax_zero.legend()
ax_zero.grid(True, alpha=0.3)
ax_fwd.plot(t_fine, fwd_linear, label='Forward (Interpolación Lineal)', linestyle='--')
ax_fwd.plot(t_fine, fwd_cubic, label='Forward (Spline Cúbico)', linewidth=2)
ax_fwd.scatter(times[1:], get_fwd(cubic_interp, times[1:]), color = 'green', zorder=5, label = 'Forward del spline en los nudos')
#Son los forwards instantaneos del spline justo en los nudos, por eso caen encima de la curva del spline
ax_fwd.set_title("El Problema de la Suavidad: Lineal vs Spline")
ax_fwd.set_ylabel("Tasa Forward Instantánea")
ax_fwd.set_xlabel("Tiempo (Años)")
ax_fwd.legend()
ax_fwd.grid(True, alpha=0.3)
plt.tight_layout()
plt.show()
