# Piedra, papel o tijera contra el G1

Le decís **"arrancar"**, el robot canta la cuenta con el brazo, tira su jugada
con los dedos, y la webcam mira qué hiciste vos para decidir quién ganó.

```
   vos  ->  webcam  ->  MediaPipe  ->  piedra | papel | tijera
                                              |
   robot  ->  simulador MuJoCo  <-  socket  <-+->  arbitro  ->  voz
```

## Antes de la primera vez

**1. El entorno** (una sola vez). Los launchers del TP ya prefieren este venv:

```bash
/opt/homebrew/bin/python3.12 -m venv ~/.venvs/unitree && ~/.venvs/unitree/bin/pip install -U pip mujoco 'mediapipe==0.10.35' opencv-python vosk sounddevice
```

Va en **3.12**: mediapipe y vosk no publican ruedas para 3.13 ni 3.14.

**mediapipe va clavada en 0.10.35.** La 1.0.x se cae en macOS ARM apenas abre
el grafo, con cualquier combinacion de delegate y modo:

```
F0000 graph_service.h:139] Check failed: service_ Service is unavailable.
    @ -[DrishtiMetalHelper initWithCalculatorContext:]
```

Le pide un servicio de Metal que no esta registrado. La 0.10.35 usa la misma
API (Tasks) y anda, asi que no hay que cambiar una linea de codigo -- solo no
dejar que pip la actualice.

**2. Los modelos** (66 MB, no están en git — ver `.gitignore`):

```bash
curl -L --create-dirs -o modelos/hand_landmarker.task https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
```

```bash
curl -L -o /tmp/v.zip https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip && unzip -q -o /tmp/v.zip -d modelos && mv modelos/vosk-model-small-es-0.42 modelos/vosk-es
```

**3. Permisos de macOS.** La app desde la que corrés esto (Terminal, iTerm,
VS Code) necesita **Cámara** y **Micrófono** en Ajustes del Sistema →
Privacidad y seguridad. Si ya se los negaste una vez, el diálogo no vuelve a
aparecer: hay que prenderlos a mano y **cerrar y reabrir la terminal**. Sin
permiso la cámara devuelve cuadros negros y el micro silencio, **sin dar
error**.

## Jugar

Dos terminales.

```bash
cd ../../entorno && ~/.venvs/unitree/bin/python -m sim --robot g1_mano --materia tp07
```

**Sobre macOS y `mjpython`.** La ventana 3D solo abre bajo el lanzador propio
de MuJoCo: `launch_passive` necesita el bucle de eventos de Cocoa en el hilo
principal. Con `python` a secas el simulador arrancaba igual pero caia al modo
consola — y el aviso quedaba tapado apenas la vista de texto se redibujaba
encima, asi que ni se veia el motivo. Ahora **se relanza solo bajo `mjpython`**
(ver `_relanzar_con_mjpython` en `entorno/sim/__main__.py`), asi que el comando
de arriba anda tal cual.

Si el simulador te dice que no puede abrir el puerto 8765, quedo otro corriendo:

```bash
pkill -f "sim --robot"
```

```bash
~/.venvs/unitree/bin/python jugar.py
```

Decí **"arrancar"** (o apretá **espacio**). Se juega una ronda atrás de
otra, todas las que quieras. **ESC** para salir — es la única salida, a
propósito (ver abajo).

**Cambiar de cámara sin salir:** en la ventana, **TAB** pasa a la siguiente que
responda, o apretá el **número** de la que quieras (`0`, `1`, `2`…). El índice
en uso se ve abajo a la derecha. Cambiar corta la ronda en curso: los cuadros
de dos cámaras distintas no se pueden votar juntos. También sirve `--camara 1`
al arrancar.

La cuenta va **palabra por palabra**: el robot dice *"piedra"* y da un golpe
con el brazo, *"papel"* y otro golpe, *"tijera"* y otro, y en el *"ya"* tira.
Cada golpe espera a que el `say` **termine de verdad** en vez de adivinar
cuánto tarda, así que el brazo va al ritmo de la voz en cualquier máquina.
Medido: 0.00 / 1.10 / 2.25 / 3.35 s, parejo desde la primera ronda.

Si algo falla, cada pieza corre sola:

| | |
|---|---|
| `python vision.py` | solo la webcam: te dice qué jugada te lee, en vivo (TAB cambia de cámara) |
| `python voz.py` | solo la voz: habla y después escucha |
| `python jugar.py --sin-robot` | el juego entero sin abrir el simulador |
| `python jugar.py --sin-voz` | sin micrófono ni parlantes, se juega con espacio |

En el simulador también podés tirar a mano con el teclado de la ventana:
**O** piedra, **A** papel, **V** tijera, **Y** la cuenta, **B** festeja, **F** se lamenta.

## Por qué el robot no hace trampa

El robot **elige y sella su jugada antes de que exista un solo cuadro de la
ventana de captura**. No es una promesa: publica el SHA-256 de su jugada más un
número al azar, y al final revela las dos cosas para que cualquiera recalcule
el sello.

```
  [COMPROMISO] el robot ya eligio. sello=3639eb722e040683
  [REVELA]  jugada=papel  sal=4f829d5976150bbe
            sha256('papel|4f829d5976150bbe') empieza con 3639eb722e040683  -> verifica
```

Queda registrado en `partidas.csv`. Si el marcador no da cerca de
1/3 - 1/3 - 1/3 en muchas manos, algo se rompió.

## Cómo reacciona al resultado

| resultado | qué hace |
|---|---|
| gana el robot | **bailecito**: los dos brazos arriba subiendo y bajando alternados, con la cintura acompañando |
| gana el humano | **se lamenta**: se agacha, se inclina adelante y se agarra la cabeza con la derecha |
| empate | nada |

