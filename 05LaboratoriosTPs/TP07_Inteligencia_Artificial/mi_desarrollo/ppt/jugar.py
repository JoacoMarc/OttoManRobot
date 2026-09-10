"""Piedra, papel o tijera contra el G1.

    1. Le decis "arrancar" (o apretas la barra espaciadora)
    2. El robot ELIGE SU JUGADA Y LA SELLA, antes de mirarte la mano
    3. Canta la cuenta PALABRA POR PALABRA -- "piedra", "papel", "tijera" --
       y con cada palabra da un golpe con el brazo
    4. En el "ya" tira, y la camara mira que hiciste vos
    5. Canta el resultado, revela el sello, y vuelve a esperar

Antes de correr esto, abri el simulador en otra terminal:

    cd ../../entorno && python -m sim --robot g1_mano --materia tp07

Todo pasa en UN SOLO HILO, menos el microfono. El que marca el pulso es
`camara.read()`, que se toma sus ~33 ms esperando el proximo cuadro: ese es el
reloj. Nada mas bloquea -- ni el pedido al robot, que es un ida y vuelta por
loopback, ni la voz, que es un proceso aparte. Un hilo para la camara ademas
seria contraproducente: en macOS `cv2.imshow` tiene que correr en el hilo
principal.

LA CUENTA LA MANEJA LA VOZ, NO UN RELOJ. Cada palabra dispara su golpe y el
juego espera a que el `say` TERMINE para pasar a la siguiente. Antes habia un
solo "piedra papel o tijera" de 2.4 s con tres golpes encima, y la unica forma
de que coincidieran era adivinar cuanto tarda cada voz en cada maquina.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import cv2

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))     # para `from robot import Robot`

import arbitro                                                # noqa: E402
import vision                                                 # noqa: E402
import voz as voz_mod                                         # noqa: E402

PARTIDAS = os.path.join(AQUI, "partidas.csv")

CUENTA = ("piedra", "papel", "tijera")
# Lo que dura el gesto "golpe". Aunque la voz termine antes, se espera esto:
# si no, con una voz rapida el brazo no llega a completar el movimiento.
GOLPE_S = 0.75
# Techo por si el `say` nunca termina (proceso colgado, sin audio): la cuenta
# no se puede quedar trabada esperando una voz que no vuelve.
BEAT_MAX_S = 2.5
TRAS_YA = 0.35        # cuanto se espera despues del "ya" para mirar la mano
CAPTURA_S = 0.90      # cuanto dura la ventana de captura (~27 cuadros)
# Cuando festeja o se lamenta, contado desde el "ya". Va DESPUES de que termine
# el gesto de la jugada (2.2 s): la envolvente vale 0 en las dos puntas, asi que
# un gesto que termina y otro que empieza empalman solos. Cortar uno sostenido
# por la mitad, en cambio, da un salto de imagen.
REACCION_EN = 2.30
MOSTRAR_S = 4.2       # cuanto queda el resultado en pantalla

# Solo lo que hace falta. "salir" NO va: con una gramatica cerrada vosk empuja
# lo que oiga hacia la palabra mas parecida, y con el robot hablando cerca del
# microfono el juego se cerraba solo. Para salir esta ESC.
PALABRAS = ("arrancar", "de nuevo")

ESPERANDO, CONTANDO, CAPTURANDO, RESULTADO = ("esperando", "contando",
                                              "capturando", "resultado")

COLOR = {arbitro.GANA_HUMANO: (80, 230, 80), arbitro.GANA_ROBOT: (80, 80, 240),
         arbitro.EMPATE: (0, 210, 240), "nula": (150, 150, 150)}


class Juego:
    def __init__(self, robot, voz, oido, verboso=True):
        self.robot, self.voz, self.oido = robot, voz, oido
        self.verboso = verboso
        self.marcador = arbitro.Marcador()
        self.fase = ESPERANDO
        self.comp = None
        self.beat = 0
        self.t_beat = 0.0
        self.t_ya = 0.0
        self.t_resultado = 0.0
        self.votos = []
        self.humano = None
        self.resultado = None
        self.motivo = ""
        self.reaccion = None      # gesto pendiente para cuando termine el tiro

    # ---------- el robot ----------
    def _pedir(self, que, *args):
        if self.robot is None:
            return
        try:
            getattr(self.robot, que)(*args, esperar=False)
        except Exception as exc:                              # noqa: BLE001
            print(f"  [ROBOT] no pude '{que}': {exc}")

    def _decir(self, texto: str) -> None:
        """Habla, y tapa el microfono mientras dure.

        Sin esto el robot se escucha a si mismo: decia "deci arrancar" y el
        juego arrancaba solo.
        """
        self.voz.decir(texto)
        if self.oido is not None:
            self.oido.callar(1.2)

    # ---------- una ronda ----------
    def arrancar(self) -> None:
        # ---- EL COMPROMISO ----
        # Aca, y solo aca, el robot elige. Pasa ANTES de que exista un solo
        # cuadro de la ventana de captura: no puede haber visto tu mano. El
        # sello se publica ahora y la jugada se revela al final, para que
        # cualquiera pueda comprobar que no cambio en el medio.
        self.comp = arbitro.Compromiso.nuevo()
        self.votos, self.humano, self.resultado, self.motivo = [], None, None, ""
        self.reaccion = None
        self.fase = CONTANDO
        self.beat = -1
        print(f"\n  [COMPROMISO] el robot ya eligio. sello={self.comp.sello[:16]}")
        self._siguiente_beat()

    def _siguiente_beat(self) -> None:
        """Canta la palabra que toca y da su golpe. Al terminar las tres, tira."""
        self.beat += 1
        if self.beat >= len(CUENTA):
            self._tirar()
            return
        self.t_beat = time.monotonic()
        self._decir(CUENTA[self.beat])
        self._pedir("golpear")

    def _tirar(self) -> None:
        self.fase = CAPTURANDO
        self.t_ya = time.monotonic()
        self._decir("ya")
        self._pedir("tirar", self.comp.jugada)

    def paso(self, jugada_vista) -> None:
        """Una vuelta del bucle. `jugada_vista` es lo que ve la camara ahora."""
        ahora = time.monotonic()

        if self.fase == CONTANDO:
            transcurrido = ahora - self.t_beat
            listo = (not self.voz.hablando()) and transcurrido >= GOLPE_S
            if listo or transcurrido > BEAT_MAX_S:
                self._siguiente_beat()

        elif self.fase == CAPTURANDO:
            t = ahora - self.t_ya
            if TRAS_YA <= t <= TRAS_YA + CAPTURA_S:
                self.votos.append(jugada_vista)
            elif t > TRAS_YA + CAPTURA_S:
                self._cerrar_ronda()

        elif self.fase == RESULTADO:
            # Festeja o se lamenta, una vez que el brazo termino de tirar.
            if self.reaccion and ahora - self.t_ya >= REACCION_EN:
                self._pedir(self.reaccion)
                self.reaccion = None

            # No se vuelve a esperar hasta que el robot termine de cantar el
            # resultado: si no, la ronda siguiente le pisa la frase.
            if (ahora - self.t_resultado > MOSTRAR_S
                    and not self.voz.hablando()):
                self.fase = ESPERANDO
                if self.oido is not None:
                    self.oido.limpiar()
                print('  [LISTO] deci "arrancar" para otra ronda '
                      "(o barra espaciadora).")

    def _cerrar_ronda(self) -> None:
        self.fase = RESULTADO
        self.t_resultado = time.monotonic()
        self.humano, self.motivo = arbitro.votar(self.votos)
        validos = sum(1 for v in self.votos if v)

        if self.humano is None:
            self.marcador.nulas += 1
            self._decir(f"{self.motivo}. Probemos otra vez.")
            print(f"  [RONDA NULA] {self.motivo} "
                  f"({validos}/{len(self.votos)} cuadros con mano)")
            return

        self.resultado = arbitro.resolver(self.comp.jugada, self.humano)
        self.marcador.anotar(self.resultado)
        self.marcador.registrar(self.comp, self.humano, self.resultado, validos)

        frase = {arbitro.EMPATE: "Empate.",
                 arbitro.GANA_ROBOT: "Gano yo.",
                 arbitro.GANA_HUMANO: "Ganaste vos."}[self.resultado]
        self._decir(f"Yo saque {self.comp.jugada}, vos {self.humano}. {frase}")
        # El gesto no se dispara ahora sino en `paso`, cuando el brazo termine
        # de tirar. En el empate no hace nada: no hay nada que festejar.
        self.reaccion = {arbitro.GANA_ROBOT: "festejar",
                         arbitro.GANA_HUMANO: "lamentarse"}.get(self.resultado)
        print(f"  [REVELA]  jugada={self.comp.jugada}  sal={self.comp.sal}")
        print(f"            sha256('{self.comp.jugada}|{self.comp.sal}') "
              f"empieza con {self.comp.sello[:16]}  "
              f"-> {'verifica' if self.comp.verifica() else 'NO VERIFICA'}")
        print(f"  [MARCADOR] {self.marcador}")


def dibujar_hud(cuadro, juego, jugada_vista, oido_ok,
                camara_idx: int = 0) -> None:
    alto, ancho = cuadro.shape[:2]
    cv2.rectangle(cuadro, (0, 0), (ancho, 88), (24, 24, 28), -1)
    cv2.rectangle(cuadro, (0, alto - 40), (ancho, alto), (24, 24, 28), -1)

    m = juego.marcador
    cv2.putText(cuadro, f"ROBOT {m.robot}  -  VOS {m.humano}", (16, 34),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (255, 255, 255), 2)
    cv2.putText(cuadro, f"empates {m.empates}   nulas {m.nulas}", (16, 66),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (170, 170, 170), 1)

    if juego.fase == ESPERANDO:
        pedido = 'deci "ARRANCAR"' if oido_ok else "apreta ESPACIO"
        cv2.putText(cuadro, pedido, (ancho - 330, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 230, 230), 2)
    elif juego.fase == CONTANDO:
        # Una bolita por palabra cantada, y la palabra en curso escrita.
        for i in range(3):
            cv2.circle(cuadro, (ancho - 230 + i * 60, 44), 20,
                       (0, 230, 230) if i <= juego.beat else (70, 70, 70), -1)
        if 0 <= juego.beat < len(CUENTA):
            cv2.putText(cuadro, CUENTA[juego.beat].upper(), (ancho - 330, 78),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 230), 1)
    elif juego.fase == CAPTURANDO:
        cv2.putText(cuadro, "YA!", (ancho - 180, 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 230, 230), 4)
    elif juego.fase == RESULTADO:
        if juego.humano is None:
            texto, color = "RONDA NULA", COLOR["nula"]
        else:
            texto = {arbitro.EMPATE: "EMPATE",
                     arbitro.GANA_ROBOT: "GANO EL ROBOT",
                     arbitro.GANA_HUMANO: "GANASTE VOS"}[juego.resultado]
            color = COLOR[juego.resultado]
        cv2.putText(cuadro, texto, (16, alto - 90),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, color, 3)
        if juego.humano is not None:
            cv2.putText(cuadro,
                        f"robot: {juego.comp.jugada}    vos: {juego.humano}",
                        (16, alto - 55), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (230, 230, 230), 2)
        else:
            cv2.putText(cuadro, juego.motivo, (16, alto - 55),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)

    abajo = f"veo: {jugada_vista or '-'}"
    if juego.comp is not None and juego.fase != ESPERANDO:
        abajo += f"     sello {juego.comp.sello[:16]}"
    cv2.putText(cuadro, abajo, (16, alto - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (190, 190, 190), 1)
    cv2.putText(cuadro, f"camara {camara_idx}  TAB cambia   ESC salir",
                (ancho - 330, alto - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (140, 140, 140), 1)


def main() -> None:
    ap = argparse.ArgumentParser(description="Piedra, papel o tijera con el G1")
    ap.add_argument("--sin-robot", action="store_true",
                    help="solo camara y voz, sin abrir el simulador")
    ap.add_argument("--sin-voz", action="store_true",
                    help="no hablar ni escuchar; se juega con la barra")
    ap.add_argument("--camara", type=int, default=0)
    args = ap.parse_args()

    robot = None
    if not args.sin_robot:
        from robot import Robot
        robot = Robot()
        robot.conectar()

    voz = voz_mod.Voz(callado=args.sin_voz)
    oido = None if args.sin_voz else voz_mod.Oido(PALABRAS)
    oido_ok = oido is not None and oido.encendido

    indice = args.camara
    camara = vision.abrir_camara(indice)
    if camara is None:
        raise SystemExit(vision.texto_sin_camara(indice))

    juego = Juego(robot, voz, oido)
    print()
    print("  " + "-" * 58)
    print("   PIEDRA, PAPEL O TIJERA")
    print("  " + "-" * 58)
    if oido_ok:
        print('   Deci "ARRANCAR" para jugar una ronda.')
        print("   Tambien anda la barra espaciadora.")
    else:
        print("   Apreta ESPACIO para jugar una ronda.")
    print("   Se juega una ronda atras de otra. ESC para salir.")
    print(f"   Camara {indice}. TAB cambia de camara, o apreta su numero.")
    print("  " + "-" * 58)
    # El saludo NO se dice en voz alta: el microfono lo escucharia y el juego
    # arrancaria solo antes de que llegues a poner la mano.

    milis = 0
    try:
        with vision.Ojo() as ojo:
            while True:
                hay, cuadro = camara.read()          # ~33 ms: el reloj del juego
                if not hay:
                    break
                milis += 33
                rgb = cv2.cvtColor(cuadro, cv2.COLOR_BGR2RGB)
                jugada_vista, puntos = ojo.leer(rgb, milis)

                tecla = cv2.waitKey(1) & 0xFF
                if tecla == 27:                      # ESC: la unica salida
                    break

                # TAB pasa a la siguiente camara que ande; los numeros van
                # directo a una. Cambiar corta la ronda en curso: los cuadros
                # de dos camaras distintas no se pueden votar juntos.
                nuevo_indice = None
                if tecla == 9:                       # TAB
                    camara, nuevo_indice = vision.cambiar_camara(camara, indice)
                elif 48 <= tecla <= 57:              # 0-9
                    pedido = tecla - 48
                    if pedido != indice:
                        camara.release()
                        otra = vision.abrir_camara(pedido)
                        if otra is not None:
                            camara, nuevo_indice = otra, pedido
                        else:
                            print(f"  [CAMARA] la {pedido} no responde")
                            camara = vision.abrir_camara(indice)
                if nuevo_indice is not None:
                    if camara is None:
                        raise SystemExit(vision.texto_sin_camara(nuevo_indice))
                    if nuevo_indice == indice:
                        # `cambiar_camara` vuelve a la misma cuando no encontro
                        # ninguna otra. No cambio nada: no hay que avisar ni
                        # cortar la ronda.
                        print("  [CAMARA] no encontre otra camara")
                    else:
                        indice = nuevo_indice
                        print(f"  [CAMARA] ahora la {indice}")
                        if juego.fase != ESPERANDO:
                            juego.fase = ESPERANDO
                            print("  [CAMARA] ronda cancelada por el cambio")
                    continue

                # El microfono se ignora mientras el robot habla. Solo se hace
                # caso entre rondas: durante la cuenta no hay nada que decir.
                if voz.hablando() and oido is not None:
                    oido.callar(0.8)
                oida = oido.escuchar() if oido_ok else None
                if juego.fase == ESPERANDO and (
                        tecla == 32 or oida in ("arrancar", "de nuevo")):
                    juego.arrancar()

                juego.paso(jugada_vista)

                cuadro = cv2.flip(cuadro, 1)     # espejo, para que se vea normal
                if puntos is not None:
                    espejo = [type("P", (), {"x": 1.0 - p.x, "y": p.y})()
                              for p in puntos]
                    vision.dibujar(cuadro, espejo)
                dibujar_hud(cuadro, juego, jugada_vista, oido_ok, indice)
                cv2.imshow("piedra, papel o tijera", cuadro)
    except KeyboardInterrupt:
        pass
    finally:
        camara.release()
        cv2.destroyAllWindows()
        if oido is not None:
            oido.cerrar()
        voz.cerrar()
        juego.marcador.guardar(PARTIDAS)
        print(f"\n  Marcador final: {juego.marcador}")
        if juego.marcador.filas:
            print(f"  Partidas guardadas en {PARTIDAS}")
        if robot is not None:
            robot.desconectar()


if __name__ == "__main__":
    main()
