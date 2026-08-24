/// Lo que devuelve el backend, en tipos de Dart.
///
/// Casi todos los números son `double?` y no `double`, y no es por descuido: el
/// servidor manda `null` donde el pipeline produjo un NaN, y produce NaN con
/// motivo. La desviación típica de una serie de una sola repetición no es cero,
/// es "no hay". El ratio de una repetición sin fase medible no es cero, es "no
/// se pudo". Un `double` con 0 por defecto convertiría esos huecos en datos
/// falsos, y el gráfico enseñaría una caída a cero que nunca ocurrió.
library;

/// Lee un número que puede venir nulo, o entero donde se espera decimal.
double? _num(dynamic valor) {
  if (valor == null) return null;
  if (valor is num) return valor.toDouble();
  return null;
}

List<double?> _lista(dynamic valor) {
  if (valor is! List) return const [];
  return valor.map(_num).toList(growable: false);
}

/// Una repetición medida.
class Repeticion {
  const Repeticion({
    required this.numero,
    required this.valida,
    required this.truncada,
    this.instanteS,
    this.romBu,
    this.tSubidaS,
    this.tBajadaS,
    this.ratioEccCon,
    this.vPicoConcentrica,
    this.margenBu,
    this.desnivelHombrosBu,
    this.desviacionNarizBu,
  });

  final int numero;
  final bool valida;

  /// Alguna fase toca el borde del vídeo: la duración es un mínimo, no la real.
  /// La app la enseña marcada y no la mete en las medias.
  final bool truncada;

  final double? instanteS;
  final double? romBu;
  final double? tSubidaS;
  final double? tBajadaS;
  final double? ratioEccCon;
  final double? vPicoConcentrica;
  final double? margenBu;
  final double? desnivelHombrosBu;
  final double? desviacionNarizBu;

  factory Repeticion.desdeJson(Map<String, dynamic> json) => Repeticion(
        numero: json['numero'] as int,
        valida: json['valida'] as bool? ?? false,
        truncada: json['truncada'] as bool? ?? false,
        instanteS: _num(json['instante_s']),
        romBu: _num(json['rom_bu']),
        tSubidaS: _num(json['t_subida_s']),
        tBajadaS: _num(json['t_bajada_s']),
        ratioEccCon: _num(json['ratio_ecc_con']),
        vPicoConcentrica: _num(json['v_pico_concentrica']),
        margenBu: _num(json['margen_bu']),
        desnivelHombrosBu: _num(json['desnivel_hombros_bu']),
        desviacionNarizBu: _num(json['desviacion_nariz_bu']),
      );
}

/// La señal de altura y sus etiquetas de fase, para el gráfico.
class Senal {
  const Senal({required this.tiempoS, required this.alturaBu, required this.fases});

  final List<double?> tiempoS;
  final List<double?> alturaBu;

  /// +1 concéntrica, -1 excéntrica, 0 pausa.
  final List<double?> fases;

  factory Senal.desdeJson(Map<String, dynamic> json) => Senal(
        tiempoS: _lista(json['tiempo_s']),
        alturaBu: _lista(json['altura_bu']),
        fases: _lista(json['fases']),
      );

  bool get vacia => tiempoS.isEmpty || alturaBu.isEmpty;
}

/// Las referencias que hacen del gráfico una prueba y no un adorno.
class Referencias {
  const Referencias({this.barraYPx, this.barraBu, this.umbralBu, this.umbralVBuS});

  final double? barraYPx;

  /// La barra en la misma escala que la señal.
  final double? barraBu;

  /// Lo que la nariz tiene que superar para que la barbilla pase.
  final double? umbralBu;

  final double? umbralVBuS;

  factory Referencias.desdeJson(Map<String, dynamic> json) => Referencias(
        barraYPx: _num(json['barra_y_px']),
        barraBu: _num(json['barra_bu']),
        umbralBu: _num(json['umbral_bu']),
        umbralVBuS: _num(json['umbral_v_bu_s']),
      );
}

/// Métricas agregadas de la serie.
class ResumenSerie {
  const ResumenSerie({
    this.romMedioBu,
    this.romSdBu,
    this.tSubidaMediaS,
    this.tBajadaMediaS,
    this.ratioMedio,
    this.ratioSd,
    this.vPicoMedia,
    this.caidaVelocidad,
    this.caidaVelocidadPct,
    this.caidaVelocidadR2,
    this.desnivelHombrosMedioBu,
    this.desviacionNarizMediaBu,
  });

  final double? romMedioBu;
  final double? romSdBu;
  final double? tSubidaMediaS;
  final double? tBajadaMediaS;
  final double? ratioMedio;
  final double? ratioSd;
  final double? vPicoMedia;

  /// Pendiente en bu/s por repetición. Negativa = la serie se frena.
  final double? caidaVelocidad;
  final double? caidaVelocidadPct;

  /// Cuánto explica la recta. Con r² bajo la pendiente existe pero no describe
  /// nada, y la app no la enseña como si fuera fatiga.
  final double? caidaVelocidadR2;

  final double? desnivelHombrosMedioBu;
  final double? desviacionNarizMediaBu;

  /// Umbral por debajo del cual la caída de velocidad no se presenta como tal.
  static const double r2Minimo = 0.30;

  bool get caidaEsFiable =>
      caidaVelocidad != null &&
      caidaVelocidadR2 != null &&
      caidaVelocidadR2! >= r2Minimo;

