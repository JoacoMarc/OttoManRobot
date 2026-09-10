"""Manejar el robot a mano desde la ventana 3D: flechas para moverlo y letras
para los gestos.

Por que las teclas QUEDAN puestas en vez de mantenerlas apretadas
-----------------------------------------------------------------
MuJoCo avisa de cada tecla UNA sola vez. El visor le pasa nuestro callback al
adaptador de GLFW, y ese solo lo llama cuando `act == GLFW_PRESS`
(`GlfwAdapter::IsKeyDownEvent`): el autorepeat del sistema (GLFW_REPEAT) y el
soltar la tecla (GLFW_RELEASE) no llegan NUNCA. Con eso no se puede hacer un
"mantene apretado para avanzar": no hay forma de saber que la tecla sigue
abajo, ni cuando se solto.

Asi que el movimiento es un mando con memoria: una flecha PRENDE ese movimiento
y la misma flecha lo APAGA. La barra espaciadora apaga todo. Se maneja a
golpecitos y el robot sigue andando solo.

La orden se refresca en cada vuelta del bucle del simulador y VENCE en
REFRESCO_S segundos, igual que el Move() del robot real: si el simulador se
cierra o se cuelga, el robot frena solo en vez de quedar caminando para siempre.

Por que el movimiento va en las flechas y no en WASD
----------------------------------------------------
Porque el visor procesa la tecla ANTES de pasarnosla, y LAS 26 LETRAS son
atajos suyos de dibujo: `mjVISSTRING` y `mjRNDSTRING` traen un atajo por flag.
Con WASD, la D apagaba los cuerpos estaticos -- el piso es uno, y por eso
"cambiaba el fondo" al manejar --, la W ponia el robot en alambre y la S sacaba
las sombras.

Las flechas y la barra espaciadora no tocan ningun flag, y sus casos en
`simulate.cc` estan guardados por `!is_passive_`, asi que en el visor pasivo
que usamos no hacen absolutamente nada. Son las unicas teclas realmente libres.

Para los gestos si hacen falta letras, y ahi se deshace el atajo a mano: ver
`enganchar()` y `_deshacer_atajo()`. No todas se pueden deshacer, y las que no,
no se usan.

Los gestos NO llegan al robot real
----------------------------------
Saltar, patear y agacharse son cosmeticos y viven enteros dentro del proceso
del simulador: el teclado le escribe derecho al `Mundo`, sin pasar por
`local.py::_orden_gesto`, que es donde se aplica la lista blanca. No estan en
`acciones.py::PERMITIDAS` ni en el cliente `robot.py`, y es a proposito: esa
lista es la misma que usa el laboratorio fisico y prohibe justamente esto
(`FrontJump`: "salto; impacto y perdida de equilibrio"; `Sit` y `StandDown`:
"cambia la postura"). El programa del alumno no puede pedirlos.
"""

from __future__ import annotations

# Codigos de tecla de GLFW. Llegan tal cual: `GlfwAdapter::TranslateKeyCode`
# es la identidad, asi que no hay que traducir nada.
ESPACIO = 32
C, D, E, H, I, J, M, P, Q = 67, 68, 69, 72, 73, 74, 77, 80, 81
# Piedra, papel o tijera. Las cuatro estan en mjVISSTRING (reversibles) y
# libres. Ojo: R y L, que serian los mnemonicos obvios, estan en mjRNDSTRING
# y no se pueden deshacer -- ver el encabezado.
O, A, V, Y = 79, 65, 86, 89
B, F = 66, 70          # festejo y lamento
FLECHA_DER, FLECHA_IZQ, FLECHA_ABAJO, FLECHA_ARRIBA = 262, 263, 264, 265

# Cada tecla de movimiento toca UN eje, con su signo. Los ejes son los del
# Move() del SDK: vx adelante, vy al costado, vyaw girando. Positivo = adelante,
# izquierda.
_MOVIMIENTO: dict[int, tuple[str, int]] = {
    FLECHA_ARRIBA: ("vx", +1),
    FLECHA_ABAJO: ("vx", -1),
    FLECHA_IZQ: ("vyaw", +1),
    FLECHA_DER: ("vyaw", -1),
    Q: ("vy", +1),
    E: ("vy", -1),
}

# Tecla -> nombre del gesto en `robot.gestos`. El nombre es el que queda en
# `mundo.accion`, que es lo que el simulador busca para dibujarlo.
_GESTOS: dict[int, str] = {
    H: "saludo",
    D: "dar_la_mano",
    P: "patada",
    J: "salto",
    M: "agarre",
    O: "piedra",      # O de puno cerrado
    A: "papel",       # A de mano abierta
    V: "tijera",      # V de los dos dedos
    Y: "preparar",    # Y de "ya": la cuenta antes de tirar
    B: "festejo",     # B de baile
    F: "lamento",     # F de fracaso
}

