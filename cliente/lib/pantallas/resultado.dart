/// El resultado de una serie: el número, la prueba y las limitaciones.
///
/// El orden de la pantalla es deliberado. Primero el contador, que es lo que la
/// gente busca. Justo debajo el gráfico con la barra y el umbral, que es la
/// PRUEBA de por qué contó lo que contó: si la línea naranja no cae sobre la
/// barra que se ve en el vídeo, la medida está mal y el número no vale. Y el
/// banner de limitaciones fijo, no al final, porque nadie llega al final.
library;

import 'dart:io';

import 'package:flutter/material.dart';

import '../modelo/analisis.dart';
import '../widgets/comunes.dart';
import '../widgets/graficos.dart';
import '../widgets/reproductor.dart';

class PantallaResultado extends StatelessWidget {
  const PantallaResultado({
    super.key,
    required this.analisis,
    required this.alGuardar,
    required this.alDescartar,
    this.guardada = false,
    this.videoAnotadoFichero,
  });

  final Analisis analisis;
  final VoidCallback alGuardar;
  final VoidCallback alDescartar;
  final bool guardada;
  final File? videoAnotadoFichero;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final resumen = analisis.resumen;

    final tieneVideoFichero = videoAnotadoFichero != null && videoAnotadoFichero!.existsSync();
    final tieneVideoUrl = analisis.videoAnotadoUrl != null && analisis.videoAnotadoUrl!.isNotEmpty;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Serie analizada'),
        actions: [
          if (!guardada)
            TextButton(onPressed: alDescartar, child: const Text('Descartar')),
        ],
      ),
      // El banner vive fuera del scroll: no se puede dejar atrás.
      bottomNavigationBar: BannerLimitaciones(texto: analisis.limitaciones),
      floatingActionButton: guardada
          ? null
          : FloatingActionButton.extended(
              onPressed: alGuardar,
              icon: const Icon(Icons.save_outlined),
              label: const Text('Guardar serie'),
            ),
      body: ListView(
        padding: const EdgeInsets.only(bottom: 88),
        children: [
          _Contador(analisis: analisis),

          if (tieneVideoFichero || tieneVideoUrl)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: ReproductorVideo(
                fichero: tieneVideoFichero ? videoAnotadoFichero : null,
                url: !tieneVideoFichero && tieneVideoUrl ? analisis.videoAnotadoUrl : null,
                titulo: 'Vídeo con trackpoints de tu serie',
              ),
            ),

          if (analisis.nTotal != analisis.nValidas)
            const Aviso(
              texto:
                  'Las repeticiones que no cuentan como válidas no llegaron a '
                  'pasar el umbral. El número de repeticiones es firme; el de '
                  'válidas es conservador: con el modelo ligero la nariz sale '
                  'un poco más abajo de lo real y se lleva por delante las que '
                  'pasan la barra por poco.',
            ),

          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: GraficoSenal(
              senal: analisis.senal,
              referencias: analisis.referencias,
              repeticiones: analisis.repeticiones,
            ),
          ),

          const _Titulo('Tempo y recorrido'),
          _Resumen(resumen: resumen, nUsadas: analisis.nUsadas, nTotal: analisis.nTotal),

          const _Titulo('Caída de velocidad'),
          _Caida(resumen: resumen),

          const _Titulo('Simetría'),
          _Simetria(resumen: resumen),

          const _Titulo('Repetición a repetición'),
          _Tabla(repeticiones: analisis.repeticiones),

          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              'Medido con ${analisis.versionPipeline}. Las series con distinta '
              'versión no son comparables entre sí.',
              style: tema.textTheme.labelSmall
                  ?.copyWith(color: tema.colorScheme.outline),
            ),
          ),
        ],
      ),
    );
  }
}

class _Titulo extends StatelessWidget {
  const _Titulo(this.texto);
  final String texto;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 24, 16, 8),
        child: Text(texto, style: Theme.of(context).textTheme.titleMedium),
      );
}

class _Contador extends StatelessWidget {
  const _Contador({required this.analisis});
  final Analisis analisis;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text('${analisis.nTotal}',
              style: tema.textTheme.displayMedium
                  ?.copyWith(fontWeight: FontWeight.w600)),
          const SizedBox(width: 8),
          Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Text('realizadas', style: tema.textTheme.titleSmall),
          ),
          const Spacer(),
          Text('${analisis.nValidas}',
              style: tema.textTheme.displaySmall?.copyWith(
                color: const Color(0xFF2E9E4F),
                fontWeight: FontWeight.w600,
              )),
          const SizedBox(width: 8),
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Text('válidas', style: tema.textTheme.titleSmall),
          ),
        ],
      ),
    );
  }
}

class _Resumen extends StatelessWidget {
  const _Resumen({required this.resumen, required this.nUsadas, required this.nTotal});

