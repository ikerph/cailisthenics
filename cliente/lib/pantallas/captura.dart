/// La pantalla que decide si la beta funciona.
///
/// Si el 30 % de los vídeos falla por encuadre, nadie escribe para decir por
/// qué: dejan de abrir la app. Por eso aquí hay tres barreras antes de gastar
/// una subida —checklist, guía en pantalla y validación de la grabación— y
/// ninguna es opcional.
library;

import 'dart:io';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';

import '../config.dart';

/// Lo que hay que cumplir antes de grabar.
///
/// Cada punto está aquí porque hay un fallo concreto del pipeline detrás, no
/// por completitud: son las cuatro causas de que un vídeo no se pueda analizar.
const List<({String texto, String porque})> comprobaciones = [
  (
    texto: 'Se te ve el cuerpo entero, de la cabeza a los pies',
    porque: 'La medida se hace en anchuras de hombros y necesita verlos siempre. '
        'Si te sales del encuadre a mitad de serie, el análisis se corta ahí.',
  ),
  (
    texto: 'La cámara está de frente, no de lado',
    porque: 'De perfil un hombro tapa al otro y no se puede medir la asimetría. '
        'De frente tampoco se mide la extensión de codo: eso no lo da esta vista.',
  ),
  (
    texto: 'No hay nadie más en el encuadre',
    porque: 'El modelo sigue a una sola persona. Si alguien pasa por detrás, '
        'puede saltar a esa persona a mitad de serie sin avisar.',
  ),
  (
    texto: 'La barra y tus manos se ven durante toda la serie',
    porque: 'La barra se deduce de la recta que une las dos muñecas. Sin manos '
        'visibles no hay referencia y no se puede decir qué repetición vale.',
  ),
];

class PantallaCaptura extends StatefulWidget {
  const PantallaCaptura({super.key, required this.alGrabar});

  /// Se llama con el vídeo listo para subir.
  final void Function(File video, Duration duracion) alGrabar;

  @override
  State<PantallaCaptura> createState() => _PantallaCapturaState();
}

