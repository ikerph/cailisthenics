/// FASE 3 en el dispositivo: el histórico.
///
/// El esquema NO se escribe aquí. Se lee de `assets/esquema/001_inicial.sql`,
/// que es copia del fichero de la raíz del repositorio. Dos copias del DDL -una
/// en SQL y otra en Dart- divergen el día que alguien toca solo una, y esa
/// divergencia se descubre en el móvil de un usuario, que es el peor sitio.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:flutter/services.dart' show rootBundle;
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

import '../config.dart';
import '../modelo/analisis.dart';

/// Un usuario registrado en el dispositivo.
class Usuario {
  const Usuario({
    required this.id,
    required this.username,
    this.nombre,
    required this.fechaCreacion,
  });

  final int id;
  final String username;
  final String? nombre;
  final DateTime fechaCreacion;
}

/// Una serie tal y como sale del histórico.
class SerieGuardada {
  const SerieGuardada({
    required this.id,
    this.usuarioId,
    required this.fechaUtc,
    required this.nTotal,
    required this.nValidas,
    required this.versionPipeline,
    this.escalaPxBu,
    this.recorridoBu,
    this.caidaVelocidad,
    this.notas,
    this.keypointsPath,
    this.videoAnotadoPath,
    this.repeticiones = const [],
  });

  final int id;
  final int? usuarioId;
  final DateTime fechaUtc;
  final int nTotal;
  final int nValidas;
  final String versionPipeline;
  final double? escalaPxBu;
  final double? recorridoBu;
  final double? caidaVelocidad;
  final String? notas;
  final String? keypointsPath;
  final String? videoAnotadoPath;
  final List<Repeticion> repeticiones;

  /// Media de un campo sobre las repeticiones que sirven.
  ///
  /// Se recalcula desde las repeticiones en vez de guardarse: es justo la razón
  /// de persistir rep a rep. El día que haga falta "el ratio de las tres
  /// últimas", el dato está.
  double? mediaDe(double? Function(Repeticion) campo) {
    final valores = repeticiones
        .where((r) => !r.truncada)
        .map(campo)
        .whereType<double>()
        .toList();
    if (valores.isEmpty) return null;
    return valores.reduce((a, b) => a + b) / valores.length;
  }

  double? get ratioMedio => mediaDe((r) => r.ratioEccCon);
  double? get romMedio => mediaDe((r) => r.romBu);
}

class Almacen {
  Almacen._(this._db, this.deviceId, this._carpetaKeypoints, this._carpetaVideos,
      this._ficheroServidor, this.servidor, this._ficheroClave, this.clave);

  final Database _db;

  /// Identificador local.
  final String deviceId;

  final Directory _carpetaKeypoints;
  final Directory _carpetaVideos;
  final File _ficheroServidor;
  final File _ficheroClave;

  /// Dirección del backend.
  String servidor;

  /// Contraseña del backend. Sin ella el servidor rechaza TODAS las peticiones.
  ///
  /// Vive en el almacenamiento privado de la app, que en Android solo lee esta
  /// aplicación. No resiste un móvil rooteado; para eso haría falta el llavero
  /// del sistema y otra dependencia más.
  String clave;

  /// Usuario activo en la sesión.
  Usuario? usuarioActivo;

  static const _fichero = 'cai_listhenics.db';

  static Future<Almacen> abrir() async {
    final documentos = await getApplicationDocumentsDirectory();
    final ddl = await rootBundle.loadString('assets/esquema/001_inicial.sql');

    final db = await openDatabase(
      p.join(await getDatabasesPath(), _fichero),
      version: 1,
      onConfigure: (db) async {
        await db.execute('PRAGMA foreign_keys = ON');
        await db.rawQuery('PRAGMA journal_mode = WAL');
      },
      onCreate: (db, _) async {
        for (final sentencia in _sentencias(ddl)) {
          await db.execute(sentencia);
        }
      },
    );

    final keypoints = Directory(p.join(documentos.path, 'keypoints'));
    await keypoints.create(recursive: true);

    final videos = Directory(p.join(documentos.path, 'videos'));
    await videos.create(recursive: true);

    final ficheroServidor = File(p.join(documentos.path, 'servidor'));
    var servidor = baseUrl;
    if (await ficheroServidor.exists()) {
      final guardado = (await ficheroServidor.readAsString()).trim();
      if (guardado.isNotEmpty) servidor = guardado;
    }

    final ficheroClave = File(p.join(documentos.path, 'clave'));
    var clave = '';
    if (await ficheroClave.exists()) {
      clave = (await ficheroClave.readAsString()).trim();
    }

    final almacen = Almacen._(db, await _deviceId(documentos), keypoints, videos,
        ficheroServidor, servidor, ficheroClave, clave);

    // Cargar el primer usuario disponible si existe
    final usuarios = await almacen.obtenerUsuarios();
    if (usuarios.isNotEmpty) {
      almacen.usuarioActivo = usuarios.first;
    }

    return almacen;
  }

