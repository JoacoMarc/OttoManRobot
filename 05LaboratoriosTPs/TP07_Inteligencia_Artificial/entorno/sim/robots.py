"""Los dos robots reales: donde esta su modelo oficial y como se anima cada uno.

Usamos los modelos OFICIALES de Unitree (repo unitreerobotics/unitree_mujoco),
no una figura inventada: el alumno tiene que ver el robot que despues va a usar.

El movimiento es CINEMATICO: escribimos la pose y llamamos mj_forward, sin
correr fisica. Es a proposito:

  - El G1 es un humanoide y SE CAE SOLO sin un controlador de locomocion. El
    simulador oficial no trae ese controlador (vive en la PC interna del robot
    y Unitree no lo publica). Con fisica real, el robot se desploma antes de
    que el alumno pueda probar nada.
  - Un TP de programacion evalua el algoritmo, no la marcha. Si el robot se
    tropieza, el alumno recibe roja por algo que no es suyo.

La animacion de las patas es COSMETICA: el robot se desliza. Sirve para que se
vea que camina, no para simular como camina.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

# Donde buscar los modelos oficiales, en orden.
UBICACIONES = [
    # Primero los que vienen DENTRO del paquete: es lo que tiene un profesor
    # que bajo su carpeta y nada mas. Antes iba primero ~/unitree_libs, asi que
    # en la maquina de Teo se usaban esos y los del paquete no se probaban nunca.
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 "unitree_mujoco", "unitree_robots"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "unitree_robots"),
    os.path.expanduser("~/unitree_libs/unitree_mujoco/unitree_robots"),
    os.path.expanduser("~/unitree_mujoco/unitree_robots"),
    os.path.join(os.getcwd(), "unitree_mujoco", "unitree_robots"),
]


ESCENA_LIMPIA = """<mujoco model="{modelo} - escena limpia UADE">
  <!-- Generado por el laboratorio UADE. NO es un archivo oficial de Unitree.
       La escena oficial del Go2 trae 8 cajas de obstaculo, incluida una
       escalera, y dos vigas que cruzan justo por donde se dibuja la grilla del
       TP03: el robot parecia atravesar paredes. Esta escena tiene el mismo
       robot y el mismo piso, sin esos obstaculos.
       Se regenera solo si se borra. No modifica ningun archivo oficial. -->
  <include file="{incluye}"/>

  <statistic center="0 0 0.1" extent="1.2"/>

  <visual>
    <headlight diffuse="0.6 0.6 0.6" ambient="0.35 0.35 0.35" specular="0 0 0"/>
    <rgba haze="0.15 0.25 0.35 1"/>
    <global azimuth="-130" elevation="-20"/>
  </visual>

  <asset>
    <texture type="skybox" builtin="gradient" rgb1="0.3 0.5 0.7" rgb2="0 0 0"
             width="512" height="3072"/>
    <texture type="2d" name="groundplane_uade" builtin="checker" mark="edge"
             rgb1="0.2 0.3 0.4" rgb2="0.1 0.2 0.3" markrgb="0.8 0.8 0.8"
             width="300" height="300"/>
    <material name="groundplane_uade" texture="groundplane_uade" texuniform="true"
              texrepeat="5 5" reflectance="0.2"/>
  </asset>

  <worldbody>
    <light pos="0 0 1.5" dir="0 0 -1" directional="true"/>
    <geom name="floor" size="0 0 0.05" type="plane" material="groundplane_uade"/>
  </worldbody>