class _PantallaCapturaState extends State<PantallaCaptura>
    with WidgetsBindingObserver {
  CameraController? _camara;
  String? _fallo;
  bool _grabando = false;
  DateTime? _iniciada;
  final Set<int> _marcadas = {};

  bool get _listoParaGrabar => _marcadas.length == comprobaciones.length;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _arrancarCamara();
  }

  /// Suelta la cámara al irse a segundo plano y la recupera al volver.
  ///
  /// Android se la quita al proceso cuando pierde el foco. Si el controlador
  /// se queda apuntando a una cámara que ya no es suya, la siguiente llamada
  /// revienta con un error de plataforma que llega como cierre de la app.
  @override
  void didChangeAppLifecycleState(AppLifecycleState estado) {
    final camara = _camara;
    if (camara == null || !camara.value.isInitialized) return;

    if (estado == AppLifecycleState.inactive) {
      // Si estaba grabando, se pierde la toma: mejor eso que un fichero a
      // medias que el usuario cree bueno.
      _camara = null;
      _grabando = false;
      camara.dispose();
      if (mounted) setState(() {});
    } else if (estado == AppLifecycleState.resumed) {
      _arrancarCamara();
    }
  }

  Future<void> _arrancarCamara() async {
    try {
      final camaras = await availableCameras();
      if (camaras.isEmpty) {
        setState(() => _fallo = 'Este dispositivo no tiene cámara disponible.');
        return;
      }
      final trasera = camaras.firstWhere(
        (c) => c.lensDirection == CameraLensDirection.back,
        orElse: () => camaras.first,
      );
      // veryHigh es 1080p. No se puede fijar 30 fps desde el plugin, así que
      // eso se pide en el checklist y se comprueba en el servidor.
      final controlador = CameraController(
        trasera,
        ResolutionPreset.veryHigh,
        enableAudio: false,
      );
      await controlador.initialize();
      if (!mounted) return;
      setState(() => _camara = controlador);
    } on CameraException catch (e) {
      setState(() => _fallo =
          'No se pudo abrir la cámara (${e.code}). Comprueba los permisos en '
          'los ajustes del móvil.');
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _camara?.dispose();
    super.dispose();
  }

  Future<void> _alternarGrabacion() async {
    final camara = _camara;
    if (camara == null || !camara.value.isInitialized) return;

    if (!_grabando) {
      await camara.startVideoRecording();
      setState(() {
        _grabando = true;
        _iniciada = DateTime.now();
      });
      return;
    }

    final fichero = await camara.stopVideoRecording();
    final duracion = DateTime.now().difference(_iniciada ?? DateTime.now());
    setState(() => _grabando = false);
    if (!mounted) return;

    final aceptado = await _revisar(File(fichero.path), duracion);
    if (aceptado && mounted) widget.alGrabar(File(fichero.path), duracion);
  }

  /// Validación tras grabar y ANTES de subir.
  ///
  /// Solo comprueba metadatos —duración y resolución—, que es todo lo que se
  /// puede saber sin pasar la pose en el móvil. No dice que el vídeo esté bien
  /// encuadrado: dice que no está mal de forma evidente. Se le presenta al
  /// usuario como lo que es.
  Future<bool> _revisar(File video, Duration duracion) async {
    final problemas = <String>[];
    if (duracion < duracionMinima) {
      problemas.add(
        'La grabación dura ${duracion.inSeconds} s. Hacen falta al menos '
        '${duracionMinima.inSeconds}: el contador necesita ver 3 s seguidos '
        'colgado, más lo que tardas en subirte y bajarte.',
      );
    }
    if (duracion > duracionMaxima) {
      problemas.add(
        'La grabación dura ${duracion.inSeconds} s. Por encima de '
        '${duracionMaxima.inSeconds} no se mide mejor y la subida tarda mucho.',
      );
    }
    final tamano = await video.length();
    if (tamano < 100 * 1024) {
      problemas.add('El fichero está casi vacío: la grabación no se guardó bien.');
    }

    if (!mounted) return false;
    return await showDialog<bool>(
          context: context,
          builder: (contexto) => AlertDialog(
            title: Text(problemas.isEmpty ? 'Serie grabada' : 'Revisa la grabación'),
            content: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${duracion.inSeconds} s · '
                    '${(tamano / (1024 * 1024)).toStringAsFixed(1)} MB'),
                const SizedBox(height: 12),
                if (problemas.isEmpty)
                  const Text(
                    'La duración y el tamaño están bien. Lo que no se puede '
                    'comprobar aquí es el encuadre: eso lo dirá el análisis.',
                  )
                else
                  ...problemas.map((p) => Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Text('• $p'),
                      )),
              ],
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(contexto, false),
                child: const Text('Volver a grabar'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(contexto, true),
                child: Text(problemas.isEmpty ? 'Analizar' : 'Analizar igualmente'),
              ),
            ],
          ),
        ) ??
        false;
  }

  @override
  Widget build(BuildContext context) {
    if (_fallo != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(_fallo!, textAlign: TextAlign.center),
        ),
      );
    }
    final camara = _camara;
    if (camara == null) {
      return const Center(child: CircularProgressIndicator());
    }

    return Stack(
      fit: StackFit.expand,
      children: [
        CameraPreview(camara),
        const CustomPaint(painter: GuiaEncuadre(), size: Size.infinite),
        if (!_grabando)
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: _Checklist(
              marcadas: _marcadas,
              alMarcar: (i, valor) => setState(
                  () => valor ? _marcadas.add(i) : _marcadas.remove(i)),
            ),
          ),
        Positioned(
          bottom: _grabando ? 40 : 8,
          left: 0,
          right: 0,
          child: Center(
            child: _BotonGrabar(
              grabando: _grabando,
              habilitado: _listoParaGrabar,
              alPulsar: _alternarGrabacion,
            ),
          ),
        ),
      ],
    );
  }
}

/// Silueta y marca de distancia mínima sobre la vista de la cámara.
///
/// La silueta no es decoración: si el usuario cabe dentro, se le ve entero, y
/// eso es exactamente lo que el pipeline necesita. La marca de abajo indica
/// hasta dónde tienen que llegar los pies —si no llegan, la cámara está
/// demasiado cerca y el cuerpo se saldrá al subir—.
class GuiaEncuadre extends CustomPainter {
  const GuiaEncuadre();

