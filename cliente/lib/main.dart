import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;

import 'datos/almacen.dart';
import 'modelo/analisis.dart';
import 'pantallas/captura.dart';
import 'pantallas/historico.dart';
import 'pantallas/login_usuario.dart';
import 'pantallas/resultado.dart';
import 'red/api.dart';
import 'widgets/comunes.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AppCai());
}

class AppCai extends StatelessWidget {
  const AppCai({super.key});

  @override
  Widget build(BuildContext context) {
    const semilla = Color(0xFF2F6FED);
    return MaterialApp(
      title: 'cAI-listhenics',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: semilla, useMaterial3: true),
      darkTheme: ThemeData(
        colorSchemeSeed: semilla,
        brightness: Brightness.dark,
        useMaterial3: true,
      ),
      home: const Inicio(),
    );
  }
}

class Inicio extends StatefulWidget {
  const Inicio({super.key});

  @override
  State<Inicio> createState() => _InicioState();
}

class _InicioState extends State<Inicio> {
  Api? _api;
  Almacen? _almacen;
  String? _falloArranque;

  int _pestana = 0;
  List<SerieGuardada> _series = const [];

  /// Análisis en curso: `null` cuando no hay ninguno.
  Avance? _avance;
  FalloAnalisis? _fallo;

  @override
  void initState() {
    super.initState();
    _arrancar();
  }

  Future<void> _arrancar() async {
    try {
      final almacen = await Almacen.abrir();
      final series = await almacen.historico();
      if (!mounted) return;
      setState(() {
        _almacen = almacen;
        _api = Api(almacen.servidor, almacen.clave);
        _series = series;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _falloArranque =
          'No se pudo abrir el histórico del dispositivo.\n\n$e');
    }
  }

  @override
  void dispose() {
    _api?.cerrar();
    _almacen?.cerrar();
    super.dispose();
  }

  /// Dirección y contraseña del backend, comprobadas antes de guardarse.
  ///
  /// La comprobación no es un adorno: sin ella, unos ajustes mal escritos no se
  /// descubren hasta después de subir un vídeo de cien megas por una red móvil,
  /// que es el peor momento posible para enterarse.
  Future<void> _cambiarServidor() async {
    final almacen = _almacen;
    if (almacen == null) return;

    final control = TextEditingController(text: almacen.servidor);
    final controlClave = TextEditingController(text: almacen.clave);

    final guardado = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (contexto) => _DialogoServidor(
        control: control,
        controlClave: controlClave,
        comprobar: (url, clave) async {
          final prueba = Api(url, clave);
          final fallo = await prueba.comprobar();
          prueba.cerrar();
          return fallo;
        },
      ),
    );

    if (guardado != true) return;
    await almacen.guardarAcceso(
      url: control.text,
      clave: controlClave.text,
    );
    if (!mounted) return;
    setState(() {
      _api?.cerrar();
      _api = Api(almacen.servidor, almacen.clave);
      _fallo = null;
    });
  }

  Future<void> _recargar() async {
    final almacen = _almacen;
    if (almacen == null) return;
    final series = await almacen.historico();
    if (mounted) setState(() => _series = series);
  }

