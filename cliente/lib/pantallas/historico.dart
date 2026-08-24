/// El histórico: para qué se guarda rep a rep.
///
/// Tres progresiones y una advertencia. La advertencia es la parte que casi
/// nadie pondría y sin la cual el resto engaña: si la anchura de hombros en
/// píxeles cambia mucho entre sesiones, lo que cambió fue la distancia a la
/// cámara, no el atleta. Todas las métricas están en anchuras de hombros, así
/// que una cámara más lejos "mejora" el recorrido sin que nadie haya mejorado.
library;

import 'dart:io';

import 'package:flutter/material.dart';

import '../datos/almacen.dart';
import '../modelo/analisis.dart';
import '../widgets/comunes.dart';
import '../widgets/graficos.dart';
import 'resultado.dart';

/// Por encima de esta variación relativa en la escala biacromial, se avisa.
const double variacionEscalaMaxima = 0.15;

class PantallaHistorico extends StatelessWidget {
  const PantallaHistorico({
    super.key,
    required this.series,
    required this.alBorrar,
    required this.alRecargar,
    this.usuarioActivo,
    this.alAbrirPerfil,
    this.alAbrirSerie,
  });

  /// De la más nueva a la más vieja, como sale del almacén.
  final List<SerieGuardada> series;

  final void Function(SerieGuardada) alBorrar;
  final Future<void> Function() alRecargar;
  final Usuario? usuarioActivo;
  final VoidCallback? alAbrirPerfil;
  final void Function(SerieGuardada)? alAbrirSerie;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);

    // Los gráficos se leen de viejo a nuevo; la lista, de nuevo a viejo.
    final cronologicas = series.reversed.toList(growable: false);
    final versiones = series.map((s) => s.versionPipeline).toSet();
    final aviso = _avisoDeEscala(cronologicas);

    return RefreshIndicator(
      onRefresh: alRecargar,
      child: ListView(
        padding: const EdgeInsets.only(bottom: 24),
        children: [
          // Banner principal de la App
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: ClipRRect(
              borderRadius: BorderRadius.circular(16),
              child: Stack(
                alignment: Alignment.bottomLeft,
                children: [
                  Image.asset(
                    'assets/images/banner.jpeg',
                    height: 125,
                    width: double.infinity,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => const SizedBox.shrink(),
                  ),
                  Container(
                    height: 125,
                    decoration: const BoxDecoration(
                      gradient: LinearGradient(
                        begin: Alignment.topCenter,
                        end: Alignment.bottomCenter,
                        colors: [Colors.transparent, Colors.black87],
                      ),
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.all(12),
                    child: Row(
                      children: [
                        ClipRRect(
                          borderRadius: BorderRadius.circular(12),
                          child: Image.asset(
                            'assets/images/logo.jpg',
                            width: 36,
                            height: 36,
                            fit: BoxFit.cover,
                            errorBuilder: (_, __, ___) => const Icon(Icons.fitness_center, color: Colors.white),
                          ),
                        ),
                        const SizedBox(width: 10),
                        const Text(
                          'cAI-listhenics',
                          style: TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.bold,
                            fontSize: 20,
                            shadows: [Shadow(blurRadius: 4, color: Colors.black)],
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),

          // Cabecera de perfil de usuario
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: Card(
              color: tema.colorScheme.surfaceContainerHigh,
              child: ListTile(
                leading: ClipRRect(
                  borderRadius: BorderRadius.circular(20),
                  child: Image.asset(
                    'assets/images/logo.jpg',
                    width: 40,
                    height: 40,
                    fit: BoxFit.cover,
                    errorBuilder: (_, __, ___) => CircleAvatar(
                      backgroundColor: tema.colorScheme.primary,
                      child: Text(
                        usuarioActivo != null
                            ? (usuarioActivo!.nombre ?? usuarioActivo!.username)[0].toUpperCase()
                            : 'U',
                        style: TextStyle(color: tema.colorScheme.onPrimary, fontWeight: FontWeight.bold),
                      ),
                    ),
                  ),
                ),
                title: Text(
                  usuarioActivo != null
                      ? (usuarioActivo!.nombre ?? '@${usuarioActivo!.username}')
                      : 'Usuario local',
                  style: const TextStyle(fontWeight: FontWeight.w600),
                ),
                subtitle: Text(
                  usuarioActivo != null ? '@${usuarioActivo!.username} · ${series.length} series' : '${series.length} series guardadas',
                ),
                trailing: TextButton.icon(
                  onPressed: alAbrirPerfil,
                  icon: const Icon(Icons.person_search, size: 18),
                  label: const Text('Perfil'),
                ),
              ),
            ),
          ),

          if (series.isEmpty)
            Padding(
              padding: const EdgeInsets.all(48),
              child: Text(
                'Aún no hay series guardadas.\nGraba una y aparecerá aquí.',
                textAlign: TextAlign.center,
                style: tema.textTheme.bodyMedium
                    ?.copyWith(color: tema.colorScheme.outline),
              ),
            )
          else ...[
            if (aviso != null) Aviso(texto: aviso, icono: Icons.straighten),

            if (versiones.length > 1)
              const Aviso(
                texto:
                    'Hay series medidas con versiones distintas del análisis. Los '
                    'números no son comparables entre ellas: la progresión que se '
                    've puede ser un cambio de método, no del atleta.',
                icono: Icons.rule,
              ),

            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
              child: GraficoProgresion(
                titulo: 'Ratio excéntrica / concéntrica',
                series: cronologicas,
                valorDe: (s) => s.ratioMedio,
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 24, 16, 0),
              child: GraficoProgresion(
                titulo: 'Recorrido medio (anchuras de hombros)',
                series: cronologicas,
                valorDe: (s) => s.romMedio,
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 24, 16, 0),
              child: GraficoProgresion(
                titulo: 'Caída de velocidad (bu/s por repetición)',
                series: cronologicas,
                valorDe: (s) => s.caidaVelocidad,
                decimales: 3,
              ),
            ),

            Padding(
              padding: const EdgeInsets.fromLTRB(16, 28, 16, 8),
              child: Text('Sesiones', style: tema.textTheme.titleMedium),
            ),
            for (final serie in series)
              _Fila(
                serie: serie,
                alBorrar: alBorrar,
                alAbrirSerie: alAbrirSerie,
              ),
          ],
        ],
      ),
    );
  }

  String? _avisoDeEscala(List<SerieGuardada> cronologicas) {
    final escalas = cronologicas
        .map((s) => s.escalaPxBu)
        .whereType<double>()
        .where((e) => e > 0)
        .toList();
    if (escalas.length < 2) return null;

    final ultima = escalas.last;
    final anteriores = escalas.sublist(0, escalas.length - 1)..sort();
    final mediana = anteriores.length.isOdd
        ? anteriores[anteriores.length ~/ 2]
        : (anteriores[anteriores.length ~/ 2 - 1] +
                anteriores[anteriores.length ~/ 2]) /
            2;
    if (mediana <= 0) return null;

    final variacion = (ultima - mediana).abs() / mediana;
    if (variacion <= variacionEscalaMaxima) return null;

    return 'La anchura de hombros medida ha cambiado un '
        '${(variacion * 100).toStringAsFixed(0)} % respecto a las sesiones '
        'anteriores (${mediana.toStringAsFixed(0)} px → '
        '${ultima.toStringAsFixed(0)} px). Todas las métricas se miden en '
        'anchuras de hombros, así que eso normalmente significa que la cámara '
        'estaba a otra distancia o girada, no que hayas progresado. Compara con '
        'cuidado.';
  }
}

class _Fila extends StatelessWidget {
  const _Fila({
    required this.serie,
    required this.alBorrar,
    this.alAbrirSerie,
  });

  final SerieGuardada serie;
  final void Function(SerieGuardada) alBorrar;
  final void Function(SerieGuardada)? alAbrirSerie;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final fecha = serie.fechaUtc.toLocal();
    final dia = '${fecha.day.toString().padLeft(2, '0')}/'
        '${fecha.month.toString().padLeft(2, '0')}/${fecha.year}';
    final hora = '${fecha.hour.toString().padLeft(2, '0')}:'
        '${fecha.minute.toString().padLeft(2, '0')}';

    final tieneVideo = serie.videoAnotadoPath != null &&
        File(serie.videoAnotadoPath!).existsSync();

    return Dismissible(
      key: ValueKey(serie.id),
      direction: DismissDirection.endToStart,
      background: Container(
        alignment: Alignment.centerRight,
        padding: const EdgeInsets.only(right: 20),
        color: tema.colorScheme.errorContainer,
        child: Icon(Icons.delete_outline, color: tema.colorScheme.onErrorContainer),
      ),
      confirmDismiss: (_) async =>
          await showDialog<bool>(
            context: context,
            builder: (contexto) => AlertDialog(
              title: const Text('Borrar esta serie'),
              content: const Text(
                'Se borran la serie, sus repeticiones, sus keypoints y su vídeo local. '
                'No se puede deshacer.',
              ),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(contexto, false),
                    child: const Text('Cancelar')),
                FilledButton(
                    onPressed: () => Navigator.pop(contexto, true),
                    child: const Text('Borrar')),
              ],
            ),
          ) ??
          false,
      onDismissed: (_) => alBorrar(serie),
      child: ListTile(
        onTap: alAbrirSerie != null ? () => alAbrirSerie!(serie) : null,
        leading: Icon(
          tieneVideo ? Icons.play_circle_fill : Icons.analytics_outlined,
          color: tieneVideo ? const Color(0xFF2F6FED) : tema.colorScheme.outline,
          size: 32,
        ),
        title: Text('${serie.nTotal} dominadas · ${serie.nValidas} válidas'),
        subtitle: Text(
          '$dia $hora · ratio ${cifra(serie.ratioMedio)} · '
          'ROM ${cifra(serie.romMedio, sufijo: ' bu')}',
        ),
        trailing: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              cifra(serie.caidaVelocidad, decimales: 3),
              style: tema.textTheme.labelMedium?.copyWith(
                color: (serie.caidaVelocidad ?? 0) < 0
                    ? tema.colorScheme.error
                    : tema.colorScheme.outline,
              ),
            ),
            const SizedBox(width: 4),
            const Icon(Icons.chevron_right, size: 20),
          ],
        ),
      ),
    );
  }
}
