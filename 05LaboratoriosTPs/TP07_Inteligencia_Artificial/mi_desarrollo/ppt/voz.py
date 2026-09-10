"""Hablar y escuchar. Las dos cosas detras de una interfaz chica, para poder
cambiarles el motor sin tocar el juego.

Escuchar (`Oido`) usa vosk con el modelo chico de espanol y una GRAMATICA
CERRADA: solo puede reconocer las tres o cuatro palabras que le pasamos. Con un
vocabulario asi de chico casi no se equivoca, anda sin internet y arranca en un
segundo. Un modelo grande de dictado seria peor para esto: mas lento, mas
pesado, y con muchas mas formas de escuchar cualquier cosa.

Hablar (`Voz`) usa lo que traiga el sistema. En macOS es `say`, que ya esta
instalado. Nunca bloquea: el juego se maneja por reloj, y si el audio falla
tiene que seguir jugando igual, callado.

Para el robot real, `VozRobot` habla por los parlantes del G1 con el
AudioClient del SDK. Misma interfaz, se cambia una linea en jugar.py.
"""

from __future__ import annotations

import json
import os
import platform
import queue
import subprocess
import threading
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELO_VOZ = os.path.join(AQUI, "modelos", "vosk-es")

# Voces de macOS que suenan a castellano, en orden de preferencia.
VOCES_MAC = ("Paulina", "Monica", "Mónica")


