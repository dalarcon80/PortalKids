# Portal Educativo BlockCorp

Este proyecto implementa un portal web de entrenamiento basado en misiones. Los estudiantes se matriculan, avanzan por las misiones y deben cumplir contratos de entrega que se verifican de manera automática. Está dividido en frontend (HTML, CSS y JavaScript), backend (Python Flask) y un archivo de contratos en YAML. Puedes empaquetar y desplegar la aplicación en Windows IIS mediante el script `install_all.ps1`.

## Configuración de base de datos

El servicio backend persiste estudiantes y misiones completadas en una base de datos PostgreSQL (por ejemplo, Cloud SQL). Antes de iniciar el servidor debes definir las siguientes variables de entorno:

| Variable | Descripción |
| --- | --- |
| `DB_NAME` | Nombre de la base de datos. |
| `DB_USER` | Usuario con permisos de lectura/escritura. |
| `DB_PASSWORD` | Contraseña del usuario. |
| `DB_HOST` | Host o IP del servidor PostgreSQL (usa `DB_PORT` para el puerto, por defecto 5432). |
| `DB_INSTANCE_CONNECTION_NAME` | Alternativa a `DB_HOST` para conexiones vía socket de Cloud SQL (`<project>:<region>:<instance>`). |

Variables opcionales:

| Variable | Descripción |
| --- | --- |
| `DB_PORT` | Puerto TCP cuando se usa `DB_HOST`. |
| `DB_SOCKET_DIR` | Directorio del socket Unix para Cloud SQL (por defecto `/cloudsql`). |
| `DB_SSLMODE` | Modo SSL de PostgreSQL (por defecto `prefer`). |
| `DB_CONNECT_TIMEOUT` | Tiempo máximo de conexión en segundos. |

Debes proporcionar `DB_HOST` o `DB_INSTANCE_CONNECTION_NAME`; si falta alguno el backend devolverá un error 500 al atender las peticiones.

## Integraciones externas

Las credenciales para GitHub y OpenAI se gestionan desde la interfaz administrativa (`frontend/admin/index.html`). El backend deja de depender de variables de entorno para estas integraciones y almacena la configuración en la tabla `service_integrations`. Cada actualización ejecuta una prueba mínima contra el servicio externo antes de persistir los cambios.

Revisa la guía [docs/service-integrations.md](docs/service-integrations.md) para conocer:

* Qué campos se esperan para cada servicio y el formato de los tokens.
* Cómo usar el panel de administración y qué mensajes devuelve el backend cuando hay errores de validación.
* Los comandos necesarios para ejecutar las pruebas automatizadas (`pytest backend/tests/test_service_integrations.py`) antes de aplicar cambios en producción.
