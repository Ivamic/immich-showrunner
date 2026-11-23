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
	targets: string[];
	jellyfin_pending: number;
	kodi_pending: number;
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
	targets: string[];
	jellyfin_pending: number;
	kodi_pending: number;
	created: number;
	replaced: number;
	removed: number;
	last_sync_at: string | null;
	last_full_sync_at: string | null;
	sync_interval_seconds: number;
	skipped: { album: string; file: string; reason: string }[];
	pictures_failed: string[];
	foreign: { path: string; detail: string }[];
	slideshows_drawn: number;
	slideshows_waiting: number;
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
	/** The landscape picture the app drew, if any: its version. */
	landscape_version: string | null;
	/** Slideshows drawn so far. */
	slideshows: number;
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
/** `version` (of an edit in Immich) keeps a picture the browser kept from before it away. */
export const thumbnailUrl = (assetId: string, version?: string | null) =>
	`/api/thumbnails/${assetId}` + (version ? `?v=${encodeURIComponent(version)}` : '');
/** The landscape picture the app drew for a show; the version keeps a cached old one away. */
export const landscapeUrl = (show: string, version: string) =>
	`/api/shows/${show}/artwork/file?path=landscape.jpg&v=${encodeURIComponent(version)}`;

export interface Person {
	id: string;
	/** The name for the media server; empty: the person is not in it. */
	name: string;
	owner_names: string[];
	shared_by: string[];
	description: string;
}

export interface People {
	people: Person[];
	can_write: boolean;
	group: string[] | null;
	invitations: { id: string; from_users: string[] }[];
	can_accept: boolean;
}

export const getPeople = () => request<People>('GET', '/people');
export const editPerson = (id: string, patch: { name?: string; description?: string }) =>
	request<void>('PATCH', `/people/${id}`, patch);
export const acceptInvitation = (id: string) =>
	request<void>('POST', `/people/invitations/${id}/accept`);
export const faceUrl = (id: string) => `/api/people/${id}/face`;

export type ArtworkKind = 'series_poster' | 'season_poster' | 'landscape' | 'fanart' | 'logo';

export interface Style {
	id: string;
	/** The name of the style in each language of the page. */
	names: Record<string, string>;
	enabled: boolean;
	/** Shows drawn in this style now. */
	shows: number;
}

export interface ArtworkPicture {
	kind: ArtworkKind;
	season: number | null;
	/** The name of the picture: `series_poster`, `season_poster:2024`… */
	slot: string;
	url: string;
	pinned: boolean;
}

export interface Artwork {
	style_id: string | null;
	seed: number;
	use_cover: boolean;
	slot_seeds: Record<string, number>;
	pictures: ArtworkPicture[];
	/** Videos still to look at: the pictures are drawn from the others for now. */
	waiting: number;
	/** A sync runs or is about to: the pictures may change soon. */
	syncing: boolean;
}

export interface ArtworkChoice {
	style_id: string;
	seed: number;
	use_cover: boolean;
	slot_seeds: Record<string, number>;
}

export interface ArtworkPreview {
	choice: ArtworkChoice;
	/** Data URLs by slot; pinned pictures and the poster given way to the cover are absent. */
	pictures: Record<string, string>;
}

export type ArtworkChange = 'style' | 'frames' | 'cover' | 'drawn';

export interface ArtworkLookRequest {
	change: ArtworkChange;
	/** With `frames`: other frames for this picture only. */
	slot?: string | null;
	/** With `style`: this style instead of one at random. */
	style_id?: string | null;
	current?: ArtworkChoice | null;
	seen_styles?: string[];
}

export const getStyles = () => request<Style[]>('GET', '/styles');
export const editStyle = (id: string, enabled: boolean) =>
	request<void>('PATCH', `/styles/${id}`, { enabled });
export const getArtwork = (show: string) => request<Artwork>('GET', `/shows/${show}/artwork`);
export const previewArtwork = (show: string, look: ArtworkLookRequest) =>
	request<ArtworkPreview>('POST', `/shows/${show}/artwork/preview`, look);
export const applyArtwork = (show: string, choice: ArtworkChoice) =>
	request<void>('PUT', `/shows/${show}/artwork`, choice);
/** Pin or unpin pictures (all of them when `slots` is null); answers with the pinned ones. */
export const pinArtwork = (show: string, slots: string[] | null, pinned: boolean) =>
	request<{ pinned: string[] }>('PUT', `/shows/${show}/artwork/pins`, { slots, pinned });

export const getStatus = () => request<Status>('GET', '/status');
/** A full pass right away; `force` carries out a mass removal that the last pass held. */
export const syncNow = (force = false) => request<void>('POST', '/sync', { force });

// --- slideshows (D-103) -----------------------------------------------------------------------

export type Mood = 'calm' | 'wistful' | 'bright' | 'upbeat' | 'solemn' | 'cinematic';
export const MOODS: Mood[] = ['calm', 'wistful', 'bright', 'upbeat', 'solemn', 'cinematic'];

/** The languages of the text drawn in slideshows (the months of a part, the credits). */
export type SlideshowLanguage = 'en' | 'de' | 'fr' | 'it' | 'ru';
export const SLIDESHOW_LANGUAGES: SlideshowLanguage[] = ['en', 'de', 'fr', 'it', 'ru'];

export interface SlideshowSettings {
	enabled: boolean;
	credits: boolean;
	language: SlideshowLanguage;
	/** Where the photos were taken, under the title (an album may say otherwise). */
	places: boolean;
	/** A folder of slideshows is set: the output folders link to it. */
	folder: boolean;
	/** The data folder is there: without it nothing can be drawn. */
	data: boolean;
}