</mujoco>
"""



# El modelo con manos viene de unitree_ros y trae su propio piso, su luz y su
# cielo. Si le sumaramos los de ESCENA_LIMPIA, MuJoCo corta con "repeated name
# 'floor' in geom". Asi que esta escena NO agrega cuerpos: solo reencuadra.
#
# El azimut esta girado respecto del oficial (-130) a proposito: el robot tira
# con la mano derecha y la camara tiene que verla de frente.
#
# OJO CON LA CONVENCION: en MuJoCo `azimuth` es HACIA DONDE MIRA la camara, no
# donde esta parada. O sea que la camara queda en el angulo opuesto. Con -135
# mira hacia atras-izquierda, es decir esta adelante y a la derecha del robot,
# que es de donde la mano se ve entera. Probado contra el modelo barriendo todo
# el circulo: con -40 la camara quedaba DETRAS y el cuerpo tapaba la mano.
ESCENA_MANO = """<mujoco model="{modelo} - escena UADE">
  <!-- Generado por el laboratorio UADE. NO es un archivo oficial de Unitree.
       Se regenera solo si se borra. No modifica ningun archivo oficial. -->
  <include file="{incluye}"/>

  <statistic center="0.16 -0.10 0.98" extent="1.1"/>

  <visual>
    <headlight diffuse="0.65 0.65 0.65" ambient="0.4 0.4 0.4" specular="0.1 0.1 0.1"/>
    <rgba haze="0.15 0.25 0.35 1"/>
    <global azimuth="-135" elevation="-8" offwidth="1280" offheight="960"/>
  </visual>
