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

export type SeasonMode = 'year' | 'single';

export interface ShowSummary {
	album_id: string;
	album_name: string;
	title: string;
	title_edited: boolean;
	hidden: boolean;
	season_mode: SeasonMode;
	episodes: number;
	cover_asset_id: string | null;
}

export interface Episode {
	asset_id: string;
	file_name: string;
	filmed_at: string;
	season: number;
	/** 0 for a hidden episode. */
	number: number;
	title: string;
	auto_title: string;
	title_edited: boolean;
	plot: string;
	auto_plot: string;
	plot_edited: boolean;
	moved: boolean;
	hidden: boolean;
}

export interface ShowDetail extends ShowSummary {
	episode_list: Episode[];
}

export const getShows = () => request<ShowSummary[]>('GET', '/shows');
export const getShow = (id: string) => request<ShowDetail>('GET', `/shows/${id}`);
export const editShow = (
	id: string,
	patch: { title?: string | null; hidden?: boolean; season_mode?: SeasonMode }
) => request<ShowSummary>('PATCH', `/shows/${id}`, patch);
/** A field set to null goes back to what Immich says (`sort_at: null`: the order of filming). */
export const editEpisode = (
	show: string,
	episode: string,
	patch: { title?: string | null; plot?: string | null; hidden?: boolean; sort_at?: null }
) => request<void>('PATCH', `/shows/${show}/episodes/${episode}`, patch);
export const moveEpisode = (
	show: string,
	episode: string,
	place: { after?: string; before?: string }
) => request<void>('POST', `/shows/${show}/episodes/${episode}/move`, place);
export const thumbnailUrl = (assetId: string) => `/api/thumbnails/${assetId}`;

export const getStatus = () => request<Status>('GET', '/status');
/** A full pass right away; `force` carries out a mass removal that the last pass held. */
export const syncNow = (force = false) => request<void>('POST', '/sync', { force });
