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
const { parseMissionExtrasDisplaySections, normalizeMissionExtraHeading } = require('../assets/js/main.js');

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

console.log('Mission extras parser fixture checks passed.');
