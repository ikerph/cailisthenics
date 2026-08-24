/// Configuración de la beta. Sin login, sin ajustes: una constante y ya.
library;

/// Dónde vive el backend.
///
/// En depuración apunta al emulador de Android: `10.0.2.2` es el host desde
/// dentro de la máquina virtual; `localhost` sería el propio emulador y no
/// respondería nadie. Para probar en un móvil real por wifi, se pone la IP del
/// portátil y se arranca uvicorn con `--host 0.0.0.0`.
const String baseUrl = String.fromEnvironment(
  'CAI_BASE_URL',
  defaultValue: 'http://10.0.2.2:8000',
);

/// Duración mínima de una grabación útil.
///
/// El contador necesita al menos 3 s seguidos colgado de la barra, y hay que
/// contar lo que se tarda en subirse y bajarse. Por debajo de esto el análisis
/// falla seguro, y es mejor decirlo antes de gastar la subida.
const Duration duracionMinima = Duration(seconds: 8);

/// Por encima de esto no se mide mejor, solo se tarda más en subir.
const Duration duracionMaxima = Duration(seconds: 90);
