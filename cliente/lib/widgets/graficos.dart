/// Gráficos a mano con `CustomPainter`.
///
/// Sin librería de charts a propósito: lo que hace falta son dos dibujos muy
/// concretos -una señal con dos líneas de referencia, y una progresión con
/// puntos- y una dependencia de terceros costaría más en configuración que
/// estos doscientos renglones. Además hay un requisito que ninguna librería
/// generalista respeta bien: la línea de la barra y la del umbral tienen que
/// verse SIEMPRE, aunque caigan fuera del rango de la señal, porque son lo que
/// explica por qué una repetición contó como válida.
library;

import 'dart:math';

import 'package:flutter/material.dart';

import '../datos/almacen.dart';
import '../modelo/analisis.dart';

/// La señal de altura de la nariz, con la barra y el umbral marcados.
class GraficoSenal extends StatelessWidget {
  const GraficoSenal({
    super.key,
    required this.senal,
    required this.referencias,
    required this.repeticiones,
    this.alto = 220,
  });

  final Senal senal;
  final Referencias referencias;
  final List<Repeticion> repeticiones;
  final double alto;

  @override
  Widget build(BuildContext context) {
    if (senal.vacia) return const SizedBox.shrink();
    final tema = Theme.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          height: alto,
          width: double.infinity,
          child: CustomPaint(
            painter: _PintorSenal(
              senal: senal,
              referencias: referencias,
              repeticiones: repeticiones,
              colorSenal: tema.colorScheme.primary,
              colorBarra: const Color(0xFFEF8A17),
              colorUmbral: tema.colorScheme.error,
              colorEje: tema.colorScheme.outlineVariant,
              colorTexto: tema.colorScheme.onSurfaceVariant,
            ),
          ),
        ),
        const SizedBox(height: 8),
        Wrap(
          spacing: 16,
          runSpacing: 4,
          children: [
            _Leyenda(color: tema.colorScheme.primary, texto: 'Altura de la nariz'),
            const _Leyenda(color: Color(0xFFEF8A17), texto: 'Barra'),
            _Leyenda(
                color: tema.colorScheme.error,
                texto: 'Umbral de barbilla sobre barra'),
          ],
        ),
      ],
    );
  }
}

class _Leyenda extends StatelessWidget {
  const _Leyenda({required this.color, required this.texto});
  final Color color;
  final String texto;

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(width: 14, height: 3, color: color),
          const SizedBox(width: 6),
          Text(texto, style: Theme.of(context).textTheme.labelSmall),
        ],
      );
}

class _PintorSenal extends CustomPainter {
  _PintorSenal({
    required this.senal,
    required this.referencias,
    required this.repeticiones,
    required this.colorSenal,
    required this.colorBarra,
    required this.colorUmbral,
    required this.colorEje,
    required this.colorTexto,
  });

  final Senal senal;
  final Referencias referencias;
  final List<Repeticion> repeticiones;
  final Color colorSenal, colorBarra, colorUmbral, colorEje, colorTexto;

  static const _margenIzq = 34.0;
  static const _margenAbajo = 20.0;
  static const _margenArriba = 8.0;

