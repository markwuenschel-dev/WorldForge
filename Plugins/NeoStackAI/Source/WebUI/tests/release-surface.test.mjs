import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const i18nSource = await readFile(new URL('../src/lib/i18n.ts', import.meta.url), 'utf8');
const settingsSource = await readFile(
	new URL('../src/lib/components/SettingsPanel.svelte', import.meta.url),
	'utf8'
);
const layoutSource = await readFile(
	new URL('../src/routes/+layout.svelte', import.meta.url),
	'utf8'
);

test('only complete locales are advertised and accepted', () => {
	assert.match(i18nSource, /releasedLocales = \['en'\]/);
	assert.match(i18nSource, /locale\.set\(sanitizeLocale\(value\)\)/);
	assert.match(settingsSource, /#each releasedLocales as currentLocale/);
	assert.doesNotMatch(settingsSource, /#each locales as currentLocale/);
});

test('startup fonts are limited to the released Latin surface', () => {
	assert.equal(
		[...layoutSource.matchAll(/@fontsource\/[^']+\.css/g)].length,
		6,
		'only the required Geist weights should be bundled'
	);
	assert.doesNotMatch(layoutSource, /@fontsource\/geist\/(?:400|500|600|700)\.css/);
	assert.doesNotMatch(layoutSource, /@fontsource\/geist-mono\/(?:400|500)\.css/);
	assert.match(layoutSource, /@fontsource\/geist\/latin-400\.css/);
	assert.match(layoutSource, /@fontsource\/geist-mono\/latin-400\.css/);
});
