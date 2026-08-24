/// Pantalla de gestión e inicio de sesión / creación de usuario.
library;

import 'package:flutter/material.dart';

import '../datos/almacen.dart';

class PantallaLoginUsuario extends StatefulWidget {
  const PantallaLoginUsuario({
    super.key,
    required this.almacen,
    required this.alSeleccionarUsuario,
  });

  final Almacen almacen;
  final void Function(Usuario usuario) alSeleccionarUsuario;

  @override
  State<PantallaLoginUsuario> createState() => _PantallaLoginUsuarioState();
}

class _PantallaLoginUsuarioState extends State<PantallaLoginUsuario> {
  final _formKey = GlobalKey<FormState>();
  final _usernameControl = TextEditingController();
  final _nombreControl = TextEditingController();

  List<Usuario> _usuarios = [];
  bool _cargando = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _cargarUsuarios();
  }

  Future<void> _cargarUsuarios() async {
    final lista = await widget.almacen.obtenerUsuarios();
    if (mounted) {
      setState(() {
        _usuarios = lista;
        _cargando = false;
      });
    }
  }

  @override
  void dispose() {
    _usernameControl.dispose();
    _nombreControl.dispose();
    super.dispose();
  }

  Future<void> _crear() async {
    if (!_formKey.currentState!.validate()) return;
    final username = _usernameControl.text.trim();
    final nombre = _nombreControl.text.trim();

    try {
      final existente = await widget.almacen.buscarUsuario(username);
      if (existente != null) {
        setState(() => _error = 'El nombre de usuario "@$username" ya existe.');
        return;
      }

      final nuevo = await widget.almacen.crearUsuario(
        username: username,
        nombre: nombre.isEmpty ? null : nombre,
      );
      if (mounted) {
        widget.alSeleccionarUsuario(nuevo);
      }
    } catch (e) {
      setState(() => _error = 'Error al crear usuario: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Perfil de Usuario'),
      ),
      body: _cargando
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Center(
                    child: Column(
                      children: [
                        ClipRRect(
                          borderRadius: BorderRadius.circular(24),
                          child: Image.asset(
                            'assets/images/logo.jpg',
                            width: 72,
                            height: 72,
                            fit: BoxFit.cover,
                            errorBuilder: (_, __, ___) => const Icon(Icons.person, size: 56),
                          ),
                        ),
                        const SizedBox(height: 10),
                        Text(
                          'cAI-listhenics',
                          style: tema.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.bold),
                        ),
                        const SizedBox(height: 20),
                      ],
                    ),
                  ),

                  if (_usuarios.isNotEmpty) ...[
                    Text(
                      'Selecciona tu usuario',
                      style: tema.textTheme.titleMedium,
                    ),
                    const SizedBox(height: 12),
                    Card(
                      child: Column(
                        children: [
                          for (final u in _usuarios)
                            ListTile(
                              leading: CircleAvatar(
                                backgroundColor: tema.colorScheme.primaryContainer,
                                child: Text(
                                  (u.nombre ?? u.username)[0].toUpperCase(),
                                  style: TextStyle(
                                    color: tema.colorScheme.onPrimaryContainer,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                              ),
                              title: Text(u.nombre ?? '@${u.username}'),
                              subtitle: Text('@${u.username}'),
                              trailing: widget.almacen.usuarioActivo?.id == u.id
                                  ? const Icon(Icons.check_circle, color: Colors.green)
                                  : null,
                              onTap: () {
                                widget.almacen.seleccionarUsuario(u);
                                widget.alSeleccionarUsuario(u);
                              },
                            ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 32),
                    const Divider(),
                    const SizedBox(height: 24),
                  ],

                  Text(
                    'Crear nuevo usuario',
                    style: tema.textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Registra tu nombre para asociar tus entrenamientos a tu perfil.',
                    style: tema.textTheme.bodySmall
                        ?.copyWith(color: tema.colorScheme.outline),
                  ),
                  const SizedBox(height: 16),

                  if (_error != null) ...[
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: tema.colorScheme.errorContainer.withValues(alpha: 0.5),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        _error!,
                        style: TextStyle(color: tema.colorScheme.error, fontSize: 13),
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],

                  Form(
                    key: _formKey,
                    child: Column(
                      children: [
                        TextFormField(
                          controller: _usernameControl,
                          decoration: const InputDecoration(
                            labelText: 'Nombre de usuario (@ejemplo)',
                            prefixIcon: Icon(Icons.alternate_email),
                            border: OutlineInputBorder(),
                          ),
                          validator: (val) {
                            if (val == null || val.trim().isEmpty) {
                              return 'Introduce un nombre de usuario válido';
                            }
                            if (val.trim().length < 3) {
                              return 'El usuario debe tener al menos 3 caracteres';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 16),
                        TextFormField(
                          controller: _nombreControl,
                          decoration: const InputDecoration(
                            labelText: 'Nombre completo (opcional)',
                            prefixIcon: Icon(Icons.person_outline),
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 24),
                        SizedBox(
                          width: double.infinity,
                          height: 48,
                          child: FilledButton.icon(
                            onPressed: _crear,
                            icon: const Icon(Icons.person_add),
                            label: const Text('Crear Usuario'),
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}