export const getSlideshowSettings = () => request<SlideshowSettings>('GET', '/slideshow/settings');
export const putSlideshowSettings = (
	change: Partial<Pick<SlideshowSettings, 'enabled' | 'credits' | 'language' | 'places'>>
) => request<SlideshowSettings>('PUT', '/slideshow/settings', change);

export interface Slideshow {
	year: number;
	part: number;
	title: string;
	seconds: number;
	photos: number;
	left_out: number;
	music: string[];
	/** Drawn as planned; an older one shown while this one waits; none yet. */
	state: 'drawn' | 'older' | 'waiting';
	report: SlideshowReport;
}

export interface SlideshowDay {
	date: string;
	photos: number;
	shown?: number;
	junk?: number;
	series?: number;
	poor?: number;
	scene?: number;
}

/** Why photos were left out of a slideshow. */
export interface SlideshowReport {
	reasons?: { junk?: number; series?: number; poor?: number; scene?: number };
	scenes?: number;
	days?: SlideshowDay[];
	/** Photos of the year not looked at yet: they come in later syncs. */
	not_looked?: number;
}

export interface AlbumSlideshow {
	/** False: off for this album; null: as the settings say. */
	enabled: boolean | null;
	mood: Mood | null;
	auto_mood: Mood | null;
	/** The places under the title for this album; null: as the settings say. */
	places: boolean | null;
	slideshows: Slideshow[];
}

export const getAlbumSlideshow = (show: string) =>
	request<AlbumSlideshow>('GET', `/shows/${show}/slideshow`);
export const putAlbumSlideshow = (
	show: string,
	change: {
		enabled?: boolean | null;
		mood?: Mood | null;
		places?: boolean | null;
		other_music?: boolean;
	}
) => request<AlbumSlideshow>('PUT', `/shows/${show}/slideshow`, change);
export const slideshowVideoUrl = (show: string, s: Slideshow, download = false) =>
	`/api/shows/${show}/slideshow/video?year=${s.year}&part=${s.part}${download ? '&download=1' : ''}`;

/** What became of a photo in the plan of a slideshow. */
export interface TracedPhoto {
	id: string;
	taken: string;
	scene: number;
	/** The photo its group of near copies gave way to; null when it is in none. */
	group: string | null;
	fate: 'shown' | 'series' | 'scene' | 'junk' | 'poor' | 'other';
	score: number;
	/** How good the photo is, 0..1 (the score adds a bonus for faces). */
	quality?: number | null;
	faces?: number | null;
	/** How alike it is to the photo of its group, or else to the photo before it. */
	like?: number | null;
	/** The share of the words of screenshots and documents. */
	junk?: number | null;
	/** The edit of the photo in Immich, when it has one: the version of its picture. */
	edit?: string | null;
}

export interface SlideshowPlan {
	year: number;
	part: number;
	title: string;
	photos: TracedPhoto[];
}

export const getSlideshowPlan = (show: string, year: number, part: number) =>
	request<SlideshowPlan>('GET', `/shows/${show}/slideshow/plan?year=${year}&part=${part}`);
export const previewUrl = (assetId: string, version?: string | null) =>
	`/api/thumbnails/${assetId}?size=preview` + (version ? `&v=${encodeURIComponent(version)}` : '');

/** A slideshow drawn before, kept in the trash for a while (D-105). */
export interface TrashedSlideshow {
	name: string;
	size: number;
	put_at: string;
	leaves_at: string;
}

export const getSlideshowTrash = (show: string) =>
	request<TrashedSlideshow[]>('GET', `/shows/${show}/slideshow/trash`);
export const trashedSlideshowUrl = (show: string, t: TrashedSlideshow) =>
	`/api/shows/${show}/slideshow/trash/file?name=${encodeURIComponent(t.name)}`;

/** The slideshow being drawn now. */
export interface SlideshowProgress {
	album_id: string | null;
	show: string;
	title: string;
	started: string;
	/** Slideshows waiting after this one in the pass. */
	queue: number;
	/** Null while the photos are fetched. */
	percent: number | null;
}

export const getSlideshowProgress = () =>
	request<SlideshowProgress | null>('GET', '/slideshow/progress');

export interface Track {
	id: string;
	kind: 'set' | 'own';
	title: string;
	author: string;
	license: string;
	link: string;
	mood: string;
	mood_given: boolean;
	sound_mood: string;
	seconds: number | null;
	enabled: boolean;
	present: boolean;
	error: string | null;
	file_name: string;
}

export interface TrackChange {
	enabled?: boolean;
	mood?: Mood | null;
	title?: string;
	author?: string;
	license?: string;
	link?: string;
}

export const getMusic = () => request<Track[]>('GET', '/music');
export const changeTrack = (id: string, change: TrackChange) =>
	request<Track>('PATCH', `/music/${encodeURI(id)}`, change);
export const removeTrack = (id: string) =>
	request<{ removed: boolean }>('DELETE', `/music/${encodeURI(id)}`);
export const trackUrl = (id: string) => `/api/music/file/${encodeURI(id)}`;

/** The file itself is the body of the request: no form encoding. */
export async function uploadTrack(file: File): Promise<Track> {
	let response: Response;
	try {
		response = await fetch(`/api/music/own/${encodeURIComponent(file.name)}`, {
			method: 'PUT',
			headers: { 'Content-Type': 'application/octet-stream' },
			body: file
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
			// not JSON
		}
		throw new ApiError(response.status, code, params);
	}
	return (await response.json()) as Track;
}
