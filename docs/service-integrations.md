# Integraciones de servicios

El portal almacena las credenciales de GitHub y OpenAI en la tabla `service_integrations`. Cada entrada contiene un par `service`/`key` y el valor correspondiente, junto con metadatos descriptivos.

## Esquema de la tabla

| Columna      | Tipo      | Descripción                                                                 |
| ------------ | --------- | --------------------------------------------------------------------------- |
| `service`    | `TEXT`    | Identificador del servicio externo (por ejemplo `github` u `openai`).      |
| `key`        | `TEXT`    | Nombre del parámetro (token, owner, api_key, etc.).                         |
| `value`      | `TEXT`    | Valor almacenado. Se mantiene cifrado a nivel de base de datos.            |
| `description`| `TEXT`    | Descripción o instrucciones del campo.                                     |
| `metadata`   | `JSONB`   | Información adicional (placeholders, ejemplos).                            |
| `updated_at` | `TIMESTAMPTZ` | Fecha de la última actualización del registro.                        |

Cada combinación (`service`, `key`) es única. El backend valida las credenciales antes de persistir los cambios y actualiza automáticamente la marca de tiempo.

## Configuración esperada por servicio

### GitHub

| Campo        | Requerido | Descripción                                                                 |
| ------------ | --------- | --------------------------------------------------------------------------- |
| `token`      | Sí        | Token personal (PAT) en formato `ghp_...` con permisos de lectura a repositorios privados. Debe incluir el scope `repo` para listar y consultar repositorios. |
| `owner`      | Sí        | Usuario u organización que aloja el repositorio principal.                   |
| `repository` | Sí        | Nombre del repositorio que usará el portal para sincronizar evidencias.     |

Durante la validación se realizan dos llamadas mínimas a la API REST de GitHub:

1. `GET https://api.github.com/user` para comprobar que el token es válido.
2. `GET https://api.github.com/repos/{owner}/{repository}` (o `GET /user/repos`) para confirmar el acceso al repositorio configurado.

### OpenAI

| Campo           | Requerido | Descripción                                                                 |
| ----------------| --------- | --------------------------------------------------------------------------- |
| `api_key`       | Sí        | API key de OpenAI en formato `sk-...` con permisos para listar modelos.    |
| `organization`  | Opcional  | ID de organización (`org-...`) si la cuenta lo requiere.                   |
| `project`       | Opcional  | Identificador de proyecto empresarial.                                     |
| `base_url`      | Opcional  | Endpoint alternativo para entornos con proxy (`https://api.openai.com/v1`). |
| `default_model` | Opcional  | Modelo preferido para el portal (por ejemplo `gpt-4o-mini`).               |

La verificación realiza una petición `GET {base_url}/models` y comprueba que la respuesta incluya al menos un modelo disponible.

## Flujo administrativo

1. Inicia sesión en el portal como usuario con rol **Admin**.
2. Accede a `frontend/admin/index.html`. El enlace “Administración” aparece automáticamente para cuentas con permisos.
3. Completa los formularios de GitHub u OpenAI. Los campos sensibles pueden dejarse en blanco para mantener el valor almacenado.
4. Haz clic en **“Probar y guardar”**. El backend validará las credenciales antes de actualizar la base de datos y devolverá un mensaje con el resultado.
5. Repite el proceso cada vez que debas rotar tokens, cambiar de repositorio o actualizar el modelo predeterminado.

Si la validación falla, el backend devolverá un mensaje detallado indicando la causa (token inválido, repositorio inexistente, error de red, etc.). No se guardarán cambios hasta superar la prueba.

## Pruebas automatizadas

Antes de desplegar cambios en las integraciones ejecuta los tests del backend:

```bash
pip install -r backend/requirements.txt
pip install pytest
pytest backend/tests/test_service_integrations.py
```

Las pruebas cubren la creación y actualización de configuraciones, así como el manejo de errores en las llamadas de GitHub y OpenAI mediante stubs de red.
