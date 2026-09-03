import prettier from 'eslint-config-prettier';
import path from 'node:path';
import { includeIgnoreFile } from '@eslint/compat';
import js from '@eslint/js';
import svelte from 'eslint-plugin-svelte';
import { defineConfig } from 'eslint/config';
import globals from 'globals';
import ts from 'typescript-eslint';
import svelteConfig from './svelte.config.js';

const gitignorePath = path.resolve(import.meta.dirname, '.gitignore');

export default defineConfig(
	includeIgnoreFile(gitignorePath),
	js.configs.recommended,
	...ts.configs.recommended,
	...svelte.configs.recommended,
	prettier,
	...svelte.configs.prettier,
	{
		languageOptions: { globals: { ...globals.browser, ...globals.node } },
		rules: {
			// typescript-eslint strongly recommend that you do not use the no-undef lint rule on TypeScript projects.
			// see: https://typescript-eslint.io/troubleshooting/faqs/eslint/#i-get-errors-from-the-no-undef-rule-about-global-variables-not-being-defined-even-though-there-are-no-typescript-errors
			'no-undef': 'off'
		}
	},
	{
		files: ['**/*.svelte', '**/*.svelte.ts', '**/*.svelte.js'],
		languageOptions: {
			parserOptions: {
				projectService: true,
				extraFileExtensions: ['.svelte'],
				parser: ts.parser,
				svelteConfig
			}
		}
	},
	{
		files: ['src/lib/bridge.ts', 'src/lib/relay.ts'],
		rules: {
			// UE generates its bridge surface at runtime and relay payloads arrive as
			// untyped JSON. Keep the dynamic type at these transport boundaries.
			'@typescript-eslint/no-explicit-any': 'off'
		}
	},
	{
		files: [
			'src/lib/components/AgentRegistry.svelte',
			'src/lib/components/ui/button/button.svelte'
		],
		rules: {
			// Both components intentionally accept external URLs; Svelte's resolve()
			// helper is only appropriate for app-relative navigation.
			'svelte/no-navigation-without-resolve': 'off'
		}
	}
);
