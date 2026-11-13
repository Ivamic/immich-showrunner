// SPDX-License-Identifier: AGPL-3.0-or-later
import type { Locale } from '#lib/paraglide/runtime.js';

/** Languages by their own names, never flags; shown in their own language, so not translated. */
export const LANGUAGE_NAMES: Record<Locale, string> = {
	en: 'English',
	de: 'Deutsch',
	fr: 'Français',
	it: 'Italiano',
	ru: 'Русский'
};