</mujoco>
"""


def _generar_escena_limpia(destino: str, incluye: str,
                           plantilla: str = ESCENA_LIMPIA) -> str:
    """Escribe la escena sin obstaculos al lado del modelo oficial."""
    contenido = plantilla.format(
        modelo=os.path.splitext(incluye)[0], incluye=incluye)
    with open(destino, "w", encoding="utf-8") as f:
        f.write(contenido)
    return destino


@dataclass
class Gesto:
    """Un gesto COSMETICO del simulador: una pose y como se llega a ella.

    Solo los dispara el teclado de la ventana, y viven enteros dentro del
    proceso del simulador. NO estan en la lista blanca de `acciones.py` y no
    los puede pedir el programa del alumno: esa lista es la misma que usa el
    laboratorio fisico y prohibe justamente esto -- saltar y cambiar de
    postura -- porque con el robot real se cae o lastima a alguien.

        articulaciones  indice de articulacion -> radianes, la pose del gesto
        altura          cuanto sube la base, en metros (el salto)
        vibra           indice -> amplitud, para agitar la mano al saludar
        ciclos          cuantas idas y vueltas da `vibra` en todo el gesto
        desfase         indice -> radianes de corrimiento de esa vibracion.
                        Sin esto todas las articulaciones oscilan EN FASE, y
                        un baile con los dos brazos subiendo y bajando juntos
                        no parece un baile: parece un temblor. Con pi de
                        desfase entre un brazo y el otro, se alternan.
        sostenido       si la pose se mantiene mientras dura el gesto
        duracion        segundos
    """

    articulaciones: dict = field(default_factory=dict)
    altura: float = 0.0
    vibra: dict = field(default_factory=dict)
    ciclos: float = 3.0
    desfase: dict = field(default_factory=dict)
    sostenido: bool = False
    duracion: float = 1.6
    descripcion: str = ""


# Cuanto tarda un gesto sostenido en entrar y en salir, en fraccion del total.
RAMPA = 0.15


def envolvente(gesto: Gesto, progreso: float) -> float:
    """Cuanto del gesto se aplica, entre 0 y 1, segun lo avanzado que este.

    Vale 0 en las dos puntas a proposito: asi el robot sale de la pose de pie
    y vuelve a ella, sin el salto de imagen que daba escribir la pose entera de
    una (que es lo que se hacia con el saludo).
    """
    p = min(1.0, max(0.0, progreso))
    if gesto.sostenido:
        # Trapecio: entra, se queda puesta, y se va sin golpe.
        return min(1.0, p / RAMPA, (1.0 - p) / RAMPA)
    return math.sin(math.pi * p)


@dataclass
class Robot:
    clave: str
    nombre: str
    tipo: str
    escena: str          # ruta relativa dentro de unitree_robots/
    altura: float        # altura de la base al estar de pie, en metros
    incluye: str = ""    # si esta, generamos una escena limpia que lo incluya
    plantilla: str = ""  # con que plantilla; por defecto, ESCENA_LIMPIA
    # Encuadre inicial de la ventana. En 0 vale el de siempre (3.5 m para
    # un humanoide, 2.6 para el perro), que mira al robot entero. El G1 con
    # manos necesita estar mas cerca: la jugada se lee en los dedos, y a
    # 3.5 m la mano ocupa quince pixeles.
    camara_distancia: float = 0.0
    camara_altura: float = 0.0     # a que altura mira, en metros
    camara_elevacion: float = 0.0  # en grados; 0 = la de siempre (-20)
    pose_de_pie: dict = field(default_factory=dict)   # indice art -> radianes
    # Indices (dentro de qpos, contando desde la primera articulacion) que se
    # animan al caminar: (indice, amplitud, desfase)
    marcha: list = field(default_factory=list)
    saludo: dict = field(default_factory=dict)
    pose_sentado: dict = field(default_factory=dict)
    # nombre de la accion -> Gesto. La clave es la que queda en `mundo.accion`,
    # asi que es la que busca el simulador para saber que dibujar.
    gestos: dict = field(default_factory=dict)

    def ruta_escena(self) -> str | None:
        for base in UBICACIONES:
            ruta = os.path.join(base, self.escena)
            if os.path.exists(ruta):
                return ruta
            # Escena limpia: la generamos al lado del modelo oficial si falta.
            if self.incluye:
                modelo = os.path.join(base, os.path.dirname(self.escena),
                                      self.incluye)
                if os.path.exists(modelo):
                    return _generar_escena_limpia(
                        ruta, self.incluye,
                        self.plantilla or ESCENA_LIMPIA)
        return None


# --- G1: humanoide de 29 grados de libertad -----------------------------
# Indices relativos (qpos real = 7 + indice), leidos del orden de <joint> de
# g1_29dof.xml: el `floating_base_joint` ocupa qpos[0:7], asi que la primera
# articulacion de verdad -- left_hip_pitch -- es el indice 0.
G1_L_HIP_P, G1_L_KNEE = 0, 3
G1_R_HIP_P, G1_R_KNEE = 6, 9
G1_R_ANKLE_P = 10
G1_L_SHOULDER_P, G1_L_ELBOW = 15, 18
G1_R_SHOULDER_P, G1_R_ELBOW = 22, 25

# El saludo se usa en dos lados (el campo `saludo` y la tabla de gestos), asi
# que los angulos viven en un solo lugar.
_G1_SALUDO = {G1_R_SHOULDER_P: -2.4, G1_R_ELBOW: -1.0}

G1 = Robot(
    clave="g1",
    nombre="Unitree G1",
    tipo="humanoide",
    escena="g1/scene_29dof.xml",   # scene.xml tiene ~100 obstaculos del terrain_tool
    altura=0.793,
    pose_de_pie={
        G1_L_SHOULDER_P: 0.20, G1_R_SHOULDER_P: 0.20,
        G1_L_ELBOW: -0.30, G1_R_ELBOW: -0.30,
    },
    marcha=[
        (G1_L_HIP_P, 0.40, 0.0),
        (G1_R_HIP_P, 0.40, math.pi),
        (G1_L_KNEE, 0.45, 1.1),
        (G1_R_KNEE, 0.45, 1.1 + math.pi),
        (G1_L_SHOULDER_P, 0.30, math.pi),
        (G1_R_SHOULDER_P, 0.30, 0.0),
    ],
    saludo=_G1_SALUDO,
    # Agachado (FSM Sit / Damp). No es un desplome: es una postura.
    pose_sentado={G1_L_HIP_P: -1.2, G1_R_HIP_P: -1.2,
                  G1_L_KNEE: 1.8, G1_R_KNEE: 1.8},
    gestos={
        # "saludo" es como lo nombra la lista blanca cuando el gesto llega por
        # el socket. El servicio sport por DDS lo llama "saludando": ese alias
        # se agrega abajo, apuntando a este mismo gesto.
        "saludo": Gesto(
            articulaciones=_G1_SALUDO, vibra={G1_R_ELBOW: 0.35}, duracion=2.2,
            descripcion="saluda con la mano"),
        "dar_la_mano": Gesto(
            articulaciones={G1_R_SHOULDER_P: -1.35, G1_R_ELBOW: -0.5},
            sostenido=True, duracion=2.5,
            descripcion="extiende la mano"),
        # Pierna derecha al frente con la rodilla estirada. Los signos salen
        # de pose_sentado: cadera negativa lleva el muslo adelante y rodilla
        # positiva la dobla, asi que la patada es cadera adelante y rodilla
        # casi en cero.
        "patada": Gesto(
            articulaciones={G1_R_HIP_P: -1.0, G1_R_KNEE: 0.15,
                            G1_R_ANKLE_P: -0.2},
            duracion=1.0,
            descripcion="patea con la pierna derecha"),
        # Sin fisica, un salto es la base subiendo mientras recoge las piernas.
        "salto": Gesto(
            articulaciones={G1_L_HIP_P: -0.5, G1_R_HIP_P: -0.5,
                            G1_L_KNEE: 0.95, G1_R_KNEE: 0.95},
            altura=0.30, duracion=0.9,
            descripcion="salta"),
        # El modelo oficial de 29 DOF tiene las manos de goma FIJAS, sin
        # articulaciones de dedos: lo mas parecido a agarrar que se puede
        # dibujar es estirar los dos brazos al frente.
        "agarre": Gesto(
            articulaciones={G1_L_SHOULDER_P: -1.5, G1_R_SHOULDER_P: -1.5,
                            G1_L_ELBOW: -0.35, G1_R_ELBOW: -0.35},
            sostenido=True, duracion=4.0,
            descripcion="estira los brazos como para agarrar"),
    },
)

# --- G1 con manos Dex3-1: el mismo humanoide, pero con dedos -------------
# Usa `g1_29dof_with_hand.xml`, que suma la mano de 3 dedos (pulgar, indice y
# medio: 7 DOF por mano). Ese modelo no viene en unitree_mujoco; esta en
# unitree_ros/robots/g1_description. Las 16 mallas de las manos se bajaron al
# lado de las otras, que se comparten.
#
# ES UN ROBOT APARTE Y NO UNA VARIANTE DE G1, A PROPOSITO. Los dedos de la
# mano IZQUIERDA se meten en el MEDIO del orden de qpos, asi que todo lo que
# viene despues se corre 7 lugares:
#
#     left_wrist_yaw          21  ->  21   (igual)
#     dedos izquierdos        --  ->  22-28
#     right_shoulder_pitch    22  ->  29   (+7)
#     right_elbow             25  ->  32
#     dedos derechos          --  ->  36-42
#
# Si tocaramos G1, los indices que usan los otros seis TPs apuntarian a un
# dedo en vez de a un hombro.
M_L_HIP_P, M_L_KNEE = 0, 3
M_R_HIP_P, M_R_KNEE = 6, 9
M_R_ANKLE_P = 10
M_L_SHOULDER_P, M_L_SHOULDER_R, M_L_ELBOW = 15, 16, 18
M_CINTURA_Y, M_CINTURA_P = 12, 14
M_R_SHOULDER_P, M_R_SHOULDER_R, M_R_SHOULDER_Y = 29, 30, 31
M_R_ELBOW = 32
M_R_WRIST_R, M_R_WRIST_P, M_R_WRIST_Y = 33, 34, 35
# Mano derecha. OJO CON LOS SIGNOS: las dos manos estan espejadas. En la
# DERECHA cerrar el dedo es POSITIVO (indice y medio van de 0 a ~1.75), pero
# el pulgar cierra hacia NEGATIVO (thumb_2 va de -1.745 a 0). En la izquierda
# es al reves. Se usa solo la derecha, que es con la que se tira.
M_R_TH0, M_R_TH1, M_R_TH2 = 36, 37, 38    # pulgar: gira + dos falanges
M_R_MID0, M_R_MID1 = 39, 40               # medio
M_R_IDX0, M_R_IDX1 = 41, 42               # indice

# Mano en reposo, un poco curvada. Con todos los dedos en cero la mano queda
# plana y tiesa, y ademas "papel" no se distinguiria de estar parado sin
# hacer nada.
_MANO_RELAJADA = {M_R_IDX0: 0.25, M_R_IDX1: 0.30,
                  M_R_MID0: 0.25, M_R_MID1: 0.30,
                  M_R_TH1: 0.20, M_R_TH2: -0.35}

# Las tres manos del juego.
_PIEDRA = {M_R_IDX0: 1.45, M_R_IDX1: 1.70,
           M_R_MID0: 1.45, M_R_MID1: 1.70,
           M_R_TH0: 0.50, M_R_TH1: 0.70, M_R_TH2: -1.60}
_PAPEL = {M_R_IDX0: 0.0, M_R_IDX1: 0.0,
          M_R_MID0: 0.0, M_R_MID1: 0.0,
          M_R_TH0: -0.90, M_R_TH1: -1.00, M_R_TH2: 0.0}
# La Dex3 no tiene abduccion: el indice y el medio son paralelos y no se
# pueden abrir en V. Con los dedos solos, papel y tijera se diferenciaban nada
# mas que por el pulgar, y de lejos no se distinguian. Se resuelve con la
# ORIENTACION DE LA MANO, que se lee de mucho mas lejos que un dedo (ver
# _MANO_PLANA y _MANO_PARADA abajo).
_TIJERA = {M_R_IDX0: 0.0, M_R_IDX1: 0.0,
           M_R_MID0: 0.0, M_R_MID1: 0.0,
           M_R_TH0: 0.50, M_R_TH1: 0.70, M_R_TH2: -1.60}

# COMO SE PRESENTA LA MANO. Esto es lo que separa papel de tijera, no los
# dedos: la Dex3 no tiene abduccion -- indice y medio son paralelos y no se
# abren en V --, asi que con los dedos solos las dos jugadas se diferenciaban
# nada mas que por el pulgar y de lejos eran iguales. La orientacion de la mano
# se lee de mucho mas lejos que un dedo.
#
# Los angulos NO son a ojo: salieron de buscar sobre el modelo optimizando a la
# vez la posicion (mano adelante y del lado de la camara, lejos del cuerpo) y
# la orientacion. Medido sobre el modelo:
#
#   acostada   dedos a  -0.1 grados del piso, plano de la mano a 8 grados
#              (o sea horizontal), y el pulgar 4.4 cm POR DEBAJO de la muneca
#   parada     dedos a +73.0 grados, plano de la mano a 90 grados (vertical)
#
# El pulgar para abajo en papel importa: acostada pero con el pulgar al techo,
# el pulgar se lee como un dedo mas levantado, que es justo lo que confunde
# con tijera.
# La mano cae en los dos casos en (0.33, -0.20, 1.00): adelante, del lado de
# la camara, y 25 cm por DEBAJO de la cabeza. Que las dos terminen en el mismo
# punto es lo que las hace leer como el mismo gesto con distinto contenido, y
# que sea abajo es lo que evita que la mano se tape con la cabeza. Ojo: el
# hombro esta en z=1.085 y el alcance hombro->muneca es de apenas 0.375 m, asi
# que no se puede estirar mas que esto.
_BRAZO_ACOSTADO = {M_R_SHOULDER_P: -0.83, M_R_SHOULDER_R: -0.55,
                   M_R_SHOULDER_Y: 0.38, M_R_ELBOW: 0.68,
                   M_R_WRIST_R: -0.98, M_R_WRIST_P: 0.02, M_R_WRIST_Y: 0.05}
_BRAZO_PARADO = {M_R_SHOULDER_P: -0.94, M_R_SHOULDER_R: -0.16,
                 M_R_SHOULDER_Y: -0.51, M_R_ELBOW: 1.02,
                 M_R_WRIST_R: -0.01, M_R_WRIST_P: -1.20, M_R_WRIST_Y: 0.24}


def _tiro(mano: dict, brazo: dict = None) -> dict:
    """Un tiro = como se presenta la mano + que hacen los dedos."""
    return {**(brazo or _BRAZO_PARADO), **mano}


# --- Las dos reacciones al resultado -------------------------------------
# Festejo: los dos brazos arriba y abiertos, subiendo y bajando ALTERNADOS,
# con la cintura acompanando. Lo alternado es todo: con `vibra` sola las dos
# articulaciones oscilan en fase y los dos brazos suben juntos, que no parece
# un baile sino un temblor. Por eso existe `desfase`.
_BAILE = {
    M_L_SHOULDER_P: -1.50, M_R_SHOULDER_P: -1.50,
    M_L_SHOULDER_R: 1.10, M_R_SHOULDER_R: -1.10,
    M_L_ELBOW: 0.20, M_R_ELBOW: 0.20,
}

# Lamento: se agacha, se inclina adelante y se agarra la cabeza con la derecha.
#
# Doblar las rodillas NO baja al robot: sin fisica la base se escribe a una
# altura fija, asi que lo unico que pasa es que los PIES SE LEVANTAN. Medido:
# con la rodilla en 1.00 suben 8.4 cm, y por eso el gesto baja la base los
# mismos 8.4 cm. Sin eso el robot se agacha flotando.
_LAMENTO_RODILLA, _LAMENTO_CADERA = 1.00, -0.60
_LAMENTO = {
    M_CINTURA_P: 0.35,                 # positivo = se inclina adelante
    M_L_HIP_P: _LAMENTO_CADERA, M_R_HIP_P: _LAMENTO_CADERA,
    M_L_KNEE: _LAMENTO_RODILLA, M_R_KNEE: _LAMENTO_RODILLA,
    # Brazo derecho a la SIEN. Optimizado contra el modelo con el torso ya
    # agachado, pidiendo tres cosas juntas: que la muneca llegue a la sien
    # (queda a 1 mm), que la palma MIRE A LA CABEZA (0.98 de 1) y que los dedos
    # apunten hacia arriba pero SOLO 38 grados.
    #
    # Las tres hicieron falta, y en dos pasadas:
    #   - solo con la posicion, la muneca llegaba pero la mano quedaba en
    #     cualquier angulo, con los dedos para abajo;
    #   - despues, con los dedos verticales y estirados, la mano terminaba
    #     ARRIBA de la cabeza y los dos dedos parecian antenas.
    # De ahi los 38 grados y los dedos cerrados de abajo.
    M_R_SHOULDER_P: -1.58, M_R_SHOULDER_R: -0.25, M_R_SHOULDER_Y: 0.04,
    M_R_ELBOW: -1.02,
    M_R_WRIST_R: -0.22, M_R_WRIST_P: -0.02, M_R_WRIST_Y: -0.55,
    # Mano cerrada contra la cabeza. Con los dedos estirados se lee como un
    # saludo militar, no como agarrarse la cabeza.
    M_R_IDX0: 0.95, M_R_IDX1: 1.10, M_R_MID0: 0.95, M_R_MID1: 1.10,
    M_R_TH0: 0.30, M_R_TH1: 0.45, M_R_TH2: -1.00,
}


G1_MANO = Robot(
    clave="g1_mano",
    nombre="Unitree G1 con manos Dex3",
    tipo="humanoide",
    # No hay escena oficial para este modelo: se genera una limpia al lado,
    # igual que con el Go2.
    escena="g1/scene_mano_uade.xml",
    incluye="g1_29dof_with_hand.xml",
    plantilla=ESCENA_MANO,
    camara_distancia=1.7,
    camara_altura=0.98,
    camara_elevacion=-8.0,
    altura=0.793,
    # Brazos COLGANDO, no recogidos. El G1 comun se para con el codo en -0.30,
    # que son ~100 grados de flexion (el cero del codo ya es ~83: el antebrazo
    # sale en +x mientras el brazo cuelga en -z). O sea los dos antebrazos
    # levantados al frente. Para este juego eso molesta: la mano izquierda,
    # quieta y bien a la vista, se lleva la atencion que tiene que tener la
    # derecha, que es la que tira. Con el codo en 1.15 el brazo queda casi
    # derecho y cae al costado.
    pose_de_pie={
        M_L_SHOULDER_P: 0.15, M_R_SHOULDER_P: 0.15,
        M_L_ELBOW: 1.15, M_R_ELBOW: 1.15,
        **_MANO_RELAJADA,
    },
    marcha=[
        (M_L_HIP_P, 0.40, 0.0),
        (M_R_HIP_P, 0.40, math.pi),
        (M_L_KNEE, 0.45, 1.1),
        (M_R_KNEE, 0.45, 1.1 + math.pi),
        (M_L_SHOULDER_P, 0.30, math.pi),
        (M_R_SHOULDER_P, 0.30, 0.0),
    ],
    saludo={M_R_SHOULDER_P: -2.4, M_R_ELBOW: -1.0},
    pose_sentado={M_L_HIP_P: -1.2, M_R_HIP_P: -1.2,
                  M_L_KNEE: 1.8, M_R_KNEE: 1.8},
    gestos={
        "saludo": Gesto(
            articulaciones={M_R_SHOULDER_P: -2.4, M_R_ELBOW: -1.0},
            vibra={M_R_ELBOW: 0.35}, duracion=2.2,
            descripcion="saluda con la mano"),
        "dar_la_mano": Gesto(
            articulaciones={M_R_SHOULDER_P: -1.35, M_R_ELBOW: -0.5},
            sostenido=True, duracion=2.5,
            descripcion="extiende la mano"),
        # --- piedra, papel o tijera ---
        # La cuenta: el brazo va al frente con el puno cerrado y da tres
        # golpes. Los tres salen de `vibra`, que suma sin(progreso * 6*pi):
        # eso es EXACTAMENTE tres oscilaciones por gesto, ni una mas.
        "preparar": Gesto(
            articulaciones=_tiro(_PIEDRA),
            vibra={M_R_ELBOW: 0.45}, duracion=2.4,
            descripcion="cuenta antes de tirar"),
        # UN golpe solo. La cuenta se canta palabra por palabra -- "piedra",
        # "papel", "tijera" -- y cada palabra lleva su golpe, sincronizado con
        # la voz. Por eso `ciclos=1`: con los 3 de `preparar` el brazo hacia
        # toda la cuenta sobre la primera palabra.
        "golpe": Gesto(
            articulaciones=_tiro(_PIEDRA),
            vibra={M_R_ELBOW: 0.55}, ciclos=1.0, duracion=0.75,
            descripcion="un golpe de la cuenta"),
        # Las tres jugadas son `sostenido`: con la envolvente trapezoidal la
        # pose SE QUEDA PUESTA mientras la camara mira, en vez de ir y volver.
        "piedra": Gesto(
            articulaciones=_tiro(_PIEDRA), sostenido=True, duracion=2.2,
            descripcion="tira piedra"),
        "papel": Gesto(
            articulaciones=_tiro(_PAPEL, _BRAZO_ACOSTADO),
            sostenido=True, duracion=2.2,
            descripcion="tira papel"),
        "tijera": Gesto(
            articulaciones=_tiro(_TIJERA), sostenido=True, duracion=2.2,
            descripcion="tira tijera"),
        # --- como reacciona al resultado ---
        "festejo": Gesto(
            articulaciones=_BAILE,
            vibra={M_L_SHOULDER_P: 0.55, M_R_SHOULDER_P: 0.55,
                   M_L_ELBOW: 0.35, M_R_ELBOW: 0.35,
                   M_CINTURA_Y: 0.30},
            desfase={M_R_SHOULDER_P: math.pi, M_R_ELBOW: math.pi,
                     M_CINTURA_Y: math.pi / 2},
            ciclos=3.0, sostenido=True, duracion=3.0,
            descripcion="festeja con un bailecito"),
        "lamento": Gesto(
            articulaciones=_LAMENTO,
            # Un "no, no puede ser" lento con la cintura.
            vibra={M_CINTURA_Y: 0.13}, ciclos=1.5,
            altura=-0.084,             # lo que suben los pies al doblar rodillas
            sostenido=True, duracion=3.0,
            descripcion="se agarra la cabeza"),
    },
)

# --- Go2: cuadrupedo de 12 grados de libertad ---------------------------
GO2_FL_T, GO2_FL_C = 1, 2
GO2_FR_T, GO2_FR_C = 4, 5
GO2_RL_T, GO2_RL_C = 7, 8
GO2_RR_T, GO2_RR_C = 10, 11

# Pose de perro parado. Sin esto el modelo aparece con las patas estiradas.
_GO2_MUSLO, _GO2_PANTORRILLA = 0.80, -1.55

# Pata delantera izquierda levantada. Igual que en el G1, se comparte entre el
# campo `saludo` y el gesto.
_GO2_SALUDO = {GO2_FL_T: -0.6, GO2_FL_C: -0.9}

GO2 = Robot(
    clave="go2",
    nombre="Unitree Go2",
    tipo="cuadrupedo",
    # La escena oficial del Go2 trae una escalera y vigas que cruzan la grilla.
    # Usamos una escena limpia que se genera sola. La del G1 ya viene limpia.
    escena="go2/scene_uade.xml",
    incluye="go2.xml",
    altura=0.33,
    pose_de_pie={
        GO2_FL_T: _GO2_MUSLO, GO2_FR_T: _GO2_MUSLO,
        GO2_RL_T: _GO2_MUSLO, GO2_RR_T: _GO2_MUSLO,
        GO2_FL_C: _GO2_PANTORRILLA, GO2_FR_C: _GO2_PANTORRILLA,
        GO2_RL_C: _GO2_PANTORRILLA, GO2_RR_C: _GO2_PANTORRILLA,
    },
    # Trote: las diagonales van juntas (FL con RR, FR con RL).
    marcha=[
        (GO2_FL_T, 0.28, 0.0), (GO2_RR_T, 0.28, 0.0),
        (GO2_FR_T, 0.28, math.pi), (GO2_RL_T, 0.28, math.pi),
        (GO2_FL_C, 0.22, 0.0), (GO2_RR_C, 0.22, 0.0),
        (GO2_FR_C, 0.22, math.pi), (GO2_RL_C, 0.22, math.pi),
    ],
    # El perro "saluda" levantando la pata delantera izquierda.
    saludo=_GO2_SALUDO,
    pose_sentado={GO2_FL_T: 1.3, GO2_FR_T: 1.3, GO2_RL_T: 1.3, GO2_RR_T: 1.3,
                  GO2_FL_C: -2.4, GO2_FR_C: -2.4, GO2_RL_C: -2.4, GO2_RR_C: -2.4},
    gestos={
        "saludo": Gesto(
            articulaciones=_GO2_SALUDO, vibra={GO2_FL_C: 0.3}, duracion=2.2,
            descripcion="saluda con la pata"),
        "patada": Gesto(
            articulaciones={GO2_FR_T: -0.9, GO2_FR_C: -0.3},
            duracion=1.0,
            descripcion="patea con la pata delantera derecha"),
        "salto": Gesto(
            articulaciones={GO2_FL_T: 1.4, GO2_FR_T: 1.4,
                            GO2_RL_T: 1.4, GO2_RR_T: 1.4,
                            GO2_FL_C: -2.4, GO2_FR_C: -2.4,
                            GO2_RL_C: -2.4, GO2_RR_C: -2.4},
            # Salta menos que el G1: mide 0.33 m contra 0.79 m.
            altura=0.18, duracion=0.9,
            descripcion="salta"),
        # Sin "dar_la_mano" ni "agarre": el perro no tiene manos. La tecla lo
        # dice en vez de mover algo que no existe.
    },
)

# `servicio_sport_go2.py` deja la accion como "saludando" y el socket como
# "saludo". Es el mismo gesto: se apunta el alias al mismo objeto en vez de
# copiar los angulos, que es lo que se desincroniza despues.
for _robot in (G1, G1_MANO, GO2):
    _robot.gestos["saludando"] = _robot.gestos["saludo"]

# Largo x ancho aproximados de pie, en metros. Medidos sobre el modelo oficial.
# Sirven para avisar cuando el robot no entra en la celda de la grilla del TP03.
HUELLA = {"g1": (0.32, 0.32), "g1_mano": (0.32, 0.32), "go2": (0.62, 0.28)}

ROBOTS = {"g1": G1, "g1_mano": G1_MANO, "go2": GO2}


def entra_en_celda(clave: str, tamano_celda: float) -> tuple[bool, float]:
    """Devuelve si el robot entra en una celda y cuanto mide su lado mayor."""
    largo, ancho = HUELLA.get(clave, (0.4, 0.4))
    mayor = max(largo, ancho)
    return mayor <= tamano_celda, mayor


def obtener(clave: str) -> Robot:
    c = clave.lower().strip()
    if c not in ROBOTS:
        raise ValueError(f"Robot desconocido: '{clave}'. Validos: g1, g1_mano, go2.")
    return ROBOTS[c]


def faltan_modelos() -> str:
    """Mensaje de ayuda si no encuentra los modelos oficiales."""
    return (
        "No encuentro los modelos oficiales de Unitree.\n\n"
        "Se descargan una sola vez con:\n"
        "    git clone https://github.com/unitreerobotics/unitree_mujoco\n\n"
        "Dejalos en alguna de estas carpetas:\n"
        + "\n".join(f"    {u}" for u in UBICACIONES)
    )
