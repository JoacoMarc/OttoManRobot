"""Que jugada esta haciendo la mano que ve la webcam.

Usa MediaPipe Hands, que da 21 puntos por mano. La regla para decidir si un
dedo esta estirado NO mira las coordenadas de pantalla ("la punta esta mas
arriba que el nudillo"), que es lo que sale en todos los tutoriales: eso falla
apenas girás la mano o la ponés de costado. Mira dos cosas internas a la mano,
que no dependen de como este orientada ni de si es la izquierda o la derecha:

    1. la punta esta MAS LEJOS DE LA MUNECA que el nudillo del medio
    2. el dedo esta DERECHO: el angulo en el nudillo medio es chico

Todo se normaliza por el largo de la palma, asi que tampoco importa a que
distancia de la camara estes.

Ojo con la version de mediapipe: desde la 1.0 ya no existe `mp.solutions.hands`
(la API vieja). Esto usa la nueva (Tasks), que necesita el archivo
`modelos/hand_landmarker.task` bajado al lado.
"""

from __future__ import annotations

import math
import os

import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELO = os.path.join(AQUI, "modelos", "hand_landmarker.task")

MUNECA, MEDIO_MCP = 0, 9
# nombre -> (nudillo, nudillo medio, punta)
LARGOS = {
    "indice": (5, 6, 8),
    "medio": (9, 10, 12),
    "anular": (13, 14, 16),
    "menique": (17, 18, 20),
}
PULGAR_PUNTA, PULGAR_IP, MENIQUE_MCP = 4, 3, 17

# Cuanto mas lejos que el nudillo medio tiene que estar la punta, en fraccion
# del largo de la palma. Sube si te cuenta dedos doblados como estirados.
MARGEN = 0.10
# Cuanto se puede doblar un dedo y seguir contando como estirado, en grados.
TOLERANCIA_GRADOS = 45.0

CONEXIONES = [(0, 1), (0, 5), (5, 9), (9, 13), (13, 17), (0, 17),
              (1, 2), (2, 3), (3, 4), (5, 6), (6, 7), (7, 8),
              (9, 10), (10, 11), (11, 12), (13, 14), (14, 15), (15, 16),
              (17, 18), (18, 19), (19, 20)]


def _dist(a, b) -> float:
    """Distancia en el plano de la imagen.

    Sin la z a proposito: la z de MediaPipe es relativa y bastante ruidosa, y
    para saber si un dedo esta estirado no hace falta.
    """
    return math.hypot(a.x - b.x, a.y - b.y)


def _angulo(a, b, c) -> float:
    """Angulo en `b`, en grados. 180 = los tres puntos alineados."""
    v1 = (a.x - b.x, a.y - b.y)
    v2 = (c.x - b.x, c.y - b.y)
    n1 = math.hypot(*v1) or 1e-9
    n2 = math.hypot(*v2) or 1e-9
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cos))


def dedos_estirados(puntos) -> dict:
    """Que dedos estan estirados. Devuelve nombre -> True/False."""
    palma = _dist(puntos[MUNECA], puntos[MEDIO_MCP]) or 1e-9
    fuera = {}
    for nombre, (mcp, pip, punta) in LARGOS.items():
        lejos = (_dist(puntos[punta], puntos[MUNECA])
                 > _dist(puntos[pip], puntos[MUNECA]) + MARGEN * palma)
        derecho = _angulo(puntos[mcp], puntos[pip],
                          puntos[punta]) > 180.0 - TOLERANCIA_GRADOS
        fuera[nombre] = bool(lejos and derecho)
    # El pulgar dobla en otro eje: se lo mide por cuanto se aleja del nudillo
    # del menique. No decide ninguna jugada, es solo para mostrar en pantalla.
    fuera["pulgar"] = bool(
        _dist(puntos[PULGAR_PUNTA], puntos[MENIQUE_MCP])
        > _dist(puntos[PULGAR_IP], puntos[MENIQUE_MCP]) + 0.05 * palma)
    return fuera


def jugada_de(puntos) -> str | None:
    """piedra, papel, tijera, o None si la mano no dice ninguna de las tres."""
    d = dedos_estirados(puntos)
    largos = [d["indice"], d["medio"], d["anular"], d["menique"]]
    n = sum(largos)
    # "n <= 1" y no "n == 0" a proposito: a un puno real el detector le escapa
    # un dedo de vez en cuando, y descartar esos cuadros es peor que aceptarlos
    # -- la ventana de votacion ya filtra el ruido. El costo es que APUNTAR con
    # un dedo se lee como piedra; en este juego nadie apunta.
    if n <= 1:
        return "piedra"
    if n == 4:
        return "papel"
    # Tijera exige EL PATRON, no "dos dedos": indice y medio, y ningun otro.
    # Con "n == 2" a secas, un menique con el indice contaria como tijera.
    if largos == [True, True, False, False]:
        return "tijera"
    return None



# ---------------------------------------------------------------------------
#  Elegir camara
# ---------------------------------------------------------------------------
# Cuantos indices se prueban al buscar la siguiente. Con la webcam de la
# notebook, un celular por Continuity y una USB ya se pasa de 3.
MAX_CAMARAS = 6


