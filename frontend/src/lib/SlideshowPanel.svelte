<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- The slideshows of a show (D-103): on or off for this album, the mood of the music, other
     music, and the slideshows of its years with their state and a look at each one drawn. -->
<script lang="ts">
	import {
		MOODS,
		getAlbumSlideshow,
		getSlideshowSettings,
		putAlbumSlideshow,
		slideshowVideoUrl,
		type AlbumSlideshow,
		type Mood,
		type Slideshow,
		type SlideshowSettings
	} from '#lib/api.js';
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

	async function load() {
		try {
			[album, settings] = await Promise.all([getAlbumSlideshow(show), getSlideshowSettings()]);
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
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
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
	video {
		display: block;
		width: 100%;
		max-height: 75vh;
		background: #000;
	}
</style>
