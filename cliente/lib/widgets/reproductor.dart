/// Widget reproductor para los vídeos anotados con trackpoints.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

class ReproductorVideo extends StatefulWidget {
  const ReproductorVideo({
    super.key,
    this.fichero,
    this.url,
    this.titulo = 'Vídeo con trackpoints',
  }) : assert(fichero != null || url != null, 'Debes proporcionar un archivo o una URL.');

  final File? fichero;
  final String? url;
  final String titulo;

  @override
  State<ReproductorVideo> createState() => _ReproductorVideoState();
}

class _ReproductorVideoState extends State<ReproductorVideo> {
  VideoPlayerController? _controller;
  bool _inicializado = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _inicializarController();
  }

  Future<void> _inicializarController() async {
    try {
      if (widget.fichero != null) {
        _controller = VideoPlayerController.file(widget.fichero!);
      } else if (widget.url != null) {
        _controller = VideoPlayerController.networkUrl(Uri.parse(widget.url!));
      }

      final c = _controller;
      if (c == null) return;

      await c.initialize();
      if (!mounted) return;

      c.addListener(() {
        if (mounted) setState(() {});
      });

      setState(() => _inicializado = true);
    } catch (e) {
      if (mounted) {
        setState(() => _error = 'No se pudo cargar el vídeo: $e');
      }
    }
  }

  @override
  void dispose() {
    _controller?.dispose();
    super.dispose();
  }

  void _alternarReproduccion() {
    final c = _controller;
    if (c == null || !_inicializado) return;
    if (c.value.isPlaying) {
      c.pause();
    } else {
      c.play();
    }
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);

    if (_error != null) {
      return Card(
        color: tema.colorScheme.errorContainer.withValues(alpha: 0.3),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Text(
            _error!,
            style: TextStyle(color: tema.colorScheme.error, fontSize: 13),
            textAlign: TextAlign.center,
          ),
        ),
      );
    }

    final c = _controller;
    if (!_inicializado || c == null) {
      return Container(
        height: 200,
        decoration: BoxDecoration(
          color: Colors.black12,
          borderRadius: BorderRadius.circular(12),
        ),
        child: const Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(),
              SizedBox(height: 12),
              Text('Cargando vídeo anotado…', style: TextStyle(fontSize: 12)),
            ],
          ),
        ),
      );
    }

    final posicion = c.value.position;
    final duracion = c.value.duration;
    final terminado = posicion >= duracion && duracion > Duration.zero;

    return Container(
      decoration: BoxDecoration(
        color: Colors.black,
        borderRadius: BorderRadius.circular(12),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            child: Row(
              children: [
                const Icon(Icons.videocam, color: Color(0xFFEF8A17), size: 18),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    widget.titulo,
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w600,
                      fontSize: 13,
                    ),
                  ),
                ),
                Text(
                  '${_formatoDuracion(posicion)} / ${_formatoDuracion(duracion)}',
                  style: const TextStyle(color: Colors.white70, fontSize: 12),
                ),
              ],
            ),
          ),
          GestureDetector(
            onTap: _alternarReproduccion,
            child: AspectRatio(
              aspectRatio: c.value.aspectRatio > 0 ? c.value.aspectRatio : 16 / 9,
              child: Stack(
                alignment: Alignment.center,
                children: [
                  VideoPlayer(c),
                  if (!c.value.isPlaying || terminado)
                    Container(
                      color: Colors.black38,
                      child: Icon(
                        terminado
                            ? Icons.replay_circle_filled
                            : Icons.play_circle_fill,
                        size: 64,
                        color: Colors.white.withValues(alpha: 0.9),
                      ),
                    ),
                ],
              ),
            ),
          ),
          VideoProgressIndicator(
            c,
            allowScrubbing: true,
            colors: const VideoProgressColors(
              playedColor: Color(0xFF2F6FED),
              bufferedColor: Colors.white24,
              backgroundColor: Colors.white10,
            ),
          ),
        ],
      ),
    );
  }

  String _formatoDuracion(Duration d) {
    final minutos = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final segundos = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$minutos:$segundos';
  }
}
