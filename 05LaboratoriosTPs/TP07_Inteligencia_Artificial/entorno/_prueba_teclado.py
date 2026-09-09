"""Prueba temporal del teclado y los gestos. Se borra al terminar."""
import math
import time

from sim.arrancar import SimuladorOficial
from sim.mundo import Mundo
from sim.robots import ROBOTS, envolvente, obtener
from sim.safety import perfil
from sim.teclado import (AGACHARSE, ESPACIO, FLECHA_ABAJO, FLECHA_ARRIBA,
                         FLECHA_DER, FLECHA_IZQ, INICIO, TECLAS_USADAS, D, E,
                         H, J, M, P, Q, Teleoperador, _atajos_del_visor)
from sim.verificar import buscar_repo_oficial


class VisorFalso:
    """Lo que el Teleoperador usa del visor: nada mas que opt.flags."""

    class _Opt:
        def __init__(self):
            self.flags = [0] * 31

    def __init__(self):
        self.opt = self._Opt()


def nuevo(clave="g1"):
    m = Mundo(perfil("tp07"))
    t = Teleoperador(m, obtener(clave), verboso=False)
    t.enganchar(VisorFalso())
    return m, t


def correr(m, t, seg):
    """Imita el bucle del visor: refrescar + avanzar, a 50 Hz."""
    for _ in range(int(seg / 0.02)):
        t.refrescar()
        m.avanzar()
        time.sleep(0.02)


def pose(m):
    e = m.leer()
    return e["x"], e["y"], math.degrees(e["yaw"]), e["accion"]


print("=" * 64)
print("1. NINGUNA TECLA NUESTRA PISA UN FLAG IRREVERSIBLE")
print("=" * 64)
reversibles, irreversibles = _atajos_del_visor()
choques = [chr(k) for k in TECLAS_USADAS if k in irreversibles]
deshacibles = sorted(chr(k) for k in TECLAS_USADAS if k in reversibles)
libres = sorted(repr(chr(k)) for k in TECLAS_USADAS
                if k not in reversibles and k not in irreversibles)
print(f"   irreversibles que usamos : {choques}")
print(f"   se deshacen a mano       : {deshacibles}")
print(f"   libres de verdad         : {libres}")
assert not choques, choques

print()
print("=" * 64)
print("2. MOVIMIENTO CON FLECHAS")
print("=" * 64)
m, t = nuevo()
correr(m, t, 0.3)
assert pose(m)[:2] == (0.0, 0.0), "sin tocar nada tiene que quedarse quieto"
print(f"   sin tocar nada        x={pose(m)[0]:.2f} [{pose(m)[3]}]")

t.tecla(FLECHA_ARRIBA)
correr(m, t, 1.0)
x, y, yaw, accion = pose(m)
print(f"   flecha arriba (1 s)   x={x:.2f} [{accion}]")
assert x > 0.15 and accion == "avanzando"

t.tecla(FLECHA_ARRIBA)          # la misma tecla apaga
correr(m, t, 0.4)
x_frenado = pose(m)[0]
correr(m, t, 0.4)
print(f"   otra vez (apaga)      x={pose(m)[0]:.2f} [{pose(m)[3]}]")
assert pose(m)[3] == "quieto" and abs(pose(m)[0] - x_frenado) < 1e-6

m, t = nuevo()                  # se combinan: curva
t.tecla(FLECHA_ARRIBA)
t.tecla(FLECHA_IZQ)
correr(m, t, 2.0)
x, y, yaw, accion = pose(m)
print(f"   arriba + izquierda    x={x:.2f} y={y:.2f} rumbo={yaw:.0f}")
assert x > 0.05 and y > 0.05 and yaw > 20

t.tecla(ESPACIO)
correr(m, t, 0.3)
print(f"   espacio               [{pose(m)[3]}]")
assert pose(m)[3] == "quieto"

m, t = nuevo()                  # nunca pasa el techo del perfil
for tecla in (FLECHA_ARRIBA, Q, FLECHA_DER, FLECHA_ABAJO, E):
    t.tecla(tecla)
t.refrescar()
p = m.perfil
print(f"   todas juntas          vx={m.vx:+.2f} vy={m.vy:+.2f} vyaw={m.vyaw:+.2f}"
      f"  (techo {p.velocidad_max} m/s, {p.velocidad_angular_max} rad/s)")
assert abs(m.vx) <= p.velocidad_max and abs(m.vy) <= p.velocidad_max
assert abs(m.vyaw) <= p.velocidad_angular_max and not m.avisos

m, t = nuevo()                  # la orden vence si el bucle se detiene
t.tecla(FLECHA_ARRIBA)
t.refrescar()
time.sleep(0.6)
m.avanzar()
print(f"   bucle detenido 0.6 s  [{pose(m)[3]}]")
assert pose(m)[3] == "quieto"

print()
print("=" * 64)
print("3. LOS FLAGS DEL VISOR VUELVEN COMO ESTABAN")
print("=" * 64)
m, t = nuevo()
visor = t._visor
antes = list(visor.opt.flags)
for tecla in sorted(TECLAS_USADAS):
    indice = reversibles.get(tecla)
    if indice is not None:
        # El visor togglea ANTES de llamarnos: lo imitamos.
        visor.opt.flags[indice] = not visor.opt.flags[indice]
    t.tecla(tecla)
distintos = [i for i, (a, b) in enumerate(zip(antes, visor.opt.flags)) if a != b]
print(f"   apretadas {len(TECLAS_USADAS)} teclas, flags cambiados: {distintos}")
assert not distintos, distintos

