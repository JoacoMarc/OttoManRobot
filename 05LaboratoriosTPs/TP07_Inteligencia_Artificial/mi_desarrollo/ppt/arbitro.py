"""Las reglas del juego, el marcador, y el compromiso previo del robot.

Lo importante de este archivo es `Compromiso`. El robot elige su jugada ANTES
de mirar tu mano, y para que eso sea VERIFICABLE y no una promesa, publica un
sello: el SHA-256 de su jugada mas un numero al azar. Al final revela las dos
cosas y cualquiera puede recalcular el sello y comprobar que era esa jugada y
no otra.

Sin esto, "el robot eligio antes" es algo que dice el que escribio el codigo.
Con esto, es algo que se comprueba.
"""

from __future__ import annotations

import csv
import hashlib
import os
import random
import secrets
import time
from dataclasses import dataclass, field

JUGADAS = ("piedra", "papel", "tijera")
LE_GANA_A = {"piedra": "tijera", "papel": "piedra", "tijera": "papel"}

EMPATE, GANA_ROBOT, GANA_HUMANO = "empate", "gana_robot", "gana_humano"


def resolver(robot: str, humano: str) -> str:
    if robot == humano:
        return EMPATE
    return GANA_ROBOT if LE_GANA_A[robot] == humano else GANA_HUMANO


@dataclass
class Compromiso:
    """La jugada del robot, elegida y sellada antes de mirar."""

    jugada: str
    sal: str
    sello: str

    @classmethod
    def nuevo(cls) -> "Compromiso":
        jugada = random.choice(JUGADAS)
        sal = secrets.token_hex(8)
        sello = hashlib.sha256(f"{jugada}|{sal}".encode()).hexdigest()
        return cls(jugada=jugada, sal=sal, sello=sello)

    def verifica(self) -> bool:
        esperado = hashlib.sha256(f"{self.jugada}|{self.sal}".encode())
        return esperado.hexdigest() == self.sello


def votar(votos, minimo: int = 6, mayoria: float = 0.55):
    """Que jugada hizo el humano, a partir de los cuadros de la ventana.

    Devuelve (jugada, motivo_del_rechazo). Si la jugada es None, el motivo dice
    por que. Preferimos ANULAR la ronda antes que adivinar: en una demo, un
    robot que dice "no te vi la mano" es creible; uno que se equivoca, no.
    """
    validos = [v for v in votos if v]
    if len(validos) < minimo:
        return None, "no te vi bien la mano"
    conteo = {j: validos.count(j) for j in set(validos)}
    ganadora = max(conteo, key=conteo.get)
    if conteo[ganadora] / len(validos) < mayoria:
        return None, "no me quedo clara la mano"
    # Anti-trampa: si la primera mitad de la ventana dice una cosa y la segunda
    # otra, cambiaste la mano mientras el robot tiraba.
    mitad = len(validos) // 2
    if mitad >= 2:
        pri, seg = validos[:mitad], validos[mitad:]
        if max(set(pri), key=pri.count) != max(set(seg), key=seg.count):
            return None, "cambiaste la mano a mitad de camino"
    return ganadora, ""


@dataclass
class Marcador:
    robot: int = 0
    humano: int = 0
    empates: int = 0
    nulas: int = 0
    filas: list = field(default_factory=list)

    def anotar(self, resultado: str) -> None:
        if resultado == GANA_ROBOT:
            self.robot += 1
        elif resultado == GANA_HUMANO:
            self.humano += 1
        else:
            self.empates += 1

    @property
    def jugadas(self) -> int:
        return self.robot + self.humano + self.empates

    def registrar(self, comp: Compromiso, humano: str, resultado: str,
                  votos_validos: int) -> None:
        self.filas.append({
            "cuando": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sello": comp.sello[:16], "sal": comp.sal,
            "jugada_robot": comp.jugada, "jugada_humano": humano,
            "resultado": resultado, "votos_validos": votos_validos,
        })

    def guardar(self, ruta: str) -> None:
        if not self.filas:
            return
        nuevo = not os.path.exists(ruta)
        with open(ruta, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(self.filas[0]))
            if nuevo:
                w.writeheader()
            w.writerows(self.filas)

    def __str__(self) -> str:
        return (f"robot {self.robot} - vos {self.humano}  "
                f"(empates {self.empates}, nulas {self.nulas})")
