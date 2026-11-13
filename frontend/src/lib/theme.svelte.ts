// SPDX-License-Identifier: AGPL-3.0-or-later
// Color theme: the user's choice is kept in the browser; "system" follows the OS. The resolved
// theme is always set as `data-theme` on <html> (app.html does it before the first paint).
export type ThemeChoice = 'light' | 'dark' | 'system';
export type Theme = 'light' | 'dark';

export const THEME_CHOICES: readonly ThemeChoice[] = ['light', 'dark', 'system'];

// Same key as the script in app.html.
const STORAGE_KEY = 'showrunner-theme';

const darkQuery = typeof window === 'undefined' ? null : matchMedia('(prefers-color-scheme: dark)');

function readChoice(): ThemeChoice {
	try {
		const saved = localStorage.getItem(STORAGE_KEY);
		if (saved === 'light' || saved === 'dark') return saved;
	} catch {
		// Storage can be blocked; the system theme is a fine default.
	}
	return 'system';
}

function resolve(choice: ThemeChoice): Theme {
	if (choice !== 'system') return choice;
	return darkQuery?.matches ? 'dark' : 'light';
}

const initial = darkQuery ? readChoice() : 'system';

export const theme = $state<{ choice: ThemeChoice; resolved: Theme }>({
	choice: initial,
	resolved: resolve(initial)
});

function apply() {
	theme.resolved = resolve(theme.choice);
	document.documentElement.dataset.theme = theme.resolved;
}

export function setTheme(choice: ThemeChoice) {
	theme.choice = choice;
	try {
		if (choice === 'system') localStorage.removeItem(STORAGE_KEY);
		else localStorage.setItem(STORAGE_KEY, choice);
	} catch {
		// Not remembered, but applied for this visit.
	}
	apply();
}

darkQuery?.addEventListener('change', () => {
	if (theme.choice === 'system') apply();
});
