# Portal Educativo BlockCorp

Este proyecto implementa un portal web de entrenamiento basado en misiones. Los estudiantes se matriculan, avanzan por las misiones y deben cumplir contratos de entrega que se verifican de manera automática. Está dividido en frontend (HTML, CSS y JavaScript), backend (Python Flask) y un archivo de contratos en YAML. Puedes empaquetar y desplegar la aplicación en Windows IIS mediante el script `install_all.ps1`.

## Flujo de acceso a misiones en el frontend

La lógica que determina qué misiones están desbloqueadas vive en `frontend/assets/js/main.js` dentro del helper `ensureMissionUnlocked(missionId)`. Este helper lee el `slug` y `token` guardados, consulta `/api/status` y reconstruye el mapa de progreso según el rol del estudiante. Si la sesión no existe, expiró o falta completar la misión previa, limpia el almacenamiento local y devuelve una instrucción para redirigir de vuelta al portal o mostrar un aviso.

Cada página de misión (por ejemplo `frontend/m3.html`) debe ocultar su `<main>` inicial usando el atributo `hidden` y, en `DOMContentLoaded`, llamar a `ensureMissionUnlocked`. Si la respuesta indica que el acceso es válido, la página quita el `hidden`, enlaza el botón de verificación y deja visible el contenido. Cuando el helper responde con una redirección se envía al estudiante a `index.html`; si se trata de progreso faltante, se reemplaza el cuerpo con un mensaje que invita a completar la misión anterior. Sigue este patrón para cualquier misión nueva para mantener una experiencia homogénea.

## Configuración de base de datos

El servicio backend persiste estudiantes y misiones completadas en una base de datos MySQL (por ejemplo, Cloud SQL for MySQL). Antes de iniciar el servidor debes definir las siguientes variables de entorno:

| Variable | Descripción |
| --- | --- |
| `DB_NAME` | Nombre de la base de datos. |
| `DB_USER` | Usuario con permisos de lectura/escritura. |
| `DB_PASSWORD` | Contraseña del usuario. |
| `DB_HOST` | Host o IP del servidor MySQL (usa `DB_PORT` para el puerto, por defecto 3306). |
| `DB_INSTANCE_CONNECTION_NAME` | Alternativa a `DB_HOST` para conexiones vía socket de Cloud SQL for MySQL (`<project>:<region>:<instance>`). |

Variables opcionales:

| Variable | Descripción |
| --- | --- |
| `DB_PORT` | Puerto TCP cuando se usa `DB_HOST` (por defecto 3306). |
| `DB_SOCKET_DIR` | Directorio del socket Unix para Cloud SQL (por defecto `/cloudsql`). |
| `DB_CONNECT_TIMEOUT` | Tiempo máximo de conexión en segundos. |

Debes proporcionar `DB_HOST` o `DB_INSTANCE_CONNECTION_NAME`; si falta alguno el backend devolverá un error 500 al atender las peticiones.

### Gestión de sesiones

El backend persiste las sesiones de autenticación en la tabla `sessions` de la misma base de datos. Aplica las migraciones SQL en `backend/migrations/` (incluyendo `003_create_sessions_table.sql`) para crearla con las columnas `token`, `student_slug` y `created_at`, donde `token` actúa como clave primaria e índice para las búsquedas.

Cuando un estudiante inicia sesión, `create_session` inserta una fila nueva con un token firmado aleatorio y marca la hora de creación con `UTC_TIMESTAMP()`. Cada llamada a `validate_session` consulta la tabla y elimina automáticamente los registros cuya antigüedad supere las ocho horas (`SESSION_DURATION_SECONDS`). Cuando se implemente un endpoint de cierre de sesión bastará con borrar la fila correspondiente (`DELETE FROM sessions WHERE token = ?`) para invalidar el token también en el resto de instancias.

### Endpoints administrativos para estudiantes

Los administradores autenticados (token válido en el encabezado `Authorization: Bearer <token>`) pueden gestionar estudiantes mediante la API protegida bajo `/api/admin/students`:

