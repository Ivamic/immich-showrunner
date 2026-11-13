// SPDX-License-Identifier: AGPL-3.0-or-later
// Calls to the API of the app. Errors come as { code, params }; the page translates the code.

export class ApiError extends Error {
	constructor(
		public status: number,
		public code: string,
		public params: Record<string, unknown> = {}
	) {
		super(code);
	}
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
	let response: Response;
	try {
		response = await fetch(`/api${path}`, {
			method,
			headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
			body: body === undefined ? undefined : JSON.stringify(body)
		});
	} catch {
		throw new ApiError(0, 'app_unreachable');
	}
	if (!response.ok) {
		let code = 'unexpected';
		let params: Record<string, unknown> = {};
		try {
			const data = await response.json();
			if (typeof data?.code === 'string') code = data.code;
			if (data?.params && typeof data.params === 'object') params = data.params;
		} catch {
			// not JSON: keep the generic code
		}
		throw new ApiError(response.status, code, params);
	}
	if (response.status === 204) return undefined as T;
	return (await response.json()) as T;
}

export interface Me {
	name: string;
	email: string;
	/** Whether the page can change things in Immich for the user (names of people, invitations). */
	can_write: boolean;
}

export const getMe = () => request<Me>('GET', '/auth/me');
export const loginWithPassword = (email: string, password: string) =>
	request<Me>('POST', '/auth/login', { email, password });
export const loginWithKey = (apiKey: string) =>
	request<Me>('POST', '/auth/login/key', { api_key: apiKey });
export const logout = () => request<void>('POST', '/auth/logout');

export interface Health {
	version: string;
	ok: boolean | null;
	held: boolean;
	error: string;
	shows: number;
	jellyfin_pending: number;
	last_sync_at: string | null;
	last_full_sync_at: string | null;
	notes: string[];
}

export const getHealth = () => request<Health>('GET', '/health');

export interface Status {
	version: string;
	running: boolean;
	ok: boolean | null;
	error: string;
	errors: string[];
	held: boolean;
	held_links_removed: number;
	held_links_before: number;
	shows: number;
	jellyfin_pending: number;
	created: number;
	replaced: number;
	removed: number;
	last_sync_at: string | null;
	last_full_sync_at: string | null;
	sync_interval_seconds: number;
	skipped: { album: string; file: string; reason: string }[];
	pictures_failed: string[];
	foreign: { path: string; detail: string }[];
}

export const getStatus = () => request<Status>('GET', '/status');
/** A full pass right away; `force` carries out a mass removal that the last pass held. */
export const syncNow = (force = false) => request<void>('POST', '/sync', { force });