  factory ResumenSerie.desdeJson(Map<String, dynamic> json) => ResumenSerie(
        romMedioBu: _num(json['rom_medio_bu']),
        romSdBu: _num(json['rom_sd_bu']),
        tSubidaMediaS: _num(json['t_subida_media_s']),
        tBajadaMediaS: _num(json['t_bajada_media_s']),
        ratioMedio: _num(json['ratio_medio']),
        ratioSd: _num(json['ratio_sd']),
        vPicoMedia: _num(json['v_pico_media']),
        caidaVelocidad: _num(json['caida_velocidad']),
        caidaVelocidadPct: _num(json['caida_velocidad_pct']),
        caidaVelocidadR2: _num(json['caida_velocidad_r2']),
        desnivelHombrosMedioBu: _num(json['desnivel_hombros_medio_bu']),
        desviacionNarizMediaBu: _num(json['desviacion_nariz_media_bu']),
      );
}

/// El análisis completo de una serie.
class Analisis {
  const Analisis({
    required this.jobId,
    required this.versionPipeline,
    required this.limitaciones,
    required this.nTotal,
    required this.nValidas,
    required this.nUsadas,
    required this.fps,
    required this.paso,
    required this.escalaPxBu,
    required this.recorridoBu,
    required this.referencias,
    required this.resumen,
    required this.repeticiones,
    required this.senal,
    required this.keypoints,
    this.videoAnotadoUrl,
  });

  final String jobId;

  /// Identifica CÓMO se midió. Dos series con versiones distintas no son
  /// comparables aunque los números se parezcan.
  final String versionPipeline;

  final String limitaciones;
  final int nTotal;
  final int nValidas;
  final int nUsadas;
  final double? fps;
  final int? paso;
  final double? escalaPxBu;
  final double? recorridoBu;
  final Referencias referencias;
  final ResumenSerie resumen;
  final List<Repeticion> repeticiones;
  final Senal senal;

  /// `(n, 33, 2)`. Es el dataset: el vídeo ya no existe en el servidor, así que
  /// si esto no se guarda aquí, no está en ninguna parte.
  final List<dynamic> keypoints;

  final String? videoAnotadoUrl;

  factory Analisis.desdeJson(Map<String, dynamic> json) {
    final captura = (json['captura'] as Map?)?.cast<String, dynamic>() ?? {};
    final conteo = (json['conteo'] as Map?)?.cast<String, dynamic>() ?? {};
    return Analisis(
      jobId: json['job_id'] as String? ?? '',
      versionPipeline: json['version_pipeline'] as String? ?? 'desconocida',
      limitaciones: json['limitaciones'] as String? ?? '',
      nTotal: conteo['n_total'] as int? ?? 0,
      nValidas: conteo['n_validas'] as int? ?? 0,
      nUsadas: conteo['n_usadas'] as int? ?? 0,
      fps: _num(captura['fps']),
      paso: captura['paso'] as int?,
      escalaPxBu: _num(captura['escala_px_bu']),
      recorridoBu: _num(captura['recorrido_bu']),
      referencias: Referencias.desdeJson(
          (json['referencias'] as Map?)?.cast<String, dynamic>() ?? {}),
      resumen: ResumenSerie.desdeJson(
          (json['serie'] as Map?)?.cast<String, dynamic>() ?? {}),
      repeticiones: ((json['repeticiones'] as List?) ?? const [])
          .map((r) => Repeticion.desdeJson((r as Map).cast<String, dynamic>()))
          .toList(growable: false),
      senal: Senal.desdeJson((json['senal'] as Map?)?.cast<String, dynamic>() ?? {}),
      keypoints: (json['keypoints'] as List?) ?? const [],
      videoAnotadoUrl: json['video_anotado_url'] as String?,
    );
  }
}

/// Un fallo que el usuario puede arreglar.
class FalloAnalisis implements Exception {
  const FalloAnalisis({
    required this.codigo,
    required this.titulo,
    required this.instruccion,
    required this.reintentable,
  });

  final String codigo;
  final String titulo;

  /// Qué hacer distinto. Siempre una acción, nunca un diagnóstico.
  final String instruccion;

  final bool reintentable;

  factory FalloAnalisis.desdeJson(Map<String, dynamic> json) => FalloAnalisis(
        codigo: json['codigo'] as String? ?? 'DESCONOCIDO',
        titulo: json['titulo'] as String? ?? 'No se pudo analizar el vídeo',
        instruccion: json['instruccion'] as String? ?? '',
        reintentable: json['reintentable'] as bool? ?? true,
      );

  static const red = FalloAnalisis(
    codigo: 'SIN_RED',
    titulo: 'No se pudo conectar',
    instruccion:
        'El análisis se hace en el servidor. Comprueba la conexión y vuelve a '
        'intentarlo: el vídeo sigue guardado en el móvil.',
    reintentable: true,
  );

  static const direccion = FalloAnalisis(
    codigo: 'DIRECCION_INVALIDA',
    titulo: 'La dirección del servidor no responde bien',
    instruccion:
        'Se llegó a algo, pero no era el análisis de cAI-listhenics. Revisa la '
        'dirección: tiene que incluir http:// y el puerto, por ejemplo '
        'http://140.238.1.2:8000',
    reintentable: false,
  );

  @override
  String toString() => '$codigo: $titulo';
}
