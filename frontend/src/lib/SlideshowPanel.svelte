<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- The slideshows of a show (D-103): on or off for this album, the mood of the music, other
     music, and the slideshows of its years with their state, a look at each one drawn and its
     file to save; the one being drawn now, and the ones drawn before, kept in the trash (D-105). -->
<script lang="ts">
	import {
		MOODS,
		getAlbumSlideshow,
		getSlideshowSettings,
		getSlideshowTrash,
		putAlbumSlideshow,
		slideshowVideoUrl,
		trashedSlideshowUrl,
		type AlbumSlideshow,
		type Mood,
		type Slideshow,
		type SlideshowSettings,
		type TrashedSlideshow
	} from '#lib/api.js';
	import SlideshowProgress from '#lib/SlideshowProgress.svelte';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import Dialog from '#lib/ui/Dialog.svelte';
	import Icon from '#lib/ui/Icon.svelte';
	import StatusBadge from '#lib/ui/StatusBadge.svelte';

	let { show }: { show: string } = $props();

	/** How often the page looks again while a slideshow waits to be drawn. */
	const POLL_MS = 20000;

	let album = $state<AlbumSlideshow | null>(null);
	let settings = $state<SlideshowSettings | null>(null);
	let error = $state<string | null>(null);
	let saved = $state(false);
	let busy = $state(false);
	let watching = $state<Slideshow | null>(null);
	let trashed = $state<TrashedSlideshow[]>([]);

	async function load() {
		try {
			[album, settings, trashed] = await Promise.all([
				getAlbumSlideshow(show),
				getSlideshowSettings(),
				getSlideshowTrash(show).catch(() => [])
			]);
			error = null;
		} catch (e) {
			error = errorMessage(e);
		}
	}

	$effect(() => {
		if (show) load();
	});

	$effect(() => {
		if (!album?.slideshows.some((s) => s.state !== 'drawn')) return;
		const timer = setTimeout(load, POLL_MS);
		return () => clearTimeout(timer);
	});

	async function change(what: {
		enabled?: boolean | null;
		mood?: Mood | null;
		other_music?: boolean;
	}) {
		busy = true;
		try {
			album = await putAlbumSlideshow(show, what);
			saved = true;
			setTimeout(() => (saved = false), 6000);
		} catch (e) {
			error = errorMessage(e);
		} finally {
			busy = false;
		}
	}

	const moodName = (mood: string | null) =>
		mood
			? ({
					calm: m.mood_calm(),
					wistful: m.mood_wistful(),
					bright: m.mood_bright(),
					upbeat: m.mood_upbeat(),
					solemn: m.mood_solemn()
				}[mood] ?? mood)
			: '';
	const duration = (seconds: number) =>
		`${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;
	const on = $derived(album?.enabled !== false);
	const megabytes = (bytes: number) => (bytes / 1e6).toFixed(1);
	const day = (iso: string) => new Date(iso).toLocaleDateString();

	/** "left out: near copies 840, over the limit of a scene 346, …; 20 photos not looked at yet" */
	function reasons(s: Slideshow): string {
		const r = s.report.reasons ?? {};
		const parts = [
			[r.series, m.album_slideshow_reason_series()],
			[r.scene, m.album_slideshow_reason_scene()],
			[r.junk, m.album_slideshow_reason_junk()],
			[r.poor, m.album_slideshow_reason_poor()]
		]
			.filter(([count]) => count)
			.map(([count, label]) => `${label} ${count}`);
		const text = parts.length ? m.album_slideshow_left_out({ reasons: parts.join(', ') }) : '';
		const waiting = s.report.not_looked
			? m.album_slideshow_not_looked({ count: String(s.report.not_looked) })
			: '';
		return [text, waiting].filter(Boolean).join('; ');
	}
</script>

<section class="slideshows">
	<h2>{m.album_slideshow_heading()}</h2>

	{#if error}
		<div class="st-banner st-banner--danger" role="alert">
			<Icon name="circle-alert" /><span class="st-banner__body">{error}</span>
		</div>
	{/if}
	{#if saved}
		<div class="st-banner st-banner--success" role="status">
			<Icon name="circle-check" /><span class="st-banner__body">{m.album_slideshow_saved()}</span>
		</div>
	{/if}
	<SlideshowProgress {show} onchange={load} />
	{#if settings && !settings.enabled}
		<p class="hint">{m.album_slideshow_off_global()}</p>
	{/if}

	{#if album}
		<div class="choices">
			<label class="st-check">
				<input
					type="checkbox"
					checked={on}
					disabled={busy}
					onchange={(e) => change({ enabled: e.currentTarget.checked ? null : false })}
				/>
				<span>{m.album_slideshow_enabled()}</span>
			</label>
			{#if on}
				<label class="st-field mood">
					<span class="st-field__label">{m.album_slideshow_mood()}</span>
					<select
						class="st-input st-input--select"
						value={album.mood ?? ''}
						disabled={busy}
						onchange={(e) => change({ mood: (e.currentTarget.value || null) as Mood | null })}
					>
						<option value="">
							{album.auto_mood
								? m.album_slideshow_mood_auto({ mood: moodName(album.auto_mood) })
								: m.album_slideshow_mood_auto_unknown()}
						</option>
						{#each MOODS as mood (mood)}
							<option value={mood}>{moodName(mood)}</option>
						{/each}
					</select>
				</label>
				<button
					type="button"
					class="st-btn st-btn--secondary"
					disabled={busy}
					onclick={() => change({ other_music: true })}
				>
					<Icon name="refresh-cw" size={16} />
					{m.album_slideshow_other_music()}
				</button>
			{/if}
		</div>
		{#if on}
			<p class="hint">{m.album_slideshow_wistful_hint()}</p>
			{#if album.slideshows.length === 0}
				<p class="hint">{m.album_slideshow_none()}</p>
			{:else}
				<ul>
					{#each album.slideshows as slideshow (`${slideshow.year}-${slideshow.part}`)}
						<li>
							<div class="about">
								<div class="title">{slideshow.title}</div>
								<div class="meta">
									{m.album_slideshow_info({
										duration: duration(slideshow.seconds),
										photos: String(slideshow.photos),
										left_out: String(slideshow.left_out)
									})}
								</div>
								{#if slideshow.left_out || slideshow.report.not_looked}
									<div class="meta">{reasons(slideshow)}</div>
								{/if}
								{#if slideshow.report.days?.length}
									<details>
										<summary>{m.album_slideshow_days()}</summary>
										<table>
											<thead>
												<tr>
													<th>{m.album_slideshow_day()}</th>
													<th>{m.album_slideshow_col_photos()}</th>
													<th>{m.album_slideshow_col_shown()}</th>
													<th>{m.album_slideshow_reason_series()}</th>
													<th>{m.album_slideshow_reason_scene()}</th>
													<th>{m.album_slideshow_reason_junk()}</th>
													<th>{m.album_slideshow_reason_poor()}</th>
												</tr>
											</thead>
											<tbody>
												{#each slideshow.report.days as day (day.date)}
													<tr>
														<td>{day.date}</td>
														<td>{day.photos}</td>
														<td>{day.shown ?? 0}</td>
														<td>{day.series ?? 0}</td>
														<td>{day.scene ?? 0}</td>
														<td>{day.junk ?? 0}</td>
														<td>{day.poor ?? 0}</td>
													</tr>
												{/each}
											</tbody>
										</table>
									</details>
								{/if}
								{#if slideshow.music.length}
									<div class="meta">
										{m.album_slideshow_music({ music: slideshow.music.join('; ') })}
									</div>
								{/if}
							</div>
							{#if slideshow.state === 'drawn'}
								<StatusBadge tone="success" dot>{m.album_slideshow_state_drawn()}</StatusBadge>
							{:else if slideshow.state === 'older'}
								<StatusBadge tone="info" live>{m.album_slideshow_state_older()}</StatusBadge>
							{:else}
								<StatusBadge tone="neutral">{m.album_slideshow_state_waiting()}</StatusBadge>
							{/if}
							{#if slideshow.state !== 'waiting'}
								<button
									type="button"
									class="st-btn st-btn--sm"
									onclick={() => (watching = slideshow)}
								>
									{m.album_slideshow_watch()}
								</button>
								<!-- eslint-disable svelte/no-navigation-without-resolve -- a file of the API, not a page -->
								<a
									class="st-btn st-btn--sm st-btn--secondary"
									href={slideshowVideoUrl(show, slideshow, true)}
									download
								>
									<Icon name="download" size={16} />
									{m.album_slideshow_download()}
								</a>
								<!-- eslint-enable svelte/no-navigation-without-resolve -->
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		{/if}
		{#if trashed.length}
			<details class="trash">
				<summary>{m.album_slideshow_trash({ count: String(trashed.length) })}</summary>
				<p class="hint">{m.album_slideshow_trash_hint()}</p>
				<ul>
					{#each trashed as item (item.name)}
						<li>
							<div class="about">
								<div>{item.name}</div>
								<div class="meta">
									{m.album_slideshow_trash_item({
										size: megabytes(item.size),
										put: day(item.put_at),
										leaves: day(item.leaves_at)
									})}
								</div>
							</div>
							<!-- eslint-disable svelte/no-navigation-without-resolve -- a file of the API, not a page -->
							<a
								class="st-btn st-btn--sm st-btn--secondary"
								href={trashedSlideshowUrl(show, item)}
								download
							>
								<Icon name="download" size={16} />
								{m.album_slideshow_download()}
							</a>
							<!-- eslint-enable svelte/no-navigation-without-resolve -->
						</li>
					{/each}
				</ul>
			</details>
		{/if}
	{/if}
</section>

{#if watching}
	<Dialog title={watching.title} wide onclose={() => (watching = null)}>
		<!-- svelte-ignore a11y_media_has_caption -->
		<video controls autoplay src={slideshowVideoUrl(show, watching)}></video>
	</Dialog>
{/if}

<style>
	.slideshows {
		margin-top: var(--space-6);
	}
	h2 {
		margin: 0 0 var(--space-2);
	}
	.choices {
		display: flex;
		align-items: flex-end;
		gap: var(--space-4);
		flex-wrap: wrap;
	}
	.mood {
		min-width: 16rem;
	}
	.hint {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		margin: var(--space-2) 0;
	}
	ul {
		list-style: none;
		margin: var(--space-3) 0 0;
		padding: 0;
		max-width: 60rem;
	}
	li {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border);
		flex-wrap: wrap;
	}
	.about {
		flex: 1 1 18rem;
		min-width: 0;
	}
	.title {
		font-weight: 600;
	}
	.meta {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	a.st-btn {
		text-decoration: none;
	}
	.trash {
		margin-top: var(--space-4);
		max-width: 60rem;
	}
	details {
		margin-top: var(--space-1);
		font-size: var(--text-sm);
	}
	summary {
		cursor: pointer;
		color: var(--color-text-muted);
	}
	table {
		border-collapse: collapse;
		margin-top: var(--space-2);
	}
	th,
	td {
		padding: 2px var(--space-2);
		text-align: right;
		border-bottom: 1px solid var(--color-border);
	}
	th:first-child,
	td:first-child {
		text-align: left;
	}
	video {
		display: block;
		width: 100%;
		max-height: 75vh;
		background: #000;
	}
</style>