def abrir_camara(indice: int):
    """Abre una camara y COMPRUEBA que entregue un cuadro, o devuelve None.

    Que `isOpened()` diga True no alcanza: en macOS, sin permiso de camara,
    abre igual y despues devuelve cuadros negros o nada. La unica prueba que
    sirve es leer uno.
    """
    import cv2

    cam = cv2.VideoCapture(indice)
    if cam.isOpened():
        hay, _ = cam.read()
        if hay:
            return cam
    cam.release()
    return None


def cambiar_camara(cam, indice: int, maximo: int = MAX_CAMARAS):
    """Pasa a la siguiente camara que ande. Devuelve (captura, indice).

    Suelta la actual ANTES de probar la siguiente: muchas camaras no dejan
    que dos procesos -- ni dos capturas -- las abran a la vez, asi que
    probar sin soltar daria que no hay ninguna otra.

    Si ninguna otra anda, vuelve a la que estaba.
    """
    if cam is not None:
        cam.release()
    for salto in range(1, maximo + 1):
        i = (indice + salto) % maximo
        nueva = abrir_camara(i)
        if nueva is not None:
            return nueva, i
    return abrir_camara(indice), indice


def texto_sin_camara(indice: int = 0) -> str:
    return (f"No pude abrir la webcam {indice}.\n"
            "  En macOS hay que darle permiso de Camara a la aplicacion desde\n"
            "  la que corres esto (Terminal, iTerm, VS Code) en\n"
            "  Ajustes del Sistema > Privacidad y seguridad > Camara.\n"
            "  Despues de darselo hay que cerrarla y volver a abrirla.\n"
            "  Si tenes varias camaras, proba con --camara 1.")


class Ojo:
    """La webcam mirando una mano. Se usa como contexto (`with Ojo() as ojo`)."""

    def __init__(self, manos: int = 1):
        if not os.path.exists(MODELO):
            raise FileNotFoundError(
                f"Falta el modelo de manos en {MODELO}.\n"
                "  Se baja una sola vez con:\n"
                "    curl -L -o " + MODELO + " \\\n"
                "      https://storage.googleapis.com/mediapipe-models"
                "/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task")
        opciones = mp_vision.HandLandmarkerOptions(
            base_options=mp_tasks.BaseOptions(model_asset_path=MODELO),
            running_mode=mp_vision.RunningMode.VIDEO,
            num_hands=manos,
            min_hand_detection_confidence=0.6,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5)
        self._det = mp_vision.HandLandmarker.create_from_options(opciones)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    def leer(self, rgb, milisegundos: int):
        """Devuelve (jugada o None, puntos o None) para un cuadro RGB."""
        imagen = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        salida = self._det.detect_for_video(imagen, milisegundos)
        if not salida.hand_landmarks:
            return None, None
        puntos = salida.hand_landmarks[0]
        return jugada_de(puntos), puntos

    def cerrar(self) -> None:
        self._det.close()


def dibujar(cuadro, puntos) -> None:
    """Pinta la mano encima del cuadro (BGR, se modifica en el lugar)."""
    import cv2

    alto, ancho = cuadro.shape[:2]
    pix = [(int(p.x * ancho), int(p.y * alto)) for p in puntos]
    for a, b in CONEXIONES:
        cv2.line(cuadro, pix[a], pix[b], (0, 220, 120), 2)
    for x, y in pix:
        cv2.circle(cuadro, (x, y), 3, (255, 255, 255), -1)


def _demo() -> None:
    """Solo la vision, sin robot ni voz: mostra la mano y que jugada lee."""
    import cv2

    indice = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    camara = abrir_camara(indice)
    if camara is None:
        raise SystemExit(texto_sin_camara(indice))
    print("  TAB cambia de camara.  ESC sale.")
    with Ojo() as ojo:
        t = 0
        while True:
            hay, cuadro = camara.read()
            if not hay:
                break
            t += 33
            rgb = cv2.cvtColor(cuadro, cv2.COLOR_BGR2RGB)
            jugada, puntos = ojo.leer(rgb, t)
            cuadro = cv2.flip(cuadro, 1)      # espejo: solo para que se vea bien
            if puntos is not None:
                espejo = [type("P", (), {"x": 1.0 - p.x, "y": p.y})()
                          for p in puntos]
                dibujar(cuadro, espejo)
                texto = jugada or "no se"
                d = dedos_estirados(puntos)
                detalle = " ".join(k[:3] for k, v in d.items() if v) or "-"
            else:
                texto, detalle = "no veo la mano", ""
            cv2.putText(cuadro, texto.upper(), (16, 46),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 255, 255), 3)
            cv2.putText(cuadro, detalle, (16, 78),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
            cv2.putText(cuadro, f"camara {indice}  (TAB cambia)",
                        (16, cuadro.shape[0] - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (190, 190, 190), 1)
            cv2.imshow("vision - ESC para salir", cuadro)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla == 27:
                break
            if tecla == 9:                       # TAB
                camara, indice = cambiar_camara(camara, indice)
                if camara is None:
                    raise SystemExit(texto_sin_camara(indice))
                print(f"  camara {indice}")
    camara.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    _demo()
