# Laboratorio 3 - Algoritmos de Enrutamiento

Implementación individual y modular de los algoritmos solicitados en CC3067 Redes:

- Dijkstra.
- Flooding con TTL y supresión de duplicados.
- Link State Routing (LSR) con anuncios LSP, flooding y Dijkstra.
- Distance Vector Routing (DVR) con Bellman-Ford y poison reverse.

Incluye un protocolo JSON común, archivos de configuración, simulación determinista,
nodos independientes sobre TCP asíncrono y pruebas automatizadas. El proyecto usa
Python 3.11 o superior y no tiene dependencias de ejecución externas.

## Instalación

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

En Linux o macOS, la activación del entorno es `source .venv/bin/activate`; los demás
comandos son iguales.

## Prueba rápida

Simular un mensaje sobre la topología de ejemplo:

```powershell
routing-lab simulate `
  --algorithm lsr `
  --topology examples/topo-demo.txt `
  --source A `
  --destination H `
  --message "Hola desde A" `
  --show-tables
```

Cambie `lsr` por `dijkstra`, `flooding` o `dvr` para probar cada modo. El resultado
indica si el paquete llegó, la ruta seguida, transmisiones, descartes y cantidad de
mensajes de control necesarios para converger.

Para mostrar únicamente las tablas:

```powershell
routing-lab tables --algorithm dvr --topology examples/topo-demo.txt
```

También se puede ejecutar sin el comando instalado:

```powershell
$env:PYTHONPATH = "src"
python -m routing_lab simulate --algorithm dijkstra --topology examples/topo-demo.txt --source A --destination E --message "prueba"
```

## Nodos TCP independientes

Cada nodo abre un servidor TCP y mantiene dos tareas concurrentes: `forwarding` para
paquetes de datos y `routing` para LSP o vectores. Para una prueba distribuida, abra
una terminal por cada nodo participante y ejecute:

```powershell
routing-lab node `
  --id A `
  --algorithm lsr `
  --topology examples/topo-demo.txt `
  --endpoints examples/endpoints-demo.txt
```

Repita el comando cambiando `--id`. Todos los procesos deben usar el mismo algoritmo.
Dentro de la consola de un nodo están disponibles:

```text
send <destino> <mensaje>
table
help
quit
```

Los sockets se usan como medio local de la primera fase. El transporte está separado
de los algoritmos para poder sustituirlo por XMPP cuando el curso proporcione el
servidor y las credenciales oficiales.

## Archivos de configuración

`topo-*.txt` sigue el formato del enunciado. Acepta vecinos como lista (costo 1):

```json
{"type":"topo","config":{"A":["B"],"B":["A"]}}
```

También acepta un objeto para representar enlaces ponderados:

```json
{"type":"topo","config":{"A":{"B":7},"B":{"A":7}}}
```

`names-*.txt` asigna los identificadores lógicos a las direcciones oficiales y el
archivo local `endpoints-*.txt` contiene `host` y `port` para las pruebas TCP. Hay
ejemplos completos en [`examples`](examples/).

La restricción del laboratorio se respeta: Dijkstra puro recibe la topología completa;
Flooding, LSR y DVR solamente inicializan cada router con sus enlaces locales. LSR
aprende la topología mediante LSP y DVR mediante las tablas anunciadas por vecinos.

## Pruebas

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Las pruebas verifican serialización y TTL, validación de configuración, cada algoritmo,
convergencia, cambio de enlaces y el recorrido real de un mensaje por tres servidores
TCP. La arquitectura interna se describe en [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Estructura

```text
src/routing_lab/
  algorithms/       Dijkstra, Flooding, LSR y DVR
  protocol.py       contrato JSON interoperable
  config.py         carga y validación de archivos
  simulator.py      red determinista en memoria
  runtime.py        transporte TCP y tareas concurrentes
  cli.py            interfaz de línea de comandos
examples/           topología, nombres y endpoints de demostración
tests/              pruebas unitarias y de integración
```