AGACHARSE = C
INICIO = I

TECLAS_USADAS = (frozenset(_MOVIMIENTO) | frozenset(_GESTOS)
                 | {ESPACIO, AGACHARSE, INICIO})

# Cuanto vale una orden del teclado antes de vencer. Es holgado respecto del
# bucle del visor (20 ms) para que no se note el refresco, y corto para que el
# robot frene enseguida si el simulador deja de refrescar.
REFRESCO_S = 0.4

AYUDA = """  ------------------------------------------------------------
   MANEJALO VOS: hace clic en la ventana 3D y usa el teclado
  ------------------------------------------------------------
     flechas arriba / abajo      adelante / atras
     flechas izquierda / derecha girar
     Q  /  E                     paso lateral izquierda / derecha
     barra espaciadora           frenar todo

     H   saludar                 P   patear
     D   dar la mano             J   saltar
     M   agarrar                 C   agacharse (otra vez se para)
     I   volver al inicio

     Solo el G1 con manos (--robot g1_mano):
     O   piedra    A   papel    V   tijera    Y   la cuenta
     B   festeja   F   se lamenta

   No hace falta mantener la tecla apretada: la prendes y el robot
   sigue. La MISMA flecha apaga ese movimiento, y se pueden combinar
   (arriba y despues izquierda para hacer una curva).

   Mientras no toques una tecla, el teclado no molesta a tu programa.
  ------------------------------------------------------------"""


def _atajos_del_visor():
    """Que le hace cada tecla al dibujo del visor, sacado de MuJoCo.

    Se DERIVA de las tablas de MuJoCo en vez de escribirla a mano para que no
    se desactualice: si una version cambia un atajo, esto cambia con ella.

        reversibles     tecla -> indice en `opt.flags` (los mjVIS_*). El
                        mjvOption lo comparte el visor con Python, asi que se
                        puede volver a poner como estaba.
        irreversibles   tecla -> nombre del flag (los mjRND_*). Viven en el
                        mjvScene de C++, que `launch_passive` no expone: si
                        usaramos una de estas teclas, el cambio quedaria y no
                        habria forma de deshacerlo desde aca.
    """
    import mujoco

    reversibles = {}
    for indice, fila in enumerate(mujoco.mjVISSTRING):
        if fila[2]:
            reversibles[ord(fila[2])] = indice
    irreversibles = {}
    for fila in mujoco.mjRNDSTRING:
        if fila[2]:
            irreversibles[ord(fila[2])] = fila[0]
    return reversibles, irreversibles