  void _abrirPerfil() {
    final almacen = _almacen;
    if (almacen == null) return;

    Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (contexto) => PantallaLoginUsuario(
          almacen: almacen,
          alSeleccionarUsuario: (u) async {
            Navigator.of(contexto).pop();
            await _recargar();
          },
        ),
      ),
    );
  }

  Future<void> _abrirDetalleSerie(SerieGuardada serie) async {
    // Reconstruir objeto Análisis simple para vista detallada
    final analisis = Analisis(
      jobId: 'guardado_${serie.id}',
      versionPipeline: serie.versionPipeline,
      limitaciones: 'Serie del histórico.',
      fps: 30.0,
      paso: 2,
      escalaPxBu: serie.escalaPxBu ?? 0.0,
      recorridoBu: serie.recorridoBu ?? 0.0,
      nTotal: serie.nTotal,
      nValidas: serie.nValidas,
      nUsadas: serie.nTotal,
      referencias: const Referencias(barraYPx: 0.0, barraBu: 0.0, umbralBu: 0.0, umbralVBuS: 0.0),
      resumen: ResumenSerie(
        romMedioBu: serie.romMedio,
        romSdBu: null,
        tSubidaMediaS: null,
        tBajadaMediaS: null,
        ratioMedio: serie.ratioMedio,
        ratioSd: null,
        vPicoMedia: null,
        caidaVelocidad: serie.caidaVelocidad,
        caidaVelocidadPct: null,
        caidaVelocidadR2: 1.0,
        desnivelHombrosMedioBu: null,
        desviacionNarizMediaBu: null,
      ),
      repeticiones: serie.repeticiones,
      senal: const Senal(tiempoS: [], alturaBu: [], fases: []),
      keypoints: const [],
    );

    final tieneFichero = serie.videoAnotadoPath != null &&
        File(serie.videoAnotadoPath!).existsSync();

    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (contexto) => PantallaResultado(
          analisis: analisis,
          guardada: true,
          videoAnotadoFichero: tieneFichero ? File(serie.videoAnotadoPath!) : null,
          alGuardar: () {},
          alDescartar: () {},
        ),
      ),
    );
  }

  Future<void> _analizar(File video, Duration duracion) async {
    final almacen = _almacen;
    final api = _api;
    if (almacen == null || api == null) return;

    setState(() {
      _avance = const Avance('en_cola', 0);
      _fallo = null;
    });

    try {
      final analisis = await api.analizar(
        video,
        deviceId: almacen.deviceId,
        anotar: true, // Pedir vídeo anotado con trackpoints
        alAvanzar: (a) {
          if (mounted) setState(() => _avance = a);
        },
      );
      if (!mounted) return;
      setState(() => _avance = null);
      await _mostrarResultado(analisis);
    } on FalloAnalisis catch (fallo) {
      if (!mounted) return;
      setState(() {
        _avance = null;
        _fallo = fallo;
      });
    } finally {
      if (await video.exists()) {
        try {
          await video.delete();
        } catch (_) {}
      }
    }
  }

  Future<void> _mostrarResultado(Analisis analisis) async {
    final almacen = _almacen;
    final api = _api;
    if (almacen == null) return;

    await Navigator.of(context).push<void>(
      MaterialPageRoute(
        builder: (contexto) => PantallaResultado(
          analisis: analisis,
          alGuardar: () async {
            String? rutaVideoLocal;

            // Descargar el vídeo anotado con trackpoints si el servidor lo generó
            if (analisis.videoAnotadoUrl != null && api != null) {
              final nombre = '${DateTime.now().toUtc().millisecondsSinceEpoch}.mp4';
              final destino = File(p.join(almacen.carpetaVideos.path, nombre));
              final descargado = await api.descargarVideo(analisis.videoAnotadoUrl!, destino);
              if (descargado != null) {
                rutaVideoLocal = descargado.path;
              }
            }

            await almacen.guardar(
              analisis,
              videoAnotadoPath: rutaVideoLocal,
            );

            // Guardado en el móvil: ya no hace falta nada en el servidor.
            await api?.olvidar(analisis.jobId);
            if (contexto.mounted) Navigator.of(contexto).pop();
            await _recargar();
            if (mounted) setState(() => _pestana = 1);
          },
          alDescartar: () async {
            await api?.olvidar(analisis.jobId);
            if (contexto.mounted) Navigator.of(contexto).pop();
          },
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (_falloArranque != null) {
      return Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(_falloArranque!, textAlign: TextAlign.center),
          ),
        ),
      );
    }
    if (_almacen == null || _api == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    return Scaffold(
      appBar: _pestana == 1
          ? AppBar(
              title: Row(
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(16),
                    child: Image.asset(
                      'assets/images/logo.jpg',
                      width: 32,
                      height: 32,
                      fit: BoxFit.cover,
                      errorBuilder: (_, __, ___) => const Icon(Icons.fitness_center),
                    ),
                  ),
                  const SizedBox(width: 10),
                  const Text('Histórico'),
                ],
              ),
              actions: [
                IconButton(
                  icon: const Icon(Icons.dns_outlined),
                  tooltip: 'Servidor: ${_almacen!.servidor}',
                  onPressed: _cambiarServidor,
                ),
              ],
            )
          : null,
      // A propósito NO es un IndexedStack: con él, las dos pantallas siguen en
      // el árbol y la cámara se queda encendida mientras se mira el histórico.
      // Montando solo la activa, salir de la pestaña destruye
      // `PantallaCaptura` y con ella el `CameraController`.
      body: _pestana == 0
          ? _Captura(
              avance: _avance,
              fallo: _fallo,
              alGrabar: _analizar,
              alReintentar: () => setState(() => _fallo = null),
              alCambiarServidor: _cambiarServidor,
            )
          : PantallaHistorico(
              series: _series,
              usuarioActivo: _almacen?.usuarioActivo,
              alAbrirPerfil: _abrirPerfil,
              alAbrirSerie: _abrirDetalleSerie,
              alRecargar: _recargar,
              alBorrar: (serie) async {
                await _almacen!.borrar(serie);
                await _recargar();
              },
            ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _pestana,
        onDestinationSelected: (i) => setState(() => _pestana = i),
        destinations: const [
          NavigationDestination(
              icon: Icon(Icons.videocam_outlined),
              selectedIcon: Icon(Icons.videocam),
              label: 'Grabar'),
          NavigationDestination(
              icon: Icon(Icons.show_chart_outlined),
              selectedIcon: Icon(Icons.show_chart),
              label: 'Histórico'),
        ],
      ),
    );
  }
}

/// La pestaña de grabar, con sus tres estados: cámara, procesando y fallo.
class _Captura extends StatelessWidget {
  const _Captura({
    required this.avance,
    required this.fallo,
    required this.alGrabar,
    required this.alReintentar,
    required this.alCambiarServidor,
  });