  Directory get carpetaVideos => _carpetaVideos;

  // --- Usuarios ------------------------------------------------------------

  Future<Usuario> crearUsuario({required String username, String? nombre}) async {
    final limpio = username.trim().toLowerCase();
    final fecha = DateTime.now().toUtc().toIso8601String();
    final id = await _db.insert('usuario', {
      'username': limpio,
      'nombre': nombre?.trim(),
      'fecha_creacion': fecha,
    });
    final nuevo = Usuario(
      id: id,
      username: limpio,
      nombre: nombre?.trim(),
      fechaCreacion: DateTime.parse(fecha),
    );
    usuarioActivo = nuevo;
    return nuevo;
  }

  Future<List<Usuario>> obtenerUsuarios() async {
    final filas = await _db.query('usuario', orderBy: 'fecha_creacion ASC');
    return filas
        .map((f) => Usuario(
              id: f['id'] as int,
              username: f['username'] as String,
              nombre: f['nombre'] as String?,
              fechaCreacion: DateTime.parse(f['fecha_creacion'] as String),
            ))
        .toList();
  }

  Future<Usuario?> buscarUsuario(String username) async {
    final filas = await _db.query(
      'usuario',
      where: 'username = ?',
      whereArgs: [username.trim().toLowerCase()],
      limit: 1,
    );
    if (filas.isEmpty) return null;
    final f = filas.first;
    return Usuario(
      id: f['id'] as int,
      username: f['username'] as String,
      nombre: f['nombre'] as String?,
      fechaCreacion: DateTime.parse(f['fecha_creacion'] as String),
    );
  }

  void seleccionarUsuario(Usuario? usuario) {
    usuarioActivo = usuario;
  }

  /// Cambia backend y contraseña, y los recuerda para el próximo arranque.
  Future<void> guardarAcceso({required String url, required String clave}) async {
    servidor = url.trim();
    this.clave = clave.trim();
    await _ficheroServidor.writeAsString(servidor);
    await _ficheroClave.writeAsString(this.clave);
  }

  static Iterable<String> _sentencias(String ddl) sync* {
    final sinComentarios = ddl
        .split('\n')
        .map((linea) =>
            linea.contains('--') ? linea.substring(0, linea.indexOf('--')) : linea)
        .join('\n');

    for (final trozo in sinComentarios.split(';')) {
      final limpio = trozo.trim();
      if (limpio.isEmpty) continue;
      if (limpio.toUpperCase().startsWith('PRAGMA')) continue;
      yield limpio;
    }
  }

  @visibleForTesting
  static Iterable<String> sentenciasParaPruebas(String ddl) => _sentencias(ddl);

  static Future<String> _deviceId(Directory documentos) async {
    final fichero = File(p.join(documentos.path, 'device_id'));
    if (await fichero.exists()) {
      final guardado = (await fichero.readAsString()).trim();
      if (guardado.isNotEmpty) return guardado;
    }
    final azar = Random.secure();
    final id = List.generate(16, (_) => azar.nextInt(256))
        .map((b) => b.toRadixString(16).padLeft(2, '0'))
        .join();
    await fichero.writeAsString(id);
    return id;
  }

  Future<void> cerrar() => _db.close();

  // --- guardar -------------------------------------------------------------

  /// Guarda una serie con TODAS sus repeticiones, JSON de keypoints y vídeo anotado.
  Future<int> guardar(
    Analisis analisis, {
    String? notas,
    String? videoAnotadoPath,
    int? usuarioId,
  }) async {
    final fecha = DateTime.now().toUtc().toIso8601String();
    final rutaKeypoints = await _guardarKeypoints(analisis);
    final uid = usuarioId ?? usuarioActivo?.id;

    return _db.transaction((txn) async {
      final serieId = await txn.insert('serie', {
        'device_id': deviceId,
        'usuario_id': uid,
        'fecha_utc': fecha,
        'fps': analisis.fps,
        'paso': analisis.paso,
        'escala_px_bu': analisis.escalaPxBu,
        'recorrido_bu': analisis.recorridoBu,
        'n_total': analisis.nTotal,
        'n_validas': analisis.nValidas,
        'caida_velocidad': analisis.resumen.caidaVelocidad,
        'notas': notas,
        'keypoints_json_path': rutaKeypoints,
        'video_anotado_path': videoAnotadoPath,
        'version_pipeline': analisis.versionPipeline,
      });

      final lote = txn.batch();
      for (final r in analisis.repeticiones) {
        lote.insert('repeticion', {
          'serie_id': serieId,
          'numero': r.numero,
          'instante_s': r.instanteS,
          'rom_bu': r.romBu,
          't_subida_s': r.tSubidaS,
          't_bajada_s': r.tBajadaS,
          'ratio_ecc_con': r.ratioEccCon,
          'v_pico_concentrica': r.vPicoConcentrica,
          'margen_bu': r.margenBu,
          'valida': r.valida ? 1 : 0,
          'truncada': r.truncada ? 1 : 0,
        });
      }
      await lote.commit(noResult: true);
      return serieId;
    });
  }