class Teleoperador:
    """Traduce teclas a velocidades y gestos, respetando el perfil de la materia.

    Nunca inventa un tope: pide las velocidades maximas al perfil con el que el
    profesor abrio el simulador. En un TP con techo de 0.2 m/s, la flecha de
    adelante avanza a 0.2 m/s y no hay tecla que suba de ahi.
    """

    def __init__(self, mundo, robot, verboso: bool = True):
        self.mundo = mundo
        self.robot = robot
        self.verboso = verboso
        self._ejes = {"vx": 0, "vy": 0, "vyaw": 0}
        self._activo = False
        self._visor = None
        self._deshacer: dict[int, int] = {}

    # ---------- enganche con la ventana ----------
    def enganchar(self, visor) -> None:
        """Guarda el visor para poder deshacer sus atajos. Ver el encabezado."""
        self._visor = visor
        reversibles, irreversibles = _atajos_del_visor()
        self._deshacer = {t: reversibles[t] for t in TECLAS_USADAS
                          if t in reversibles}

        # Guarda: si alguna tecla nuestra pisa un flag que no podemos devolver,
        # se dice ACA. Si no, aparece como un robot en alambre o un piso que
        # desaparece a mitad de una clase, y no hay con que atarlo a una tecla.
        choques = sorted(f"{chr(t)} ({irreversibles[t]})"
                         for t in TECLAS_USADAS if t in irreversibles)
        if choques and self.verboso:
            print("  [TECLADO] OJO: estas teclas cambian el dibujo del visor y")
            print("            no se puede deshacer: " + ", ".join(choques))

    def _deshacer_atajo(self, codigo: int) -> None:
        """Devuelve el flag que el visor acaba de togglear con nuestra tecla.

        El visor atiende la tecla antes que nosotros, asi que cuando llegamos
        el flag ya cambio: alcanza con volver a darlo vuelta.
        """
        indice = self._deshacer.get(codigo)
        if indice is None or self._visor is None:
            return
        flags = self._visor.opt.flags
        flags[indice] = not flags[indice]

    # ---------- lo llama el visor, desde el hilo de la ventana ----------
    def tecla(self, codigo: int) -> None:
        if codigo not in TECLAS_USADAS:
            return              # es una tecla del visor, no nuestra

        if codigo == ESPACIO:
            if any(self._ejes.values()):
                self._ejes = dict.fromkeys(self._ejes, 0)
                self._anunciar()
        elif codigo in _MOVIMIENTO:
            self._mover(codigo)
        elif codigo in _GESTOS:
            self._gesto(_GESTOS[codigo])
        elif codigo == AGACHARSE:
            self._agacharse()
        elif codigo == INICIO:
            self._volver_al_inicio()

        self._deshacer_atajo(codigo)

    # ---------- lo llama el bucle del simulador, en cada vuelta ----------
    def refrescar(self) -> None:
        """Sostiene la orden del teclado. INERTE si no hay ninguna tecla puesta.

        Que sea inerte importa: el programa del alumno y el teclado escriben la
        misma velocidad, y si esto refrescara ceros todo el tiempo el robot no
        se moveria nunca desde el codigo. Mientras no toques una tecla, el
        teclado no existe; con la barra espaciadora le devolves el mando al
        programa.
        """
        vx, vy, vyaw = self._velocidades()
        if vx or vy or vyaw:
            self._activo = True
            self.mundo.set_velocidad(vx, vy, vyaw, REFRESCO_S)
        elif self._activo:
            # Una sola vez, al apagar la ultima tecla: frena y se hace a un lado.
            self._activo = False
            self.mundo.detener()

    # ---------- ordenes ----------
    def _mover(self, codigo: int) -> None:
        eje, signo = _MOVIMIENTO[codigo]
        # La misma tecla otra vez apaga el eje. Es la unica forma de "soltar"
        # cuando GLFW no nos avisa que se solto la tecla.
        self._ejes[eje] = 0 if self._ejes[eje] == signo else signo

        # Agachado, `set_velocidad` descarta el movimiento y solo deja un aviso
        # en la consola del simulador: se veria como un teclado que no responde.
        if any(self._ejes.values()) and not self.mundo.de_pie:
            self.mundo.set_de_pie(True)
            if self.verboso:
                print("  [TECLADO] se para para poder moverse")
        self._anunciar()

    def _gesto(self, nombre: str) -> None:
        gesto = self.robot.gestos.get(nombre)
        if gesto is None:
            if self.verboso:
                print(f"  [TECLADO] el {self.robot.nombre} no sabe "
                      f"'{nombre}' (no tiene con que)")
            return

        # Un gesto para al robot -- lo hace `mundo.gesto()` --, asi que hay que
        # soltar las teclas de movimiento tambien: si no, el refresco de la
        # vuelta siguiente lo pone a caminar de nuevo y se come el gesto.
        self._ejes = dict.fromkeys(self._ejes, 0)
        self._activo = False
        if not self.mundo.de_pie:
            self.mundo.set_de_pie(True)
        self.mundo.gesto(nombre, gesto.duracion)
        if self.verboso:
            print(f"  [TECLADO] {gesto.descripcion}")

    def _agacharse(self) -> None:
        self._ejes = dict.fromkeys(self._ejes, 0)
        self._activo = False
        de_pie = not self.mundo.de_pie
        self.mundo.set_de_pie(de_pie)
        if self.verboso:
            print("  [TECLADO] " + ("se para" if de_pie else "se agacha"))

    def _volver_al_inicio(self) -> None:
        self._ejes = dict.fromkeys(self._ejes, 0)
        self._activo = False
        self.mundo.reiniciar()
        if self.verboso:
            print("  [TECLADO] vuelve al inicio")

    # ---------- interno ----------
    def _velocidades(self) -> tuple[float, float, float]:
        p = self.mundo.perfil
        return (self._ejes["vx"] * p.velocidad_max,
                self._ejes["vy"] * p.velocidad_max,
                self._ejes["vyaw"] * p.velocidad_angular_max)

    def _anunciar(self) -> None:
        """Avisa por consola en que quedo el mando.

        La ventana 3D no tiene donde mostrarlo, y sin esto no hay manera de
        saber que movimientos quedaron prendidos: el robot se mueve y no sabes
        por que tecla.
        """
        if not self.verboso:
            return
        vx, vy, vyaw = self._velocidades()
        if not (vx or vy or vyaw):
            print("  [TECLADO] frenado")
        else:
            print(f"  [TECLADO] adelante {vx:+.2f} m/s | "
                  f"lateral {vy:+.2f} m/s | giro {vyaw:+.2f} rad/s")
