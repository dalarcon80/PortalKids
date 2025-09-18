import React from 'react';

const LandingPage = () => (
  <main id="content">
    <section className="mission mission-story">
      <div className="mission-section mission-section--intro">
        <h2>Historia</h2>
        <p>
          Bloque 0 es el briefing oficial del Portal de Misiones BlockCorp. El Mentor Byte convoca a todas las nuevas personas
          agentes en la Sala del Núcleo para revelar qué se protege realmente detrás de cada puerta.
        </p>
        <p>
          La ciudad de Cubria depende de que el flujo de datos nunca se detenga. Los cofres con pedidos, inventarios y métricas
          llegan cada minuto, pero un sabotaje reciente dejó la red vulnerable y nuestro equipo quedó corto de manos.
        </p>
        <p>
          Byte recorre el mapa holográfico y explica que antes de tocar una sola misión debes conocer el terreno: qué
          herramientas portarás, qué ruta seguirás y cómo presentarás tus avances para recibir ayuda.
        </p>
        <p>
          Tu objetivo en este bloque es alinear expectativas, comprender cómo se desbloquean las misiones y preparar la
          documentación que usarás durante toda la campaña.
        </p>
      </div>
    </section>
    <section className="mission mission-map">
      <div className="mission-section">
        <h2>Mapa de misiones</h2>
        <p>
          Estas son las estaciones de la campaña. Cada puerta se abre cuando completas la anterior o cuando tu rol lo permite.
        </p>
        <ol>
          <li>
            <strong>Bloque 0 — Briefing del Portal:</strong> Conoce la historia, reglas y documentación base.
          </li>
          <li>
            <strong>M1 — La Puerta de la Base:</strong> Configura VS Code, Python y deja el taller listo.
          </li>
          <li>
            <strong>M2 — Despierta a tu Aliado:</strong> Prepara el entorno virtual y verifica dependencias.
          </li>
          <li>
            <strong>M3 — Cofres CSV y DataFrames:</strong> Extrae y transforma los primeros cofres de datos.
          </li>
          <li>
            <strong>M4 — Bronze:</strong> Automatiza la ingesta y crea una copia fiel de los insumos.
          </li>
          <li>
            <strong>M5 — Silver:</strong> Limpia, tipifica y documenta cada transformación.
          </li>
          <li>
            <strong>M6 Ventas / M6 Operaciones:</strong> Une fuentes, calcula métricas y construye tableros por rol.
          </li>
          <li>
            <strong>M7 — Consejo de la Tienda:</strong> Entrega el informe final y defiende tus decisiones.
          </li>
        </ol>
      </div>
    </section>
    <section className="mission mission-rules">
      <div className="mission-section">
        <h2>Reglas del portal</h2>
        <ol>
          <li>Sigue la narrativa y respeta exactamente los entregables de cada contrato.</li>
          <li>Trabaja siempre en tu repositorio asignado y mantén tu slug sin espacios ni tildes.</li>
          <li>Usa la plantilla de Pull Request para solicitar revisión y documentar evidencias.</li>
          <li>Comparte comandos, capturas o logs cuando pidas ayuda para que el mentor pueda replicar el escenario.</li>
          <li>El verificador automático valida rutas y nombres; no modifiques scripts salvo que la misión lo pida.</li>
          <li>Protege tus credenciales y jamás publiques tokens en los repositorios.</li>
        </ol>
      </div>
    </section>
    <section className="mission mission-checklist">
      <div className="mission-section">
        <h2>Checklist del Bloque 0</h2>
        <ul>
          <li>Leí el briefing completo y entiendo el objetivo general del Bloque 0.</li>
          <li>Identifiqué qué misiones corresponden a mi rol (Ventas u Operaciones).</li>
          <li>Guardé las reglas clave en mis notas personales del proyecto.</li>
          <li>Verifiqué que puedo acceder al portal, al repositorio y al canal de soporte.</li>
          <li>
            Preparé un borrador de la plantilla de Pull Request en mi carpeta <code>docs/</code>.
          </li>
        </ul>
      </div>
    </section>
    <section className="mission mission-pr-template">
      <div className="mission-section">
        <h2>Plantilla del Pull Request</h2>
        <p>Usa este formato cada vez que envíes avances o entregas finales al mentor.</p>
        <pre>
          <code>{`## Resumen
- Objetivo de la misión y cambios clave.
- Riesgos o bloqueos que el revisor debe conocer.

## Checklist
- [ ] Verifiqué la misión localmente e indico el comando utilizado.
- [ ] Subí los archivos solicitados en docs/ o reports/.
- [ ] Solicité revisión cuando todo quedó listo.

## Evidencia
- Capturas, logs o enlaces relevantes.

## Notas
- Dudas o próximos pasos.`}</code>
        </pre>
      </div>
    </section>
  </main>
);

export default LandingPage;
