/// Tests de widget del cliente.
///
/// Aquí no se prueba la cámara ni la red: las dos necesitan un dispositivo. Se
/// prueba lo que sí se puede romper sin darse cuenta y no salta en el
/// analizador: que el JSON del backend se lea bien, y que las dos piezas que
/// nunca deben desaparecer de la pantalla de resultado sigan ahí.
library;

import 'package:cai_listhenics/datos/almacen.dart';
import 'package:cai_listhenics/modelo/analisis.dart';
import 'package:cai_listhenics/pantallas/resultado.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Una respuesta del backend, con los `null` que manda de verdad donde el
/// pipeline dio NaN.
Map<String, dynamic> respuestaDeEjemplo() => {
      'job_id': 'abc',
      'version_pipeline': 'm1-nariz-lite-p2-margen0.40-corte3.0',
      'limitaciones': 'Se sigue la nariz, no la barbilla: ...',
      'video_anotado_url': null,
      'captura': {'fps': 30.0, 'paso': 2, 'escala_px_bu': 50.1, 'recorrido_bu': 2.14},
      'referencias': {
        'barra_y_px': 120.0,
        'barra_bu': 1.5,
        'umbral_bu': 1.7,
        'umbral_v_bu_s': 0.35,
      },
      'conteo': {'n_total': 3, 'n_validas': 2, 'n_usadas': 2},
      'serie': {
        'rom_medio_bu': 2.0,
        'rom_sd_bu': null, // una sola repetición usable: no hay dispersión
        't_subida_media_s': 0.9,
        't_bajada_media_s': 0.65,
        'ratio_medio': 0.72,
        'ratio_sd': 0.05,
        'v_pico_media': 3.4,
        'caida_velocidad': -0.06,
        'caida_velocidad_pct': -18.0,
        'caida_velocidad_r2': 0.71,
        'desnivel_hombros_medio_bu': 0.02,
        'desviacion_nariz_media_bu': -0.03,
      },
      'repeticiones': [
        {
          'numero': 1,
          'instante_s': 8.0,
          'rom_bu': 2.0,
          't_subida_s': 0.9,
          't_bajada_s': 0.65,
          'ratio_ecc_con': 0.72,
          'v_pico_concentrica': 3.5,
          'margen_bu': 0.3,
          'valida': true,
          'truncada': false,
        },
        {
          'numero': 2,
          'instante_s': 10.7,
          'rom_bu': 1.9,
          't_subida_s': null, // fase sin medir
          't_bajada_s': null,
          'ratio_ecc_con': null,
          'v_pico_concentrica': 3.3,
          'margen_bu': -0.1,
          'valida': false,
          'truncada': true,
        },
      ],
      'senal': {
        'tiempo_s': [0.0, 0.1, 0.2, 0.3],
        'altura_bu': [0.0, 1.0, 2.0, 0.5],
        'fases': [0, 1, 0, -1],
      },
      'keypoints': <dynamic>[],
    };

void main() {
  test('los null del backend no se convierten en ceros', () {
    final analisis = Analisis.desdeJson(respuestaDeEjemplo());

    expect(analisis.nTotal, 3);
    expect(analisis.nValidas, 2);

    // Lo que importa: un hueco sigue siendo un hueco. Si esto fuese 0, la app
    // enseñaría una dispersión nula donde no hay dato, y un ratio de cero en
    // una repetición que simplemente no se pudo medir.
    expect(analisis.resumen.romSdBu, isNull);
    expect(analisis.repeticiones[1].ratioEccCon, isNull);
    expect(analisis.repeticiones[1].tSubidaS, isNull);

    expect(analisis.repeticiones[0].ratioEccCon, 0.72);
    expect(analisis.repeticiones[1].truncada, isTrue);
  });

  test('la caída de velocidad solo es fiable con r2 suficiente', () {
    final bueno = ResumenSerie.desdeJson({
      'caida_velocidad': -0.06,
      'caida_velocidad_r2': 0.71,
    });
    expect(bueno.caidaEsFiable, isTrue);

    // Una serie que va a saltos tiene pendiente, pero llamarla fatiga sería
    // inventar: la recta no describe nada.
    final saltos = ResumenSerie.desdeJson({
      'caida_velocidad': -0.11,
      'caida_velocidad_r2': 0.09,
    });
    expect(saltos.caidaEsFiable, isFalse);

    // Sin suficientes repeticiones no hay pendiente en absoluto.
    final pocas = ResumenSerie.desdeJson({});
    expect(pocas.caidaEsFiable, isFalse);
  });

  testWidgets('el resultado enseña el contador y el banner de limitaciones',
      (tester) async {
    final analisis = Analisis.desdeJson(respuestaDeEjemplo());
    await tester.pumpWidget(MaterialApp(
      home: PantallaResultado(
        analisis: analisis,
        alGuardar: () {},
        alDescartar: () {},
      ),
    ));

    expect(find.text('3'), findsWidgets); // realizadas
    expect(find.text('realizadas'), findsOneWidget);
    expect(find.text('válidas'), findsOneWidget);

    // El banner no es letra pequeña: es parte del resultado y vive fuera del
    // scroll para que no se pueda dejar atrás. Si alguien lo mueve dentro de
    // la lista, este test se cae.
    expect(find.textContaining('Se sigue la nariz'), findsOneWidget);
  });

  testWidgets('una repetición sin medir sale como hueco, no como cero',
      (tester) async {
    final analisis = Analisis.desdeJson(respuestaDeEjemplo());
    await tester.pumpWidget(MaterialApp(
      home: PantallaResultado(
        analisis: analisis,
        alGuardar: () {},
        alDescartar: () {},
      ),
    ));

    await tester.scrollUntilVisible(find.byType(DataTable), 300);
    expect(find.text('—'), findsWidgets);
  });

  test('el parser de DDL ignora punto y coma dentro de comentarios', () {
    const ddlFalso = '''
-- comentario con punto y coma; no debe romper nada
CREATE TABLE foo (id INT); -- otro comentario; ignorado
PRAGMA journal_mode = WAL;
CREATE TABLE bar (name TEXT);
''';
    final sentencias = Almacen.sentenciasParaPruebas(ddlFalso).toList();
    expect(sentencias.length, 2);
    expect(sentencias[0], 'CREATE TABLE foo (id INT)');
    expect(sentencias[1], 'CREATE TABLE bar (name TEXT)');
  });
}
