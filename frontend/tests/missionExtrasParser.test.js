const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const fixturePath = path.join(__dirname, 'fixtures', 'm3_display_html.html');
const displayHtml = fs.readFileSync(fixturePath, 'utf8');

const dom = new JSDOM('<!doctype html><html><body></body></html>');

global.window = dom.window;
global.document = dom.window.document;
global.Node = dom.window.Node;
global.navigator = dom.window.navigator;

delete require.cache[require.resolve('../assets/js/main.js')];
const {
  parseMissionExtrasDisplaySections,
  normalizeMissionExtraHeading,
  buildMissionVerificationSectionHtml,
  ensureMissionVerificationSection,
} = require('../assets/js/main.js');

const parsed = parseMissionExtrasDisplaySections(displayHtml);
const values = parsed.values || {};
const headings = parsed.headings || {};

assert.ok(
  typeof values.history === 'string' && values.history.includes('El pasillo conduce'),
  'La sección de historia debe contener la narrativa esperada.',
);

assert.ok(
  typeof values.purpose === 'string' && values.purpose.includes('Cargar y entender datos rápidamente'),
  'La sección de propósito debe detectar el bloque «¿Para qué sirve?».',
);

assert.ok(
  typeof values.resources === 'string' && values.resources.toLowerCase().includes('youtube'),
  'La sección de recursos debe capturar el bloque de videos.',
);

assert.ok(
  typeof values.practice_contract_entry === 'string' &&
    values.practice_contract_entry.includes('orders_seed.csv'),
  'El contrato debe incluir la ruta de entrada.',
);

assert.ok(
  typeof values.practice_contract_steps === 'string' &&
    values.practice_contract_steps.toLowerCase().includes('deja tu programa parametrizable'),
  'El contrato debe capturar los pasos «Qué debes hacer hoy».',
);

assert.ok(
  typeof values.practice_contract_expected === 'string' &&
    values.practice_contract_expected.toLowerCase().includes('programa que lee el csv'),
  'El contrato debe capturar el logro esperado.',
);

assert.ok(
  typeof values.practice_contract_outputs === 'string' &&
    values.practice_contract_outputs.includes('docs/m3_practice_output.txt'),
  'El contrato debe capturar los archivos de salida.',
);

assert.ok(
  typeof values.review === 'string' &&
    values.review.includes('df.shape') &&
    values.review.includes("df.columns.tolist()") &&
    values.review.includes('df.head()') &&
    values.review.includes('df.dtypes') &&
    values.review.includes("['order_id', 'customer_id', 'product_id', 'order_date', 'status', 'quantity', 'unit_price']") &&
    values.review.includes('(3, 7)') &&
    values.review.includes('Checklist antes de subir cambios') &&
    values.review.includes('students/{slug}/sources/orders_seed.csv') &&
    values.review.includes('docs/orders_seed_instructions.md'),
  'La sección de verificación debe guiar sobre orders_seed.csv y enlazar al instructivo.',
);

assert.strictEqual(
  headings.practice_contract,
  'Práctica — Contrato',
  'El título del contrato debe conservarse.',
);

assert.strictEqual(
  normalizeMissionExtraHeading('Entrada:'),
  'entrada',
  'La normalización debe ignorar los dos puntos finales.',
);

const verificationHtml = buildMissionVerificationSectionHtml();

assert.ok(
  typeof verificationHtml === 'string' && verificationHtml.includes('Verificar y Entregar Misión'),
  'El HTML de verificación debe incluir el texto del botón requerido.',
);

const missionContainer = dom.window.document.createElement('main');
missionContainer.innerHTML = '<section class="mission"><h2>Misiones</h2></section>';

const ensuredElements = ensureMissionVerificationSection(missionContainer);

assert.ok(ensuredElements.button, 'La verificación debe crear el botón cuando no existe.');
assert.ok(ensuredElements.result, 'La verificación debe crear el contenedor de resultados cuando no existe.');
assert.strictEqual(
  ensuredElements.button.textContent,
  'Verificar y Entregar Misión',
  'El botón generado debe contener la etiqueta esperada.',
);

const repeatedCall = ensureMissionVerificationSection(missionContainer);

assert.strictEqual(
  repeatedCall.button,
  ensuredElements.button,
  'Las llamadas posteriores deben reutilizar el mismo botón.',
);
assert.strictEqual(
  repeatedCall.result,
  ensuredElements.result,
  'Las llamadas posteriores deben reutilizar el mismo contenedor de resultados.',
);

console.log('Mission extras parser fixture checks passed.');
