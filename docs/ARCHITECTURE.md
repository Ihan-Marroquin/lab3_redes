# Arquitectura

## Separación de responsabilidades

El código mantiene los algoritmos independientes del medio de transporte. `Packet`
define el contrato intercambiable; los routers deciden si entregan o reenvían; el
simulador y `TcpTransport` son responsables de mover el paquete al vecino indicado.

```text
archivo topo -> enlaces locales -> algoritmo -> decisión de forwarding
                                         |              |
                                         |              +-> vecino / entrega / descarte
                                         +-> tabla de rutas

socket TCP -> cola forwarding -> DATA/MESSAGE -> algoritmo
           -> cola routing    -> TABLE/INFO   -> algoritmo
```

Para LSR, cada nodo anuncia solamente sus propios enlaces. Los LSP nuevos se propagan
por flooding y la base de estados resultante se entrega al módulo reutilizable de
Dijkstra. Un número de secuencia descarta anuncios viejos y `max_age` permite retirar
nodos que dejan de anunciarse.

Para DVR, cada nodo conserva solamente los vectores recibidos de vecinos y aplica la
ecuación de Bellman-Ford. Las actualizaciones disparadas y periódicas usan split horizon
con poison reverse para reducir ciclos y el problema de conteo al infinito.

Flooding no mantiene tabla: usa un identificador global de paquete, caché LRU acotada,
TTL y exclusión del enlace entrante. Dijkstra puro calcula la tabla estática desde la
topología completa, la única excepción permitida por el enunciado.

## Protocolo

El contenido de cada trama sigue la estructura base del laboratorio:

```json
{
  "proto": "dijkstra|flooding|lsr|dvr",
  "type": "message|echo|info|hello|ack",
  "from": "A",
  "to": "B",
  "ttl": 16,
  "headers": [{"packet_id": "identificador-unico"}],
  "payload": "contenido o estructura de control"
}
```

La conexión TCP agrega externamente un sobre mínimo con el vecino emisor para saber
por cuál interfaz llegó la trama. El paquete interno no cambia:

```json
{"sender":"A","packet":{"proto":"lsr","type":"message","from":"A","to":"B","ttl":15,"headers":[{"packet_id":"..."}],"payload":"hola"}}
```

## Cambios de topología

`NetworkSimulator.set_link` permite crear, modificar o retirar un enlace. Dijkstra
recalcula desde el grafo; Flooding actualiza sus vecinos; LSR origina un LSP nuevo; y
DVR recalcula y anuncia el nuevo vector. `remove_node` simula la caída total de un
router. Los anuncios caducables de LSR y DVR cubren también la ausencia prolongada de
un nodo en la ejecución distribuida.

## Extensión a XMPP

Para la segunda fase se conserva `AsyncNode` y se reemplaza `TcpTransport` por un
transporte que implemente `start`, `send` y `close`, entregando a `_receive` el vecino y
un `Packet`. Esta separación evita reimplementar Dijkstra, Flooding, LSR o DVR cuando
se reciban el dominio, los usuarios y las credenciales XMPP oficiales.