# --------------------------------------------------------------------------
#  Hablar
# --------------------------------------------------------------------------
class Voz:
    """Dice textos en voz alta. `decir()` vuelve enseguida, no espera."""

    def __init__(self, velocidad: int = 195, callado: bool = False):
        self.velocidad = velocidad
        self.callado = callado
        self._proceso = None
        self._voz = self._elegir_voz()
        self._precalentar()

    def _precalentar(self) -> None:
        """Dice algo mudo para que el sistema cargue la voz.

        La PRIMERA vez que se habla, macOS tiene que leer los datos de la voz
        del disco: ese `say` tarda el doble que los siguientes. Como la cuenta
        va al ritmo de la voz, eso hacia que el primer golpe de la primera
        ronda quedara colgado 2.5 s contra 1.2 s de los demas. Un `say " "` al
        arrancar deja todo cacheado y no se oye nada.
        """
        if self.callado:
            return
        orden = self._orden(" ")
        if orden is None:
            return
        try:
            subprocess.Popen(orden, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except Exception:                                     # noqa: BLE001
            pass

    def _elegir_voz(self) -> str:
        if platform.system() != "Darwin":
            return ""
        try:
            listado = subprocess.run(["say", "-v", "?"], capture_output=True,
                                     text=True, timeout=5).stdout
        except Exception:                                     # noqa: BLE001
            return ""
        for v in VOCES_MAC:
            if v in listado:
                return v
        return ""

    def decir(self, texto: str, esperar: bool = False) -> None:
        print(f"  [ROBOT] {texto}")
        if self.callado:
            return
        orden = self._orden(texto)
        if orden is None:
            return
        try:
            self._proceso = subprocess.Popen(
                orden, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:                                     # noqa: BLE001
            self._proceso = None    # sin voz el juego sigue igual, en silencio
            return
        if esperar:
            self.esperar()

    def _orden(self, texto: str):
        sistema = platform.system()
        if sistema == "Darwin":
            base = ["say", "-r", str(self.velocidad)]
            if self._voz:
                base += ["-v", self._voz]
            return base + [texto]
        if sistema == "Linux":
            for prog, args in (("spd-say", ["-w", "-l", "es"]),
                               ("espeak-ng", ["-v", "es"]),
                               ("espeak", ["-v", "es"])):
                if _hay(prog):
                    return [prog, *args, texto]
            return None
        if sistema == "Windows":
            return ["powershell", "-NoProfile", "-Command",
                    "Add-Type -AssemblyName System.Speech; "
                    "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                    f".Speak('{texto}')"]
        return None

    def hablando(self) -> bool:
        """Si todavia esta sonando. Con esto la cuenta se sincroniza con la
        voz de verdad, en vez de adivinar cuanto tarda cada palabra."""
        return self._proceso is not None and self._proceso.poll() is None

    def esperar(self) -> None:
        if self._proceso is not None:
            try:
                self._proceso.wait(timeout=20)
            except Exception:                                 # noqa: BLE001
                pass

    def cerrar(self) -> None:
        if self._proceso is not None and self._proceso.poll() is None:
            self._proceso.terminate()


class VozRobot(Voz):
    """Habla por los parlantes del G1 real.

    Precedente en el repo:
    03Go2/01Actividades/00Python/progra1/go2_taller_alumnos.py
    """

    def __init__(self, audio_client):
        super().__init__()
        self.audio = audio_client

    def hablando(self) -> bool:
        return False        # TtsMaker no dice cuando termino

    def decir(self, texto: str, esperar: bool = False) -> None:
        print(f"  [ROBOT] {texto}")
        try:
            self.audio.TtsMaker(texto, 0)
        except Exception as exc:                              # noqa: BLE001
            print(f"  [VOZ] no pudo hablar: {exc}")


def _hay(programa: str) -> bool:
    from shutil import which
    return which(programa) is not None


# --------------------------------------------------------------------------
#  Escuchar
# --------------------------------------------------------------------------
class Oido:
    """Escucha el microfono y avisa cuando oye una de las palabras esperadas.

    No bloquea nunca: el audio entra por un callback, un hilo lo pasa por vosk,
    y `escuchar()` saca de una cola lo que haya. Si no hay microfono o falta el
    modelo, arranca APAGADO y el juego sigue andando con el teclado -- que es
    lo que salva la demo en un aula con ruido.
    """

    TASA = 16000

    def __init__(self, palabras, verboso: bool = True):
        self.palabras = tuple(p.lower() for p in palabras)
        # Hasta cuando ignorar lo que entra. EL PROBLEMA QUE ESTO RESUELVE:
        # el robot habla por los parlantes y el microfono lo escucha. Con una
        # gramatica cerrada eso es peor que un falso positivo suelto, porque
        # vosk EMPUJA todo lo que oye hacia la palabra mas parecida de la
        # lista: el robot decia "deci arrancar" y el juego arrancaba solo, y
        # al cantar el resultado se disparaba cualquier otra.
        self._mudo_hasta = 0.0
        self.encendido = False
        self.motivo = ""
        self._oidas: queue.Queue = queue.Queue()
        self._audio: queue.Queue = queue.Queue()
        self._flujo = None
        self._parar = threading.Event()
        try:
            self._arrancar()
            self.encendido = True
        except Exception as exc:                              # noqa: BLE001
            self.motivo = f"{type(exc).__name__}: {exc}"
            if verboso:
                print(f"  [OIDO] sin microfono ({self.motivo}).")
                print("         Se juega con la barra espaciadora.")

    def _arrancar(self) -> None:
        import sounddevice
        from vosk import KaldiRecognizer, Model, SetLogLevel

        if not os.path.isdir(MODELO_VOZ):
            raise FileNotFoundError(
                f"falta el modelo de voz en {MODELO_VOZ}; se baja de "
                "https://alphacephei.com/vosk/models "
                "(vosk-model-small-es-0.42)")
        SetLogLevel(-1)
        # Gramatica cerrada: vosk solo puede devolver estas palabras. "[unk]"
        # es la valvula de escape para todo lo demas, y es lo que evita que
        # cualquier ruido se transcriba como una de las nuestras.
        gramatica = json.dumps(list(self.palabras) + ["[unk]"])
        self._rec = KaldiRecognizer(Model(MODELO_VOZ), self.TASA, gramatica)

        def entra(datos, _cuadros, _tiempo, estado):          # noqa: ANN001
            self._audio.put(bytes(datos))

        self._flujo = sounddevice.RawInputStream(
            samplerate=self.TASA, blocksize=4000, dtype="int16",
            channels=1, callback=entra)
        self._flujo.start()
        threading.Thread(target=self._transcribir, daemon=True).start()

    def _transcribir(self) -> None:
        while not self._parar.is_set():
            try:
                trozo = self._audio.get(timeout=0.3)
            except queue.Empty:
                continue
            # Se miran los resultados PARCIALES ademas de los finales: vosk
            # cierra una frase recien cuando detecta silencio, y esperar ese
            # silencio agrega casi un segundo entre que decis "arrancar" y que
            # el robot reaccione.
            if self._rec.AcceptWaveform(trozo):
                texto = json.loads(self._rec.Result()).get("text", "")
            else:
                texto = json.loads(self._rec.PartialResult()).get("partial", "")
            for palabra in self.palabras:
                if palabra in texto:
                    self._oidas.put(palabra)
                    self._rec.Reset()
                    break

    def callar(self, segundos: float = 0.6) -> None:
        """Ignora lo que entre por los proximos `segundos`.

        La cola de audio ya grabada tambien se tira: si no, la voz del robot
        entra igual apenas se vuelve a escuchar.
        """
        self._mudo_hasta = max(self._mudo_hasta,
                               time.monotonic() + max(0.0, segundos))

    def escuchar(self) -> str | None:
        """La ultima palabra oida, o None. No bloquea."""
        if time.monotonic() < self._mudo_hasta:
            self._vaciar()
            return None
        try:
            return self._oidas.get_nowait()
        except queue.Empty:
            return None

    def _vaciar(self) -> None:
        while True:
            try:
                self._oidas.get_nowait()
            except queue.Empty:
                return

    def limpiar(self) -> None:
        """Tira lo que se haya oido. Se llama al empezar una ronda, para que la
        cuenta del robot no se dispare dos veces con el mismo 'arrancar'."""
        self._vaciar()

    def cerrar(self) -> None:
        self._parar.set()
        if self._flujo is not None:
            try:
                self._flujo.stop()
                self._flujo.close()
            except Exception:                                 # noqa: BLE001
                pass


def _demo() -> None:
    import time
    voz = Voz()
    voz.decir("Probando. Deci arrancar cuando quieras.", esperar=True)
    oido = Oido(("arrancar", "de nuevo"))
    if not oido.encendido:
        raise SystemExit("Sin microfono, no hay nada que probar.")
    print("  escuchando... (Ctrl+C para cortar)")
    try:
        while True:
            palabra = oido.escuchar()
            if palabra:
                print(f"  --> te escuche: {palabra!r}")
                voz.decir(f"escuche {palabra}")
                oido.callar(2.0)     # que no se escuche a si mismo
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    oido.cerrar()
    voz.cerrar()


if __name__ == "__main__":
    _demo()
