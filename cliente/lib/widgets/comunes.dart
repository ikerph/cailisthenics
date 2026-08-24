/// Piezas que se repiten por toda la app.
library;

import 'package:flutter/material.dart';

/// El banner de limitaciones. Siempre visible, nunca plegado.
///
/// No es letra pequeña ni un descargo legal: es parte del resultado. Quien lee
/// "12 dominadas" tiene que leer a la vez con qué se han medido, porque la
/// nariz no es la barbilla y la diferencia se la puede estar comiendo él.
/// Esconderlo detrás de un "ver más" sería lo mismo que no ponerlo.
class BannerLimitaciones extends StatelessWidget {
  const BannerLimitaciones({super.key, required this.texto});

  final String texto;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      color: tema.colorScheme.secondaryContainer,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.info_outline,
              size: 18, color: tema.colorScheme.onSecondaryContainer),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              texto,
              style: tema.textTheme.bodySmall?.copyWith(
                color: tema.colorScheme.onSecondaryContainer,
                height: 1.35,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// Un aviso que no es un error: algo que mirar antes de creerse el número.
class Aviso extends StatelessWidget {
  const Aviso({super.key, required this.texto, this.icono = Icons.warning_amber_rounded});

  final String texto;
  final IconData icono;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: tema.colorScheme.tertiaryContainer,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icono, size: 20, color: tema.colorScheme.onTertiaryContainer),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              texto,
              style: tema.textTheme.bodySmall
                  ?.copyWith(color: tema.colorScheme.onTertiaryContainer, height: 1.35),
            ),
          ),
        ],
      ),
    );
  }
}

/// Un fallo con su instrucción. Nunca un código de error a pelo.
class PanelFallo extends StatelessWidget {
  const PanelFallo({
    super.key,
    required this.titulo,
    required this.instruccion,
    this.alReintentar,
    this.accionExtra,
    this.etiquetaExtra,
  });

  final String titulo;
  final String instruccion;
  final VoidCallback? alReintentar;

  /// Segunda salida cuando reintentar no basta: por ejemplo, cambiar el
  /// servidor cuando el móvil no llega al portátil.
  final VoidCallback? accionExtra;
  final String? etiquetaExtra;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.videocam_off_outlined, size: 48, color: tema.colorScheme.error),
            const SizedBox(height: 16),
            Text(titulo,
                style: tema.textTheme.titleMedium, textAlign: TextAlign.center),
            const SizedBox(height: 8),
            Text(instruccion,
                style: tema.textTheme.bodyMedium, textAlign: TextAlign.center),
            if (alReintentar != null) ...[
              const SizedBox(height: 24),
              FilledButton.icon(
                onPressed: alReintentar,
                icon: const Icon(Icons.refresh),
                label: const Text('Volver a grabar'),
              ),
            ],
            if (accionExtra != null) ...[
              const SizedBox(height: 8),
              TextButton(
                onPressed: accionExtra,
                child: Text(etiquetaExtra ?? 'Más opciones'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// Un número con su etiqueta, para las tarjetas de resumen.
class Cifra extends StatelessWidget {
  const Cifra({super.key, required this.valor, required this.etiqueta, this.pie});

  final String valor;
  final String etiqueta;
  final String? pie;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(valor, style: tema.textTheme.headlineSmall),
        Text(etiqueta, style: tema.textTheme.bodySmall),
        if (pie != null)
          Text(pie!,
              style: tema.textTheme.labelSmall
                  ?.copyWith(color: tema.colorScheme.outline)),
      ],
    );
  }
}

/// Formatea un número que puede no existir. Nunca un 0 donde había un hueco.
String cifra(double? valor, {int decimales = 2, String sufijo = ''}) =>
    valor == null ? '—' : '${valor.toStringAsFixed(decimales)}$sufijo';