  @override
  void paint(Canvas lienzo, Size medida) {
    final tiempos = <double>[];
    final alturas = <double>[];
    for (var i = 0; i < senal.tiempoS.length && i < senal.alturaBu.length; i++) {
      final t = senal.tiempoS[i];
      final a = senal.alturaBu[i];
      if (t == null || a == null) continue;
      tiempos.add(t);
      alturas.add(a);
    }
    if (tiempos.length < 2) return;

    final t0 = tiempos.first;
    final t1 = tiempos.last;

    // El rango vertical incluye la barra y el umbral aunque la señal no llegue
    // a ellos: si el umbral se sale del gráfico, el gráfico deja de explicar
    // por qué una repetición no valió.
    var minY = alturas.reduce(min);
    var maxY = alturas.reduce(max);
    for (final referencia in [referencias.barraBu, referencias.umbralBu]) {
      if (referencia == null) continue;
      minY = min(minY, referencia);
      maxY = max(maxY, referencia);
    }
    final holgura = (maxY - minY) * 0.08 + 0.05;
    minY -= holgura;
    maxY += holgura;

    final ancho = medida.width - _margenIzq;
    final alto = medida.height - _margenAbajo - _margenArriba;
    if (ancho <= 0 || alto <= 0 || t1 <= t0 || maxY <= minY) return;

    double x(double t) => _margenIzq + (t - t0) / (t1 - t0) * ancho;
    double y(double v) => _margenArriba + (maxY - v) / (maxY - minY) * alto;

    // Ejes.
    final lapizEje = Paint()
      ..color = colorEje
      ..strokeWidth = 1;
    lienzo.drawLine(const Offset(_margenIzq, _margenArriba),
        Offset(_margenIzq, _margenArriba + alto), lapizEje);
    lienzo.drawLine(Offset(_margenIzq, _margenArriba + alto),
        Offset(medida.width, _margenArriba + alto), lapizEje);

    // Referencias, debajo de la señal para que no la tapen.
    _discontinua(lienzo, referencias.barraBu, y, medida, colorBarra);
    _discontinua(lienzo, referencias.umbralBu, y, medida, colorUmbral);

    // La señal.
    final trazo = Path()..moveTo(x(tiempos.first), y(alturas.first));
    for (var i = 1; i < tiempos.length; i++) {
      trazo.lineTo(x(tiempos[i]), y(alturas[i]));
    }
    lienzo.drawPath(
      trazo,
      Paint()
        ..color = colorSenal
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.8
        ..strokeJoin = StrokeJoin.round,
    );

    // Un punto por repetición, verde si valió y rojo si se quedó corta.
    for (final rep in repeticiones) {
      final t = rep.instanteS;
      if (t == null || t < t0 || t > t1) continue;
      final indice = _masCercano(tiempos, t);
      lienzo.drawCircle(
        Offset(x(tiempos[indice]), y(alturas[indice])),
        4,
        Paint()..color = rep.valida ? const Color(0xFF2E9E4F) : colorUmbral,
      );
      _texto(lienzo, '${rep.numero}', Offset(x(tiempos[indice]) - 4, y(alturas[indice]) - 22),
          colorTexto, 10);
    }

    // Escalas mínimas: sin números, un gráfico es una decoración.
    _texto(lienzo, maxY.toStringAsFixed(1), const Offset(2, _margenArriba), colorTexto, 10);
    _texto(lienzo, minY.toStringAsFixed(1),
        Offset(2, _margenArriba + alto - 12), colorTexto, 10);
    _texto(lienzo, '${(t1 - t0).toStringAsFixed(0)} s',
        Offset(medida.width - 30, _margenArriba + alto + 4), colorTexto, 10);
  }

  void _discontinua(
      Canvas lienzo, double? valor, double Function(double) y, Size medida, Color color) {
    if (valor == null) return;
    final altura = y(valor);
    final lapiz = Paint()
      ..color = color
      ..strokeWidth = 1.4;
    for (var px = _margenIzq; px < medida.width; px += 10) {
      lienzo.drawLine(Offset(px, altura), Offset(min(px + 6, medida.width), altura), lapiz);
    }
  }

  int _masCercano(List<double> tiempos, double objetivo) {
    var mejor = 0;
    var distancia = double.infinity;
    for (var i = 0; i < tiempos.length; i++) {
      final d = (tiempos[i] - objetivo).abs();
      if (d < distancia) {
        distancia = d;
        mejor = i;
      }
    }
    return mejor;
  }

  void _texto(Canvas lienzo, String texto, Offset donde, Color color, double tamano) {
    final pintor = TextPainter(
      text: TextSpan(text: texto, style: TextStyle(color: color, fontSize: tamano)),
      textDirection: TextDirection.ltr,
    )..layout();
    pintor.paint(lienzo, donde);
  }

  @override
  bool shouldRepaint(covariant _PintorSenal viejo) =>
      viejo.senal != senal || viejo.repeticiones != repeticiones;
}

