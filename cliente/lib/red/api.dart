/// Cliente del backend: subir el vídeo y sondear hasta que haya resultado.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import '../modelo/analisis.dart';

/// Estado de un análisis en curso, para la barra de progreso.
class Avance {
  const Avance(this.estado, this.progreso);
  final String estado;

  /// De 0 a 1. El servidor reparte: 0,80 la pose, el resto análisis y render.
  final double progreso;
}

class Api {
  Api(this.baseUrl, this.clave, {http.Client? cliente})
      : _cliente = cliente ?? http.Client();

  final String baseUrl;

  /// Contraseña compartida con el backend. Va en TODAS las peticiones: el
  /// servidor responde 401 a cualquiera que no la lleve, incluidos los 404.
  final String clave;

  final http.Client _cliente;

  /// Cabecera propia en vez de `Authorization`, que algunos proxies reescriben
  /// o borran por su cuenta y dejan un 401 sin motivo aparente.
  static const cabeceraClave = 'X-Cai-Clave';

  Map<String, String> get _cabeceras => {cabeceraClave: clave};

  static const _intervaloSondeo = Duration(milliseconds: 900);

  /// Tope de espera. Un vídeo de 30 s tarda 6-14 s; si a los tres minutos no
  /// hay respuesta, algo se ha quedado colgado y es mejor decirlo que dejar la
  /// rueda girando para siempre.
  static const _limiteEspera = Duration(minutes: 3);

  void cerrar() => _cliente.close();

  /// Comprueba que se llega al servidor Y que la contraseña es la correcta.
  ///
  /// Se usa al guardar los ajustes, antes de gastar una subida entera: subir un
  /// vídeo de 100 MB por una red móvil para que el servidor conteste 401 al
  /// final es exactamente lo que hay que evitar.
  ///
  /// Devuelve `null` si todo está bien, o el fallo que corresponda.
  Future<FalloAnalisis?> comprobar() async {
    final http.Response respuesta;
    try {
      respuesta = await _cliente
          .get(Uri.parse('$baseUrl/salud'), headers: _cabeceras)
          .timeout(const Duration(seconds: 15));
    } on SocketException {
      return FalloAnalisis.red;
    } on http.ClientException {
      return FalloAnalisis.red;
    } on TimeoutException {
      return FalloAnalisis.red;
    } on FormatException {
      // Una URL mal escrita: `Uri.parse` acepta casi cualquier cosa y falla
      // aquí. Es el error más probable escribiendo la dirección a mano.
      return FalloAnalisis.direccion;
    }

    if (respuesta.statusCode == 200) return null;
    if (respuesta.statusCode == 401) return _fallo(_json(respuesta.body));
    return FalloAnalisis.direccion;
  }

  /// Analiza un vídeo. Emite avances y termina devolviendo el análisis.
  ///
  /// Lanza [FalloAnalisis] con una instrucción concreta si algo va mal: nunca
  /// una excepción cruda de red o de parseo.
  Future<Analisis> analizar(
    File video, {
    required String deviceId,
    bool anotar = false,
    void Function(Avance)? alAvanzar,
  }) async {
    final jobId = await _subir(video, deviceId: deviceId, anotar: anotar);
    return _esperar(jobId, alAvanzar: alAvanzar);
  }

  Future<String> _subir(
    File video, {
    required String deviceId,
    required bool anotar,
  }) async {
    final peticion = http.MultipartRequest('POST', Uri.parse('$baseUrl/analizar'))
      ..headers.addAll(_cabeceras)
      ..fields['device_id'] = deviceId
      ..fields['anotar'] = anotar.toString()
      ..files.add(await http.MultipartFile.fromPath('video', video.path));

    final http.Response respuesta;
    try {
      respuesta = await http.Response.fromStream(await _cliente.send(peticion));
    } on SocketException {
      throw FalloAnalisis.red;
    } on http.ClientException {
      throw FalloAnalisis.red;
    }

    final cuerpo = _json(respuesta.body);
    if (respuesta.statusCode != 202) throw _fallo(cuerpo);

    final jobId = cuerpo['job_id'] as String?;
    if (jobId == null) throw _fallo(cuerpo);
    return jobId;
  }

  Future<Analisis> _esperar(String jobId, {void Function(Avance)? alAvanzar}) async {
    final limite = DateTime.now().add(_limiteEspera);

    while (DateTime.now().isBefore(limite)) {
      final http.Response respuesta;
      try {
        respuesta = await _cliente.get(Uri.parse('$baseUrl/estado/$jobId'),
            headers: _cabeceras);
      } on SocketException {
        throw FalloAnalisis.red;
      } on http.ClientException {
        throw FalloAnalisis.red;
      }

      final cuerpo = _json(respuesta.body);
      final estado = cuerpo['estado'] as String?;

      if (respuesta.statusCode == 404 || estado == 'error') throw _fallo(cuerpo);
      if (estado == 'hecho') return Analisis.desdeJson(cuerpo);

      alAvanzar?.call(Avance(
        estado ?? 'procesando',
        (cuerpo['progreso'] as num?)?.toDouble() ?? 0,
      ));
      await Future<void>.delayed(_intervaloSondeo);
    }

    throw const FalloAnalisis(
      codigo: 'TIEMPO_AGOTADO',
      titulo: 'El análisis está tardando demasiado',
      instruccion:
          'El servidor no ha respondido a tiempo. Vuelve a intentarlo; si sigue '
          'pasando, prueba con un vídeo más corto.',
      reintentable: true,
    );
  }

  /// Avisa al servidor de que ya no hace falta guardar nada del análisis.
  ///
  /// Se llama en cuanto la serie está en la base de datos del móvil. No es
  /// obligatorio -el servidor purga solo a los quince minutos- pero no hay
  /// razón para que una copia del análisis de alguien siga ahí.
  Future<void> olvidar(String jobId) async {
    try {
      await _cliente.delete(Uri.parse('$baseUrl/estado/$jobId'),
          headers: _cabeceras);
    } catch (_) {
      // Si falla, el servidor lo purgará por su cuenta. No molestar al usuario.
    }
  }

  /// Descarga el vídeo anotado generado por el servidor y lo guarda en [destino].
  Future<File?> descargarVideo(String urlVideo, File destino) async {
    try {
      final respuesta = await _cliente.get(Uri.parse(urlVideo), headers: _cabeceras);
      if (respuesta.statusCode == 200 && respuesta.bodyBytes.isNotEmpty) {
        await destino.writeAsBytes(respuesta.bodyBytes);
        return destino;
      }
    } catch (_) {
      // Continuar silenciosamente si la descarga falla
    }
    return null;
  }

  Map<String, dynamic> _json(String cuerpo) {
    try {
      final decodificado = jsonDecode(cuerpo);
      if (decodificado is Map<String, dynamic>) return decodificado;
    } catch (_) {
      // Cae al mapa vacío y de ahí a DESCONOCIDO.
    }
    return const {};
  }

  FalloAnalisis _fallo(Map<String, dynamic> cuerpo) {
    final error = (cuerpo['error'] as Map?)?.cast<String, dynamic>();
    if (error != null) return FalloAnalisis.desdeJson(error);
    return const FalloAnalisis(
      codigo: 'DESCONOCIDO',
      titulo: 'No se pudo analizar el vídeo',
      instruccion:
          'Algo falló al procesar. Prueba con otra grabación: cuerpo entero, de '
          'frente, buena luz y nadie más en el encuadre.',
      reintentable: true,
    );
  }
}