  final Avance? avance;
  final FalloAnalisis? fallo;
  final void Function(File, Duration) alGrabar;
  final VoidCallback alReintentar;
  final VoidCallback alCambiarServidor;

  @override
  Widget build(BuildContext context) {
    if (fallo != null) {
      return PanelFallo(
        titulo: fallo!.titulo,
        instruccion: fallo!.instruccion,
        alReintentar: alReintentar,
        // Si el fallo es de red, reintentar no arregla nada: lo que hay que
        // cambiar es a dónde apunta la app.
        accionExtra: fallo!.codigo == 'SIN_RED' ? alCambiarServidor : null,
        etiquetaExtra: 'Cambiar dirección del servidor',
      );
    }
    if (avance != null) return _Procesando(avance: avance!);
    return PantallaCaptura(alGrabar: alGrabar);
  }
}

class _Procesando extends StatelessWidget {
  const _Procesando({required this.avance});
  final Avance avance;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 220,
              child: LinearProgressIndicator(
                value: avance.progreso > 0 ? avance.progreso : null,
              ),
            ),
            const SizedBox(height: 20),
            Text(
              avance.estado == 'en_cola'
                  ? 'Subiendo el vídeo…'
                  : 'Analizando (${(avance.progreso * 100).toStringAsFixed(0)} %)',
              style: tema.textTheme.titleSmall,
            ),
            const SizedBox(height: 8),
            Text(
              'Un vídeo de 30 segundos tarda entre 6 y 14. El vídeo se borra del '
              'servidor en cuanto termina: solo se guardan los keypoints y las '
              'métricas, aquí en el móvil.',
              textAlign: TextAlign.center,
              style: tema.textTheme.bodySmall
                  ?.copyWith(color: tema.colorScheme.outline),
            ),
          ],
        ),
      ),
    );
  }
}

/// Ajustes de acceso al servidor: dirección y contraseña, con comprobación.
///
/// Es un widget con estado propio porque tiene que enseñar "comprobando…" y el
/// resultado sin cerrarse, y un `showDialog` a secas no puede repintarse.
class _DialogoServidor extends StatefulWidget {
  const _DialogoServidor({
    required this.control,
    required this.controlClave,
    required this.comprobar,
  });

  final TextEditingController control;
  final TextEditingController controlClave;
  final Future<FalloAnalisis?> Function(String url, String clave) comprobar;

  @override
  State<_DialogoServidor> createState() => _DialogoServidorState();
}

class _DialogoServidorState extends State<_DialogoServidor> {
  bool _comprobando = false;
  FalloAnalisis? _fallo;
  bool _verClave = false;

  Future<void> _probarYGuardar() async {
    setState(() {
      _comprobando = true;
      _fallo = null;
    });
    final fallo = await widget.comprobar(
      widget.control.text.trim(),
      widget.controlClave.text.trim(),
    );
    if (!mounted) return;
    if (fallo == null) {
      Navigator.pop(context, true);
      return;
    }
    setState(() {
      _comprobando = false;
      _fallo = fallo;
    });
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return AlertDialog(
      title: const Text('Servidor'),
      content: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Dirección del backend y su contraseña. El servidor rechaza todas '
              'las peticiones que no la lleven.',
              style: tema.textTheme.bodySmall,
            ),
            const SizedBox(height: 14),
            TextField(
              controller: widget.control,
              autofocus: true,
              keyboardType: TextInputType.url,
              autocorrect: false,
              enabled: !_comprobando,
              decoration: const InputDecoration(
                labelText: 'Dirección',
                border: OutlineInputBorder(),
                hintText: 'http://140.238.1.2:8000',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: widget.controlClave,
              obscureText: !_verClave,
              autocorrect: false,
              enableSuggestions: false,
              enabled: !_comprobando,
              decoration: InputDecoration(
                labelText: 'Contraseña',
                border: const OutlineInputBorder(),
                suffixIcon: IconButton(
                  icon: Icon(_verClave ? Icons.visibility_off : Icons.visibility),
                  // Poder verla importa: se teclea a mano desde otra pantalla y
                  // una errata en un campo de puntos no hay quien la encuentre.
                  tooltip: _verClave ? 'Ocultar' : 'Ver',
                  onPressed: () => setState(() => _verClave = !_verClave),
                ),
              ),
            ),
            if (_fallo != null) ...[
              const SizedBox(height: 14),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: tema.colorScheme.errorContainer,
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _fallo!.titulo,
                      style: tema.textTheme.labelLarge
                          ?.copyWith(color: tema.colorScheme.onErrorContainer),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      _fallo!.instruccion,
                      style: tema.textTheme.bodySmall
                          ?.copyWith(color: tema.colorScheme.onErrorContainer),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: _comprobando ? null : () => Navigator.pop(context, false),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: _comprobando ? null : _probarYGuardar,
          child: _comprobando
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Text('Comprobar y guardar'),
        ),
      ],
    );
  }
}
