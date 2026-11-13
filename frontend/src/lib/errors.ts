// SPDX-License-Identifier: AGPL-3.0-or-later
// Turns API error codes into messages in the current language.
import { ApiError } from '#lib/api.js';
import { m } from '#lib/paraglide/messages.js';

export function errorMessage(error: unknown): string {
	if (!(error instanceof ApiError)) return m.error_unexpected();
	switch (error.code) {
		case 'app_unreachable':
			return m.error_app_unreachable();
		case 'not_authenticated':
			return m.error_not_authenticated();
		case 'secret_key_missing':
			return m.error_secret_key_missing();
		case 'not_the_app_user':
			return m.error_not_the_app_user();
		case 'immich_unreachable':
			return m.error_immich_unreachable();
		case 'immich_invalid_credentials':
			return m.error_immich_invalid_credentials();
		case 'immich_invalid_api_key':
			return m.error_immich_invalid_api_key();
		case 'immich_password_login_failed':
			return m.error_immich_password_login_failed();
		case 'immich_unsupported_version':
			return m.error_immich_unsupported_version({ version: String(error.params.version ?? '?') });
		case 'immich_error':
			return m.error_immich_error();
		case 'cannot_write':
			return m.error_cannot_write();
		case 'sign_in_again':
			return m.error_sign_in_again();
		case 'already_in_a_group':
			return m.people_invitation_blocked();
		case 'show_not_found':
			return m.error_show_not_found();
		default:
			return m.error_unexpected();
	}
}