Lo alternado del baile no es decorativo. `vibra` hacía oscilar todas las
articulaciones **en fase**, así que los dos brazos subían juntos y parecía un
temblor, no un baile. Por eso ahora `Gesto` tiene **`desfase`** (articulación →
radianes de corrimiento): con π entre un brazo y el otro, se alternan.

La reacción no arranca en el momento del resultado sino **cuando el brazo
termina de tirar** (2.3 s después del "ya"). La envolvente de un gesto vale 0 en
las dos puntas, así que uno que termina y otro que empieza empalman solos;
cortar uno sostenido por la mitad, en cambio, da un salto de imagen.

Dos cosas del lamento que costaron y quedaron medidas:

- **Doblar las rodillas no agacha al robot, le levanta los pies.** Sin física la
  base se escribe a una altura fija. Medido: con la rodilla en 1.00 los pies
  suben 8.4 cm, así que el gesto baja la base esos mismos 8.4 cm. Verificado:
  los pies quedan clavados al piso durante todo el gesto y la cabeza baja 11 cm.
- **La mano hubo que optimizarla tres veces.** Con la posición sola, la muñeca
  llegaba a la cabeza pero con la mano en cualquier ángulo (dedos para abajo).
  Pidiendo además los dedos verticales, la mano terminaba *arriba* de la cabeza
  y los dos dedos parecían antenas. Lo que funciona es: muñeca en la sien
  (queda a 1 mm), palma mirando a la cabeza (0.98 de 1), dedos a **38°** y
  **cerrados** — con los dedos estirados se lee como un saludo militar.

## El micrófono no se escucha al robot

El robot habla por los parlantes y el micrófono lo oye. Con una **gramática
cerrada** eso es peor que un falso positivo suelto: vosk empuja todo lo que
escucha hacia la palabra más parecida de la lista. El robot decía *"decí
arrancar"* y el juego arrancaba solo antes de que llegaras a poner la mano, y
al cantar el resultado disparaba cualquier otra.

Por eso `Oido.callar()` tapa la entrada mientras el robot habla (y 1.2 s
después, por el eco de la sala), y **"salir" no está en el vocabulario**: para
salir está ESC. El saludo de bienvenida tampoco se dice en voz alta.

## Cómo muestra el robot su jugada

La mano Dex3-1 tiene pulgar, índice y medio: alcanza para las tres jugadas.
Pero **no tiene abducción** — índice y medio son paralelos y no se abren en V —
así que con los dedos solos papel y tijera se diferenciaban nada más que por el
pulgar, y de lejos eran iguales.

Se resuelve con la **orientación de la mano**, que se lee de mucho más lejos
que un dedo:

| | mano | dedos respecto del piso | pulgar |
|---|---|---|---|
| **piedra** | parada | puño cerrado | — |
| **papel** | **acostada**, 8° del piso | **−0.1°**, horizontales | **abajo** |
| **tijera** | **parada**, 90° del piso | **+73°**, verticales | recogido |

Los ángulos no son a ojo: salieron de optimizar sobre el modelo la posición y
la orientación a la vez, y están medidos. El pulgar para abajo en papel importa
— con la mano acostada pero el pulgar al techo, el pulgar se lee como un dedo
más levantado, que es justo lo que confunde con tijera.

Las dos jugadas terminan en el mismo punto del espacio (0.33, −0.20, 1.00), y
eso es lo que las hace leer como el mismo gesto con distinto contenido.

Dos cosas que salieron de medir el modelo, no de suponer:

- **El alcance hombro→muñeca es de apenas 0.375 m** y el hombro está a 1.085 m.
  Por eso la mano se presenta a 1.00 m: más arriba se tapa con la cabeza, y más
  adelante no llega. También por eso el G1 de este robot **para con los brazos
  colgando** y no recogidos como el `g1` común: con el antebrazo levantado, la
  mano izquierda quieta se llevaba la atención que tiene que tener la derecha.
- **En MuJoCo `azimuth` es hacia dónde MIRA la cámara, no dónde está.** La
  escena tenía −40 creyendo que la ponía adelante y a la derecha; en realidad la
  dejaba **detrás** del robot, con el cuerpo tapando la mano. Ahora es −135.

## Cómo lee la mano

MediaPipe da 21 puntos. Un dedo cuenta como estirado si **la punta está más
lejos de la muñeca que el nudillo medio** *y* **el dedo está derecho**. Las dos
condiciones son internas a la mano, así que funciona con la mano girada, de
costado, dada vuelta, y a cualquier distancia — a diferencia del clásico "la
punta está más arriba", que se rompe apenas inclinás la muñeca.

Después: 0 o 1 dedos = piedra, 4 = papel, **exactamente índice y medio** =
tijera. Cualquier otra cosa no vota.

La ventana de captura dura ~0.9 s (unos 27 cuadros) y se decide por mayoría.
**La ronda se anula** si hay menos de 6 cuadros con mano, si la mayoría no
llega al 55%, o si cambiaste la mano a mitad de camino. Anular es mejor que
adivinar: un robot que dice "no te vi" es creíble, uno que se equivoca no.

## Archivos

| | |
|---|---|
| `jugar.py` | máquina de estados y bucle principal |
| `vision.py` | MediaPipe → piedra/papel/tijera |
| `voz.py` | `Voz` (hablar) y `Oido` (escuchar). `VozRobot` habla por el G1 real |
| `arbitro.py` | reglas, marcador y el compromiso sellado |

Un solo hilo, menos el micrófono: el pulso lo marca `camara.read()`. Nada más
bloquea, y en macOS `cv2.imshow` tiene que correr en el hilo principal.