  @override
  void paint(Canvas lienzo, Size medida) {
    final lapiz = Paint()
      ..color = Colors.white.withValues(alpha: 0.75)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2;

    final centro = medida.width / 2;
    final arriba = medida.height * 0.10;
    final abajo = medida.height * 0.92;
    final anchoHombros = medida.width * 0.22;

    // Cabeza.
    lienzo.drawCircle(Offset(centro, arriba + medida.height * 0.05),
        medida.height * 0.045, lapiz);
    // Tronco.
    final tronco = Path()
      ..moveTo(centro - anchoHombros / 2, arriba + medida.height * 0.12)
      ..lineTo(centro + anchoHombros / 2, arriba + medida.height * 0.12)
      ..lineTo(centro + anchoHombros * 0.35, abajo - medida.height * 0.30)
      ..lineTo(centro - anchoHombros * 0.35, abajo - medida.height * 0.30)
      ..close();
    lienzo.drawPath(tronco, lapiz);
    // Brazos hacia la barra.
    lienzo.drawLine(Offset(centro - anchoHombros / 2, arriba + medida.height * 0.12),
        Offset(centro - anchoHombros * 0.9, arriba), lapiz);
    lienzo.drawLine(Offset(centro + anchoHombros / 2, arriba + medida.height * 0.12),
        Offset(centro + anchoHombros * 0.9, arriba), lapiz);
    // Piernas.
    lienzo.drawLine(Offset(centro - anchoHombros * 0.25, abajo - medida.height * 0.30),
        Offset(centro - anchoHombros * 0.30, abajo), lapiz);
    lienzo.drawLine(Offset(centro + anchoHombros * 0.25, abajo - medida.height * 0.30),
        Offset(centro + anchoHombros * 0.30, abajo), lapiz);

    // Marca de distancia mínima: los pies tienen que llegar a esta línea.
    final marca = Paint()
      ..color = const Color(0xFFEF8A17)
      ..strokeWidth = 2;
    for (var x = 0.0; x < medida.width; x += 16) {
      lienzo.drawLine(Offset(x, abajo), Offset(x + 9, abajo), marca);
    }
    final etiqueta = TextPainter(
      text: const TextSpan(
        text: 'los pies, por encima de esta línea',
        style: TextStyle(color: Color(0xFFEF8A17), fontSize: 11),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    etiqueta.paint(lienzo, Offset(12, abajo + 4));
  }

  @override
  bool shouldRepaint(covariant GuiaEncuadre viejo) => false;
}

class _Checklist extends StatelessWidget {
  const _Checklist({required this.marcadas, required this.alMarcar});

  final Set<int> marcadas;
  final void Function(int, bool) alMarcar;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.black.withValues(alpha: 0.62),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 72),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Padding(
            padding: EdgeInsets.only(left: 4, bottom: 4),
            child: Text(
              'Antes de grabar · 1080p y 30 fps en los ajustes de la cámara',
              style: TextStyle(color: Colors.white70, fontSize: 12),
            ),
          ),
          for (var i = 0; i < comprobaciones.length; i++)
            _Punto(
              texto: comprobaciones[i].texto,
              porque: comprobaciones[i].porque,
              marcada: marcadas.contains(i),
              alMarcar: (valor) => alMarcar(i, valor),
            ),
        ],
      ),
    );
  }
}

class _Punto extends StatelessWidget {
  const _Punto({
    required this.texto,
    required this.porque,
    required this.marcada,
    required this.alMarcar,
  });

  final String texto;
  final String porque;
  final bool marcada;
  final ValueChanged<bool> alMarcar;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => alMarcar(!marcada),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          children: [
            Icon(
              marcada ? Icons.check_box : Icons.check_box_outline_blank,
              color: marcada ? const Color(0xFF7ED08F) : Colors.white70,
              size: 20,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(texto,
                  style: const TextStyle(color: Colors.white, fontSize: 13)),
            ),
            IconButton(
              icon: const Icon(Icons.help_outline, color: Colors.white54, size: 18),
              tooltip: 'Por qué',
              onPressed: () => showDialog<void>(
                context: context,
                builder: (contexto) => AlertDialog(
                  title: Text(texto),
                  content: Text(porque),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(contexto),
                      child: const Text('Entendido'),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _BotonGrabar extends StatelessWidget {
  const _BotonGrabar({
    required this.grabando,
    required this.habilitado,
    required this.alPulsar,
  });

  final bool grabando;
  final bool habilitado;
  final VoidCallback alPulsar;

  @override
  Widget build(BuildContext context) {
    final activo = grabando || habilitado;
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (!habilitado && !grabando)
          const Padding(
            padding: EdgeInsets.only(bottom: 8),
            child: Text(
              'Marca los cuatro puntos para poder grabar',
              style: TextStyle(color: Colors.white70, fontSize: 12),
            ),
          ),
        GestureDetector(
          onTap: activo ? alPulsar : null,
          child: Container(
            width: 68,
            height: 68,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(color: Colors.white.withValues(alpha: activo ? 1 : 0.3), width: 4),
            ),
            child: Center(
              child: Container(
                width: grabando ? 26 : 52,
                height: grabando ? 26 : 52,
                decoration: BoxDecoration(
                  color: activo ? Colors.red : Colors.red.withValues(alpha: 0.3),
                  borderRadius: BorderRadius.circular(grabando ? 4 : 26),
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
