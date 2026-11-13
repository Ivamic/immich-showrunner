// SPDX-License-Identifier: AGPL-3.0-or-later
// Fails if any installed npm package has a license that is not on the allowlist
// (licenses compatible with AGPL-3.0-or-later).
import { execSync } from 'node:child_process';

const allowed = new Set([
	'0BSD',
	'Apache-2.0',
	'Apache-2.0 WITH LLVM-exception',
	'BlueOak-1.0.0',
	'BSD-2-Clause',
	'BSD-3-Clause',
	'CC0-1.0',
	'CC-BY-4.0',
	'ISC',
	'MIT',
	'MIT-0',
	'MPL-2.0',
	'Python-2.0',
	'Unlicense'
]);

const output = execSync('pnpm licenses list --json', { encoding: 'utf-8' });
const byLicense = JSON.parse(output);

// SPDX expressions like "(MIT OR Apache-2.0)" pass if any alternative is allowed.
const isAllowed = (license) =>
	license
		.replace(/^\((.*)\)$/, '$1')
		.split(/\s+OR\s+/)
		.some((part) => allowed.has(part.trim()));

const rejected = Object.entries(byLicense)
	.filter(([license]) => !isAllowed(license))
	.flatMap(([license, packages]) =>
		packages.map((p) => `${p.name}@${p.versions.join(',')}: ${license}`)
	);

if (rejected.length > 0) {
	console.error('Packages with licenses that are not on the allowlist:');
	for (const line of rejected) console.error(`  ${line}`);
	process.exit(1);
}
console.log(`License check passed (${Object.keys(byLicense).length} license groups).`);
