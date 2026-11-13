// SPDX-License-Identifier: AGPL-3.0-or-later
// Who is signed in. Filled by the root layout; `checked` is false until the first answer.
import type { Me } from '#lib/api.js';

export const session = $state<{ user: Me | null; checked: boolean }>({
	user: null,
	checked: false
});