| Método | Ruta | Descripción |
| --- | --- | --- |
| `GET` | `/api/admin/students` | Lista todos los estudiantes con sus campos principales (`slug`, `name`, `email`, `role`, `is_admin`, `created_at`) y el arreglo `completed_missions` con las misiones aprobadas. |
| `PUT` | `/api/admin/students/<slug>` | Actualiza los datos del estudiante indicado. Acepta `name`, `email`, `role`, `is_admin` y, opcionalmente, `password`. Si se envía `current_password` se verifica contra la contraseña almacenada antes de aplicar el nuevo hash. |
| `DELETE` | `/api/admin/students/<slug>` | Elimina al estudiante y, gracias a las claves foráneas con `ON DELETE CASCADE`, borra también los registros de `completed_missions` asociados. |

El backend reutiliza los helpers `hash_password` y `verify_password` para validar los cambios de contraseña y mantiene la compatibilidad tanto con SQLite como con MySQL. Todos los endpoints devuelven errores `401/403` cuando el token es inválido o pertenece a un usuario sin privilegios administrativos.

### Clave secreta de Flask (`SECRET_KEY`)

La aplicación Flask utiliza `SECRET_KEY` para firmar las cookies de sesión y otros tokens. En producción debes fijar explícitamente una cadena aleatoria y mantenerla en secreto. Por ejemplo:

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

Si `SECRET_KEY` no está definida al iniciar el backend, este mostrará un aviso en los logs y generará automáticamente una clave segura. El valor se guardará en `backend/.flask_secret_key` para reutilizarlo en reinicios posteriores (con permisos `600` cuando el sistema lo permite). Si tampoco se pudiera escribir el archivo, el backend continuará usando una clave efímera y registrará la incidencia. Revisa los logs para confirmar qué ruta se está utilizando.

## Integración con repositorios remotos en GitHub

La verificación automática de misiones se realiza leyendo los archivos del estudiante directamente desde GitHub. Configura las siguientes variables de entorno antes de iniciar el backend:

| Variable | Descripción |
| --- | --- |
| `GITHUB_TOKEN` | Token personal con permiso de lectura sobre los repositorios. |
| `GITHUB_VENTAS_REPO` | Repositorio (formato `owner/nombre`) donde trabajan los estudiantes del track de Ventas. |
| `GITHUB_OPERACIONES_REPO` | Repositorio (formato `owner/nombre`) para el track de Operaciones. |
| `GITHUB_VENTAS_BRANCH` | Rama por defecto a utilizar para Ventas (opcional, `main` si no se define). |
| `GITHUB_OPERACIONES_BRANCH` | Rama por defecto para Operaciones (opcional, `main` si no se define). |
| `GITHUB_API_URL` | URL base de la API de GitHub (opcional, útil para GitHub Enterprise). |
| `GITHUB_TIMEOUT` | Tiempo máximo en segundos para cada descarga desde GitHub (opcional, por defecto `10`). |

El backend identifica qué repositorio debe revisar cada estudiante usando su `slug` o el `role` registrado (`ventas`, `operaciones`, sufijos `_v`/`_o`, etc.). En `backend/missions_contracts.json` cada misión incluye una sección `source` con la plantilla de ruta base (`students/{slug}`) y el repositorio objetivo (`default`, `ventas` u `operaciones`). Durante la verificación se descargan únicamente los archivos declarados en el contrato y, en el caso de scripts, se copian a un directorio temporal antes de ejecutarlos.

Si GitHub devuelve un error o el archivo solicitado no existe, la API responde con `verified: false` y un mensaje de retroalimentación indicando qué archivo falló y en qué repositorio se buscó. Esto permite que el estudiante ajuste su entrega sin necesidad de revisar los logs del servidor.

## Evaluación automática con modelos de lenguaje

Algunas misiones (por ejemplo `m5`) utilizan un modelo de lenguaje para revisar las notas del estudiante. El backend envía el contenido del deliverable y el contexto del contrato a la API de OpenAI y espera una respuesta en formato JSON indicando si la entrega está `completado` o `incompleto`.

Configura las siguientes variables de entorno para habilitar esta evaluación:

| Variable | Descripción |
| --- | --- |
| `OPENAI_API_KEY` | **Obligatoria.** Clave privada de OpenAI con acceso al modelo seleccionado. |
| `OPENAI_MODEL` | Opcional. Modelo de chat a utilizar (por defecto `gpt-3.5-turbo`). |
| `OPENAI_TIMEOUT` | Opcional. Tiempo máximo de espera en segundos antes de abortar la solicitud. |

El proyecto depende de la librería oficial `openai` incluida en `backend/requirements.txt`. Ejecuta `pip install -r backend/requirements.txt` para instalarla antes de iniciar el servidor.
