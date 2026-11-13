// SPDX-License-Identifier: AGPL-3.0-or-later
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const messagesDir = join(import.meta.dirname, '../../messages');
const baseLocale = 'en';

function load(locale: string): Record<string, string> {
	const raw = JSON.parse(readFileSync(join(messagesDir, `${locale}.json`), 'utf-8'));
	delete raw.$schema;
	return raw;
}

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((x) => x[1]).sort();

describe('translations', () => {
	const base = load(baseLocale);
	const others = readdirSync(messagesDir)
		.map((file) => file.replace(/\.json$/, ''))
		.filter((locale) => locale !== baseLocale);

	it.each(others)('%s has exactly the same keys as en', (locale) => {
		expect(Object.keys(load(locale)).sort()).toEqual(Object.keys(base).sort());
	});

	it.each(others)('%s uses the same placeholders as en', (locale) => {
		const messages = load(locale);
		for (const [key, text] of Object.entries(base)) {
			expect(placeholders(messages[key] ?? ''), key).toEqual(placeholders(text));
		}
	});
});