print()
print("=" * 64)
print("4. GESTOS: ESTADO Y PROGRESO")
print("=" * 64)
for tecla, nombre in ((H, "saludo"), (D, "dar_la_mano"), (P, "patada"),
                      (J, "salto"), (M, "agarre")):
    m, t = nuevo()
    t.tecla(tecla)
    e = m.leer()
    g = ROBOTS["g1"].gestos[nombre]
    print(f"   {chr(tecla)} -> {e['accion']:12} progreso={e['progreso_gesto']:.2f} "
          f"dur={g.duracion}s  ({g.descripcion})")
    assert e["accion"] == nombre and not e["moviendose"]
    time.sleep(g.duracion / 2)
    assert 0.2 < m.leer()["progreso_gesto"] < 0.8, m.leer()["progreso_gesto"]
    time.sleep(g.duracion / 2 + 0.1)
    m.avanzar()
    assert m.leer()["accion"] == "quieto", "el gesto tiene que terminar solo"

m, t = nuevo()                  # un gesto suelta las teclas de movimiento
t.tecla(FLECHA_ARRIBA)
correr(m, t, 0.3)
t.tecla(P)
correr(m, t, 0.3)
print(f"   patada mientras andaba -> [{m.leer()['accion']}]")
assert m.leer()["accion"] == "patada"

m, t = nuevo(clave="go2")       # el Go2 no tiene manos: no rompe
t.tecla(M)
print(f"   M en el Go2            -> [{m.leer()['accion']}] (sin gesto, no falla)")
assert m.leer()["accion"] == "quieto"

# La envolvente arranca y termina en cero: ningun gesto queda a medio camino.
for clave in ("g1", "go2"):
    for nombre, g in obtener(clave).gestos.items():
        assert envolvente(g, 0.0) < 1e-9, (clave, nombre)
        assert envolvente(g, 1.0) < 1e-9, (clave, nombre)
        assert envolvente(g, 0.5) > 0.9, (clave, nombre)
print("   envolvente             0 en las puntas, llena al medio, en todos")

print()
print("=" * 64)
print("5. AGACHARSE Y VOLVER AL INICIO")
print("=" * 64)
m, t = nuevo()
t.tecla(AGACHARSE)
print(f"   C                      de_pie={m.leer()['de_pie']}")
assert not m.leer()["de_pie"]
t.tecla(FLECHA_ARRIBA)          # se para solo para poder moverse
correr(m, t, 0.6)
print(f"   flecha arriba          de_pie={m.leer()['de_pie']} "
      f"x={m.leer()['x']:.2f} [{m.leer()['accion']}]")
assert m.leer()["de_pie"] and m.leer()["x"] > 0.05
t.tecla(AGACHARSE)
t.tecla(AGACHARSE)
print(f"   C dos veces            de_pie={m.leer()['de_pie']}")
assert m.leer()["de_pie"]

t.tecla(FLECHA_ARRIBA)
correr(m, t, 0.5)
t.tecla(INICIO)
e = m.leer()
print(f"   I                      x={e['x']:.2f} y={e['y']:.2f} [{e['accion']}]")
assert (e["x"], e["y"], e["accion"], e["de_pie"]) == (0.0, 0.0, "quieto", True)

print()
print("=" * 64)
print("6. RENDER DE VERDAD, CONTRA EL MODELO OFICIAL")
print("=" * 64)
repo = buscar_repo_oficial()
for clave in ("g1", "go2"):
    robot = obtener(clave)
    mundo = Mundo(perfil("tp07"))
    sim = SimuladorOficial(mundo, robot, repo, verboso=False)
    art = sim.model.nq - 7
    print(f"   {robot.nombre}: {art} articulaciones")

    for nombre, g in robot.gestos.items():
        fuera = [i for i in list(g.articulaciones) + list(g.vibra) if i >= art]
        assert not fuera, f"{clave}/{nombre}: indices fuera del modelo: {fuera}"

    # El salto tiene que subir la base y dejarla donde estaba.
    sim._escribir_pose()
    z_parado = float(sim.data.qpos[2])
    mundo.gesto("salto", robot.gestos["salto"].duracion)
    time.sleep(robot.gestos["salto"].duracion / 2)
    sim._escribir_pose()
    z_arriba = float(sim.data.qpos[2])
    time.sleep(robot.gestos["salto"].duracion / 2 + 0.1)
    mundo.avanzar()
    sim._escribir_pose()
    z_vuelta = float(sim.data.qpos[2])
    print(f"     salto: z {z_parado:.3f} -> {z_arriba:.3f} -> {z_vuelta:.3f} m")
    assert z_arriba > z_parado + 0.1, "el salto tiene que levantar la base"
    assert abs(z_vuelta - z_parado) < 1e-9, "y tiene que volver al piso"

    # El saludo tiene que MOVER las articulaciones del gesto. Esto es el bug
    # que estaba: por el socket la accion llega como "saludo" y no se dibujaba.
    mundo.gesto("saludo", robot.gestos["saludo"].duracion)
    time.sleep(robot.gestos["saludo"].duracion / 2)
    sim._escribir_pose()
    movidas = {i: round(float(sim.data.qpos[7 + i]), 3)
               for i in robot.gestos["saludo"].articulaciones}
    print(f"     saludo: articulaciones {movidas}")
    for i, objetivo in robot.gestos["saludo"].articulaciones.items():
        base = robot.pose_de_pie.get(i, 0.0)
        assert abs(float(sim.data.qpos[7 + i]) - base) > 0.1, (
            f"la articulacion {i} no se movio (objetivo {objetivo})")

print()
print("Todo bien.")