  final ResumenSerie resumen;
  final int nUsadas;
  final int nTotal;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 28,
            runSpacing: 16,
            children: [
              Cifra(
                valor: cifra(resumen.ratioMedio),
                etiqueta: 'ratio ecc/con',
                pie: resumen.ratioSd == null
                    ? null
                    : '± ${cifra(resumen.ratioSd)} entre repeticiones',
              ),
              Cifra(
                valor: cifra(resumen.tSubidaMediaS, sufijo: ' s'),
                etiqueta: 'subida',
              ),
              Cifra(
                valor: cifra(resumen.tBajadaMediaS, sufijo: ' s'),
                etiqueta: 'bajada',
              ),
              Cifra(
                valor: cifra(resumen.romMedioBu, sufijo: ' bu'),
                etiqueta: 'recorrido medio',
                pie: resumen.romSdBu == null ? null : '± ${cifra(resumen.romSdBu)}',
              ),
            ],
          ),
          if (nUsadas < nTotal)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                'Las medias usan $nUsadas de $nTotal repeticiones. Las que quedan '
                'pegadas al principio o al final del vídeo tienen la fase '
                'cortada, así que su duración es un mínimo y no una medida.',
                style: tema.textTheme.bodySmall
                    ?.copyWith(color: tema.colorScheme.outline),
              ),
            ),
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text(
              'Los tiempos son tiempo en movimiento: las pausas no cuentan en '
              'ninguna de las dos fases.',
              style: tema.textTheme.bodySmall
                  ?.copyWith(color: tema.colorScheme.outline),
            ),
          ),
        ],
      ),
    );
  }
}

class _Caida extends StatelessWidget {
  const _Caida({required this.resumen});
  final ResumenSerie resumen;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);

    // Sin r² suficiente la pendiente existe pero no describe nada: la serie no
    // se está frenando, va a saltos. Enseñarla como fatiga sería inventar.
    if (!resumen.caidaEsFiable) {
      return Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16),
        child: Text(
          resumen.caidaVelocidad == null
              ? 'Hacen falta al menos tres repeticiones medibles para estimar la '
                  'caída de velocidad.'
              : 'La velocidad de esta serie va a saltos: la recta explica solo el '
                  '${((resumen.caidaVelocidadR2 ?? 0) * 100).toStringAsFixed(0)} % '
                  'de la variación, así que no se puede llamar fatiga.',
          style: tema.textTheme.bodyMedium
              ?.copyWith(color: tema.colorScheme.outline),
        ),
      );
    }

    final pct = resumen.caidaVelocidadPct;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                pct == null ? '—' : '${pct.toStringAsFixed(0)} %',
                style: tema.textTheme.headlineMedium?.copyWith(
                  color: (pct ?? 0) < -10
                      ? tema.colorScheme.error
                      : tema.colorScheme.onSurface,
                ),
              ),
              const SizedBox(width: 10),
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: Text('de la primera a la última',
                    style: tema.textTheme.bodySmall),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Text(
            'Pendiente ${cifra(resumen.caidaVelocidad, decimales: 3)} bu/s por '
            'repetición (r² ${cifra(resumen.caidaVelocidadR2)}). Es la métrica '
            'que un contador de repeticiones no da: mide cuánto se frena la '
            'serie, no cuántas salieron.',
            style: tema.textTheme.bodySmall
                ?.copyWith(color: tema.colorScheme.outline),
          ),
        ],
      ),
    );
  }
}

class _Simetria extends StatelessWidget {
  const _Simetria({required this.resumen});
  final ResumenSerie resumen;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 28,
            runSpacing: 16,
            children: [
              Cifra(
                valor: cifra(resumen.desnivelHombrosMedioBu, sufijo: ' bu'),
                etiqueta: 'desnivel de hombros',
                pie: 'positivo = izquierda de la imagen más alta',
              ),
              Cifra(
                valor: cifra(resumen.desviacionNarizMediaBu, sufijo: ' bu'),
                etiqueta: 'desvío lateral',
                pie: 'nariz respecto al centro de las manos',
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            'Es lo único que la vista frontal mide mejor que la lateral: de '
            'perfil un hombro tapa al otro. Ojo, son coordenadas de la imagen: '
            'si el vídeo salió en espejo, izquierda y derecha están cambiadas.',
            style: tema.textTheme.bodySmall
                ?.copyWith(color: tema.colorScheme.outline),
          ),
        ],
      ),
    );
  }
}

class _Tabla extends StatelessWidget {
  const _Tabla({required this.repeticiones});
  final List<Repeticion> repeticiones;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: DataTable(
        columnSpacing: 22,
        headingRowHeight: 36,
        dataRowMinHeight: 36,
        dataRowMaxHeight: 44,
        columns: const [
          DataColumn(label: Text('#')),
          DataColumn(label: Text('ROM'), numeric: true),
          DataColumn(label: Text('sube'), numeric: true),
          DataColumn(label: Text('baja'), numeric: true),
          DataColumn(label: Text('ratio'), numeric: true),
          DataColumn(label: Text('v pico'), numeric: true),
          DataColumn(label: Text('')),
        ],
        rows: [
          for (final r in repeticiones)
            DataRow(cells: [
              DataCell(Text('${r.numero}')),
              DataCell(Text(cifra(r.romBu))),
              DataCell(Text(cifra(r.tSubidaS))),
              DataCell(Text(cifra(r.tBajadaS))),
              DataCell(Text(cifra(r.ratioEccCon))),
              DataCell(Text(cifra(r.vPicoConcentrica))),
              DataCell(Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    r.valida ? Icons.check_circle : Icons.remove_circle_outline,
                    size: 16,
                    color: r.valida ? const Color(0xFF2E9E4F) : tema.colorScheme.error,
                  ),
                  if (r.truncada)
                    Padding(
                      padding: const EdgeInsets.only(left: 4),
                      child: Tooltip(
                        message: 'La fase toca el borde del vídeo: la duración '
                            'es un mínimo. No entra en las medias.',
                        child: Icon(Icons.content_cut,
                            size: 14, color: tema.colorScheme.outline),
                      ),
                    ),
                ],
              )),
            ]),
        ],
      ),
    );
  }
}
