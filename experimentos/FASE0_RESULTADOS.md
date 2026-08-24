# FASE 0 — ¿vale `PASO=2` para las métricas de fase?

**Sí.** Con la definición de fase adecuada, pasar de 30 a 15 Hz mueve el ratio
ecc/con un 2,5 % de sesgo y ±10 % de dispersión, por debajo de la variabilidad
del propio atleta entre repeticiones de la misma serie. `PASO=2` se queda.

Reproducir:

```bash
python experimentos/fase0_paso.py . --salida resultados/fase0 --diagnostico --autotest
```

Material: 4 vídeos (`opo` 18 rep, `fp` 7, `asdasd` 6, `bandicam` 3), modelo
`lite`, 31 repeticiones emparejadas. Es una comprobación, no un estudio.

## Lo que salió

Acuerdo entre pasos, Bland-Altman, diferencia = paso2 − paso1:

| magnitud | sesgo | sesgo rel. | dispersión (1,96·sd) |
|---|---|---|---|
| ratio ecc/con | +0,023 | +2,5 % | ±10,2 % |
| t_subida | −0,012 s | −1,3 % | ±6,9 % |
| t_bajada | +0,014 s | +1,1 % | ±8,2 % |
| ROM | −0,007 bu | −0,5 % | ±2,9 % |
| v pico concéntrica | +0,027 bu/s | +0,7 % | ±17,3 % |

El conteo de repeticiones coincide en los 4 vídeos, y el de válidas también.

Criterio del spec, por vídeo —el agrupado no sirve solo, lo manda la serie más
sucia:

| vídeo | n | sd intra-serie | \|sesgo\| | 1,96·sd_dif | |
|---|---|---|---|---|---|
| opo | 16 | 0,065 | 0,017 | 0,049 | pasa |
| bandicam | 3 | 0,125 | 0,032 | 0,114 | pasa |
| asdasd | 5 | 0,442 | 0,050 | 0,135 | pasa |
| fp | 7 | 0,601 | 0,013 | 0,297 | pasa |

Lo que cierra el caso es `opo`: es la serie limpia, su variabilidad intra-serie
es genuinamente baja (0,065) y aun así el desacuerdo entre pasos cabe dentro
(0,049). En `fp` y `asdasd` el criterio pasa con holgura, pero pasa por la razón
mala —variabilidad alta— y no cuenta como evidencia.

## El hallazgo que importa más que el `paso`

**La definición de fase pesa 3-4 veces más que el muestreo.** El primer intento
definía cada fase como el tramo contiguo de velocidad por encima del umbral
alrededor del extremo. Con esa definición:

| magnitud | dispersión, def. contigua | dispersión, def. acumulada |
|---|---|---|
| ratio ecc/con | ±32,9 % | ±10,2 % |
| t_subida | ±37,8 % | ±6,9 % |
| t_bajada | ±44,9 % | ±8,2 % |

La causa está en `resultados/fase0/diag_fp_p1.png`: la excéntrica real de una
dominada **no es monótona**. El atleta cae rápido, frena a media altura y baja
en deriva lenta hasta el dead hang. La velocidad vuelve a cruzar el umbral en
mitad del descenso, el tramo contiguo se queda solo con el primer trozo, y que
ese cruce marginal caiga de un lado o de otro depende del muestreo. Lo mismo
pasa en la concéntrica de `opo`: en `diag_opo_p2.png` se ve el doble pico de
velocidad del *sticking point*.

La definición que sobrevive: **tiempo total en movimiento dentro de la fase**
—suma de todos los tramos por encima del umbral entre valle y pico, con los
cruces interpolados a sub-muestra—. Es inmune a que la fase se parta y de paso
deja fuera las pausas. Es la que va por defecto (`--definicion acumulada`).

Sin la interpolación sub-muestra de los cruces, el experimento habría medido su
propia cuantización: 1/15 s sobre una fase de 0,7 s es un 9 %, del orden del
efecto que se quería medir.

## Números que hay que llevarse a FASE 1

1. **`t_subida`, `t_bajada`, `ratio` y `ROM`: paso=2 vale.** ±3-10 %.
2. **`v_pico` de una repetición suelta: ±17 %.** Es un extremo instantáneo, lo
   más sensible al muestreo que hay aquí. No se enseña rep a rep sin decir la
   incertidumbre.
3. **La caída de velocidad —la pendiente— sí aguanta**, porque una regresión
   promedia el ruido de cada punto: −0,078 vs −0,067 bu/s por rep en `opo`,
   −0,52 vs −0,58 en `fp`. Signo y magnitud se conservan; la segunda cifra
   significativa no.
4. **El instante del pico no está bien definido cuando hay pausa arriba.** La
   cresta es plana y el `argmax` salta: en `opo` rep 8 el pico cae en 27,32 s
   con paso=1 y en 26,70 s con paso=2, 0,62 s de diferencia. No afecta a las
   duraciones de fase —esas las fijan los cruces de velocidad, no el pico— pero
   sí a cualquier cosa que ancle en `instante_s`.
5. **El umbral por velocidad aplana el ratio.** En el autotest, un ratio real de
   1,50 se mide como 1,39 y uno de 2,50 como 2,13. Es sesgo de la definición,
   idéntico en los dos pasos, y se corrige bajando `FRAC_UMBRAL_V`. Hay que
   decidirlo en FASE 1: el ratio que enseñe la app no es el ratio real del
   tempo, es el ratio de tiempo en movimiento.

## Lo que este experimento NO dice

- Nada sobre el modelo `heavy`: todo se corrió con `lite`.
- Nada sobre generalización. 4 vídeos, 2 atletas, 31 repeticiones.
- Nada sobre exactitud. Compara paso=1 con paso=2; ninguno de los dos es la
  verdad. La verdad haría falta medirla con otra cosa.