/// Progresión de una métrica a lo largo de las sesiones.
class GraficoProgresion extends StatelessWidget {
  const GraficoProgresion({
    super.key,
    required this.titulo,
    required this.series,
    required this.valorDe,
    this.decimales = 2,
    this.alto = 140,
  });

  final String titulo;

  /// De la más vieja a la más nueva: es como se lee una progresión.
  final List<SerieGuardada> series;

  final double? Function(SerieGuardada) valorDe;
  final int decimales;
  final double alto;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final puntos = <MapEntry<DateTime, double>>[];
    for (final serie in series) {
      final valor = valorDe(serie);
      if (valor != null) puntos.add(MapEntry(serie.fechaUtc, valor));
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(titulo, style: tema.textTheme.titleSmall),
        const SizedBox(height: 6),
        if (puntos.length < 2)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(
              'Hacen falta al menos dos sesiones para ver una progresión.',
              style: tema.textTheme.bodySmall
                  ?.copyWith(color: tema.colorScheme.outline),
            ),
          )
        else
          SizedBox(
            height: alto,
            width: double.infinity,
            child: CustomPaint(
              painter: _PintorProgresion(
                puntos: puntos,
                color: tema.colorScheme.primary,
                colorEje: tema.colorScheme.outlineVariant,
                colorTexto: tema.colorScheme.onSurfaceVariant,
                decimales: decimales,
              ),
            ),
          ),
      ],
    );
  }
}

class _PintorProgresion extends CustomPainter {
  _PintorProgresion({
    required this.puntos,
    required this.color,
    required this.colorEje,
    required this.colorTexto,
    required this.decimales,
  });

  final List<MapEntry<DateTime, double>> puntos;
  final Color color, colorEje, colorTexto;
  final int decimales;

  @override
  void paint(Canvas lienzo, Size medida) {
    const margenIzq = 38.0;
    const margenAbajo = 16.0;
    final ancho = medida.width - margenIzq - 6;
    final alto = medida.height - margenAbajo - 8;
    if (ancho <= 0 || alto <= 0) return;

    final valores = puntos.map((p) => p.value).toList();
    var minY = valores.reduce(min);
    var maxY = valores.reduce(max);
    if ((maxY - minY).abs() < 1e-9) {
      minY -= 0.5;
      maxY += 0.5;
    }
    final holgura = (maxY - minY) * 0.12;
    minY -= holgura;
    maxY += holgura;

    // Reparto uniforme por orden, no por fecha: con sesiones muy separadas en
    // el tiempo, escalar por fecha amontona los puntos y no se lee nada.
    double x(int i) =>
        margenIzq + (puntos.length == 1 ? ancho / 2 : i / (puntos.length - 1) * ancho);
    double y(double v) => 8 + (maxY - v) / (maxY - minY) * alto;

    lienzo.drawLine(
      Offset(margenIzq, 8 + alto),
      Offset(medida.width - 6, 8 + alto),
      Paint()
        ..color = colorEje
        ..strokeWidth = 1,
    );

    final trazo = Path()..moveTo(x(0), y(valores.first));
    for (var i = 1; i < puntos.length; i++) {
      trazo.lineTo(x(i), y(valores[i]));
    }
    lienzo.drawPath(
      trazo,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
    for (var i = 0; i < puntos.length; i++) {
      lienzo.drawCircle(Offset(x(i), y(valores[i])), 3.5, Paint()..color = color);
    }

    _texto(lienzo, maxY.toStringAsFixed(decimales), const Offset(0, 4));
    _texto(lienzo, minY.toStringAsFixed(decimales), Offset(0, 8 + alto - 12));
  }

  void _texto(Canvas lienzo, String texto, Offset donde) {
    final pintor = TextPainter(
      text: TextSpan(text: texto, style: TextStyle(color: colorTexto, fontSize: 10)),
      textDirection: TextDirection.ltr,
    )..layout();
    pintor.paint(lienzo, donde);
  }

  @override
  bool shouldRepaint(covariant _PintorProgresion viejo) => viejo.puntos != puntos;
}