  Future<String?> _guardarKeypoints(Analisis analisis) async {
    if (analisis.keypoints.isEmpty) return null;
    final nombre = '${DateTime.now().toUtc().millisecondsSinceEpoch}.json.gz';
    final fichero = File(p.join(_carpetaKeypoints.path, nombre));
    final crudo = utf8.encode(jsonEncode(analisis.keypoints));
    await fichero.writeAsBytes(gzip.encode(crudo));
    return fichero.path;
  }

  // --- leer ----------------------------------------------------------------

  /// El histórico, filtrado opcionalmente por usuario.
  Future<List<SerieGuardada>> historico({int? usuarioId, int limite = 200}) async {
    final uid = usuarioId ?? usuarioActivo?.id;
    final String whereClause;
    final List<Object?> whereArgs;

    if (uid != null) {
      whereClause = 'usuario_id = ?';
      whereArgs = [uid];
    } else {
      whereClause = 'device_id = ?';
      whereArgs = [deviceId];
    }

    final filas = await _db.query(
      'serie',
      where: whereClause,
      whereArgs: whereArgs,
      orderBy: 'fecha_utc DESC',
      limit: limite,
    );

    final series = <SerieGuardada>[];
    for (final fila in filas) {
      final reps = await _db.query(
        'repeticion',
        where: 'serie_id = ?',
        whereArgs: [fila['id']],
        orderBy: 'numero',
      );
      series.add(SerieGuardada(
        id: fila['id'] as int,
        usuarioId: fila['usuario_id'] as int?,
        fechaUtc: DateTime.parse(fila['fecha_utc'] as String),
        nTotal: (fila['n_total'] as int?) ?? reps.length,
        nValidas: (fila['n_validas'] as int?) ?? 0,
        versionPipeline: fila['version_pipeline'] as String,
        escalaPxBu: (fila['escala_px_bu'] as num?)?.toDouble(),
        recorridoBu: (fila['recorrido_bu'] as num?)?.toDouble(),
        caidaVelocidad: (fila['caida_velocidad'] as num?)?.toDouble(),
        notas: fila['notas'] as String?,
        keypointsPath: fila['keypoints_json_path'] as String?,
        videoAnotadoPath: fila['video_anotado_path'] as String?,
        repeticiones: reps
            .map((r) => Repeticion(
                  numero: r['numero'] as int,
                  valida: (r['valida'] as int) == 1,
                  truncada: ((r['truncada'] as int?) ?? 0) == 1,
                  instanteS: (r['instante_s'] as num?)?.toDouble(),
                  romBu: (r['rom_bu'] as num?)?.toDouble(),
                  tSubidaS: (r['t_subida_s'] as num?)?.toDouble(),
                  tBajadaS: (r['t_bajada_s'] as num?)?.toDouble(),
                  ratioEccCon: (r['ratio_ecc_con'] as num?)?.toDouble(),
                  vPicoConcentrica: (r['v_pico_concentrica'] as num?)?.toDouble(),
                  margenBu: (r['margen_bu'] as num?)?.toDouble(),
                ))
            .toList(growable: false),
      ));
    }
    return series;
  }

  /// Borra una serie, sus repeticiones, su fichero de keypoints y su vídeo.
  Future<void> borrar(SerieGuardada serie) async {
    await _db.delete('serie', where: 'id = ?', whereArgs: [serie.id]);
    final rutaKp = serie.keypointsPath;
    if (rutaKp != null) {
      final f = File(rutaKp);
      if (await f.exists()) await f.delete();
    }
    final rutaVid = serie.videoAnotadoPath;
    if (rutaVid != null) {
      final f = File(rutaVid);
      if (await f.exists()) await f.delete();
    }
  }
}
