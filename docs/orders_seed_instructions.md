# Guía para copiar `sources/orders_seed.csv`

El archivo `sources/orders_seed.csv` vive en este repositorio central de PortalKids. Antes de ejecutar verificaciones o subir
cambios en tus repositorios de estudiante (Ventas y Operaciones), asegúrate de que ambos contengan una copia actualizada en la
ruta `students/{slug}/sources/orders_seed.csv`.

Sigue estos pasos:

1. **Obtener el archivo desde el repositorio central.**
   - Si estás en el mismo nivel de carpetas, puedes ejecutar: `cp PortalKids/sources/orders_seed.csv ventas/students/{slug}/sources/orders_seed.csv`.
   - Repite el comando para el repositorio de Operaciones cambiando la ruta de destino.
   - Si prefieres descargarlo manualmente, abre `sources/orders_seed.csv` desde el repositorio central en tu editor y guarda una
     copia en cada repositorio de estudiante.
2. **Crear carpetas faltantes.** Si `students/{slug}/sources/` no existe, créala antes de copiar el archivo (por ejemplo,
   `mkdir -p students/{slug}/sources`).
3. **Verificar la ubicación.** Dentro de cada repositorio (Ventas y Operaciones) ejecuta
   `ls students/{slug}/sources/orders_seed.csv` para confirmar que el archivo quedó en el lugar correcto.
4. **Confirmar antes de hacer commit/push.** Repite la verificación cada vez que actualices el archivo central o cambies de slug.

> Reemplaza `{slug}` por tu identificador real de estudiante. Mantener este archivo sincronizado evita errores de verificación en
> la misión M3.
