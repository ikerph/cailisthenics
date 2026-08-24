-- FASE 3 - Esquema SQLite del histórico. Vive en el dispositivo.
--
-- Este fichero es la fuente de la verdad. El cliente Flutter lo ejecuta tal
-- cual al crear la base de datos; no se reescribe el DDL en Dart, porque dos
-- copias del esquema divergen el día que alguien toca solo una.
--
-- Dos reglas que no se negocian y que explican la forma de todo esto:
--
--   1. Persistencia REP A REP. La tabla `repeticion` es el dato; `serie` es
--      solo su cabecera. Un histórico que guarde "12 dominadas, ratio medio
--      1,3" no permite volver a preguntarle nada: el día que se quiera saber
--      si la caída de velocidad es mayor en las últimas tres repeticiones, el
--      dato ya no está. Los agregados se recalculan; las repeticiones no se
--      recuperan.
--   2. `version_pipeline` es OBLIGATORIO. Cuando se pase de nariz a barbilla,
--      o cambie el umbral de fase, las series viejas seguirán siendo correctas
--      pero dejarán de ser la misma magnitud. Sin esta columna, el gráfico de
--      progresión mezclaría dos reglas de medir distintas y enseñaría una
--      mejora que no existe.

PRAGMA foreign_keys = ON;
-- ^ NO es decorativo y no basta con ponerlo aquí. SQLite ignora las claves
-- ajenas por defecto, POR CONEXIÓN: sin este pragma el ON DELETE CASCADE de
-- abajo no borra nada y las repeticiones quedan huérfanas para siempre. El
-- cliente tiene que ejecutarlo en cada conexión que abra, no solo al crear.

PRAGMA journal_mode = WAL;
-- Escrituras y lecturas a la vez: guardar una serie no bloquea la pantalla de
-- histórico que la está leyendo.


CREATE TABLE IF NOT EXISTS usuario (
  id             INTEGER PRIMARY KEY,
  username       TEXT    UNIQUE NOT NULL,
  nombre         TEXT,
  fecha_creacion TEXT    NOT NULL
);


CREATE TABLE IF NOT EXISTS serie (
  id                  INTEGER PRIMARY KEY,
  device_id           TEXT    NOT NULL,
  usuario_id          INTEGER REFERENCES usuario(id) ON DELETE SET NULL,
  fecha_utc           TEXT    NOT NULL,   -- ISO-8601 en UTC, siempre con zona
  fps                 REAL,
  paso                INTEGER,
  escala_px_bu        REAL,               -- anchura biacromial mediana, en px
  recorrido_bu        REAL,
  n_total             INTEGER,
  n_validas           INTEGER,
  caida_velocidad     REAL,               -- pendiente bu/s por repetición
  notas               TEXT,
  keypoints_json_path TEXT,               -- el dataset, fuera de la base
  video_anotado_path  TEXT,               -- el vídeo con trackpoints en el móvil
  version_pipeline    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS repeticion (
  id                 INTEGER PRIMARY KEY,
  serie_id           INTEGER NOT NULL REFERENCES serie(id) ON DELETE CASCADE,
  numero             INTEGER NOT NULL,
  instante_s         REAL,
  rom_bu             REAL,
  t_subida_s         REAL,
  t_bajada_s         REAL,
  ratio_ecc_con      REAL,
  v_pico_concentrica REAL,
  margen_bu          REAL,
  valida             INTEGER NOT NULL,

  -- Añadida sobre el esquema del spec, y antes de que esto se publique.
  -- Una repetición pegada al principio o al final del vídeo tiene la fase
  -- cortada por el encuadre temporal: su duración es un MÍNIMO, no una medida.
  -- El análisis ya la excluye de las medias. Sin esta columna, al releer la
  -- serie del histórico esa marca desaparece y la repetición vuelve a contar,
  -- así que la media del histórico y la de la pantalla de resultado no
  -- coincidirían para la misma serie, sin que nada avise.
  truncada           INTEGER NOT NULL DEFAULT 0
);


-- --- lo que el esquema del spec no traía y hace falta igual ---------------

-- La pantalla de histórico pide siempre lo mismo: las series de este
-- dispositivo, de la más nueva a la más vieja. Sin índice eso es un recorrido
-- completo de la tabla en cada apertura.
CREATE INDEX IF NOT EXISTS idx_serie_device_fecha
  ON serie(device_id, fecha_utc DESC);

CREATE INDEX IF NOT EXISTS idx_serie_usuario
  ON serie(usuario_id, fecha_utc DESC);

-- Y para agrupar por regla de medir cuando se pinta la progresión.
CREATE INDEX IF NOT EXISTS idx_serie_version
  ON serie(version_pipeline);

-- Cargar las repeticiones de una serie es la consulta más frecuente de todas.
-- SQLite no indexa las claves ajenas por su cuenta.
CREATE INDEX IF NOT EXISTS idx_repeticion_serie
  ON repeticion(serie_id, numero);

-- Una serie no puede tener dos repeticiones con el mismo número. Sujeta el
-- caso de guardar dos veces el mismo análisis por un reintento del cliente.
CREATE UNIQUE INDEX IF NOT EXISTS idx_repeticion_unica
  ON repeticion(serie_id, numero);


-- Versión del ESQUEMA, que no es lo mismo que la del pipeline: una dice cómo
-- están guardados los datos, la otra cómo se midieron. Se pueden mover por
-- separado y hay que poder distinguirlas.
CREATE TABLE IF NOT EXISTS version_esquema (
  version   INTEGER PRIMARY KEY,
  aplicada  TEXT NOT NULL
);

INSERT OR IGNORE INTO version_esquema (version, aplicada)
  VALUES (1, datetime('now'));
