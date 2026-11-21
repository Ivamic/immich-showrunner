<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Slideshows (D-103): switched on or off, the credits, the music set and the user's own music. -->
<script lang="ts">
	import {
		MOODS,
		changeTrack,
		getMusic,
		getSlideshowSettings,
		putSlideshowSettings,
		removeTrack,
		trackUrl,
		uploadTrack,
		type Mood,
		type SlideshowSettings,
		type Track,
		type TrackChange
	} from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import Dialog from '#lib/ui/Dialog.svelte';
	import Icon from '#lib/ui/Icon.svelte';
	import SlideshowProgress from '#lib/SlideshowProgress.svelte';

	/** One piece at a time: the one started pauses the one playing. */
	function playAlone(event: Event): void {
		for (const other of document.querySelectorAll('audio')) {
			if (other !== event.currentTarget && !other.paused) other.pause();
		}
	}

	let settings = $state<SlideshowSettings | null>(null);
	let music = $state<Track[] | null>(null);
	let error = $state<string | null>(null);
	let saved = $state(false);
	let busy = $state(false);
	let uploading = $state(false);
	let editing = $state<{ track: Track; change: Required<Omit<TrackChange, 'enabled'>> } | null>(
		null
	);
	let removing = $state<Track | null>(null);
	let fileInput = $state<HTMLInputElement>();

	async function load() {
		try {
			settings = await getSlideshowSettings();
			music = settings.data ? await getMusic() : [];
			error = null;
		} catch (e) {
			error = errorMessage(e);
		}
	}

	$effect(() => {
		load();
	});

	function done() {
		saved = true;
		setTimeout(() => (saved = false), 6000);
	}

	async function setSetting(change: { enabled?: boolean; credits?: boolean }) {
		busy = true;
		try {
			settings = await putSlideshowSettings(change);
			done();
		} catch (e) {
			error = errorMessage(e);
		} finally {
			busy = false;
		}
	}

	async function toggle(track: Track, enabled: boolean) {
		try {
			replace(await changeTrack(track.id, { enabled }));
		} catch (e) {
			error = errorMessage(e);
			await load();
		}
	}

	function replace(track: Track) {
		music = (music ?? []).map((t) => (t.id === track.id ? track : t));
	}

	async function upload(files: FileList | null) {
		if (!files?.length) return;
		uploading = true;
		error = null;
		try {
			for (const file of files) {
				const track = await uploadTrack(file);
				music = [...(music ?? []), track];
			}
		} catch (e) {
			error = errorMessage(e);
		} finally {
			uploading = false;
			if (fileInput) fileInput.value = '';
		}
	}

	function edit(track: Track) {
		editing = {
			track,
			change: {
				title: track.title,
				author: track.author,
				license: track.license,
				link: track.link,
				mood: track.mood_given ? (track.mood as Mood) : null
			}
		};
	}

	async function saveEdit() {
		if (!editing) return;
		try {
			replace(await changeTrack(editing.track.id, editing.change));
			editing = null;
			await load();
		} catch (e) {
			error = errorMessage(e);
		}
	}

	async function confirmRemove() {
		if (!removing) return;
		try {
			await removeTrack(removing.id);
			music = (music ?? []).filter((t) => t.id !== removing?.id);
		} catch (e) {
			error = errorMessage(e);
		} finally {
			removing = null;
		}
	}

	const moodName = (mood: string) =>
		({
			calm: m.mood_calm(),
			wistful: m.mood_wistful(),
			bright: m.mood_bright(),
			upbeat: m.mood_upbeat(),
			solemn: m.mood_solemn()
		})[mood] ?? mood;
	const duration = (seconds: number | null) =>
		seconds === null
			? ''
			: `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;
	const setPieces = $derived((music ?? []).filter((t) => t.kind === 'set'));
	const ownPieces = $derived((music ?? []).filter((t) => t.kind === 'own'));
</script>

<h1>{m.slideshow_heading()}</h1>
<p class="intro">{m.slideshow_intro()}</p>
<SlideshowProgress />

{#if error}
	<div class="st-banner st-banner--danger" role="alert">
		<Icon name="circle-alert" /><span class="st-banner__body">{error}</span>
	</div>
{/if}
{#if saved}
	<div class="st-banner st-banner--success" role="status">
		<Icon name="circle-check" /><span class="st-banner__body">{m.slideshow_saved()}</span>
	</div>
{/if}

{#if settings}
	{#if !settings.data}
		<div class="st-banner st-banner--warning" role="alert">
			<Icon name="triangle-alert" /><span class="st-banner__body">{m.slideshow_no_data()}</span>
		</div>
	{/if}
	<section class="settings">
		<label class="st-check">
			<input
				type="checkbox"
				checked={settings.enabled}
				disabled={busy || !settings.data}
				onchange={(e) => setSetting({ enabled: e.currentTarget.checked })}
			/>
			<span>{m.slideshow_enabled()}</span>
		</label>
		<p class="hint">{m.slideshow_enabled_hint()}</p>
		<label class="st-check">
			<input
				type="checkbox"
				checked={settings.credits}
				disabled={busy}
				onchange={(e) => setSetting({ credits: e.currentTarget.checked })}
			/>
			<span>{m.slideshow_credits()}</span>
		</label>
		<p class="hint">{m.slideshow_credits_hint()}</p>
	</section>
{:else if !error}
	<p>{m.status_loading()}</p>
{/if}

{#if music && settings?.data}
	<section>
		<h2>{m.music_own_heading()}</h2>
		<p class="intro">{m.music_own_intro()}</p>
		<p class="rights">{m.music_own_rights()}</p>
		<input
			bind:this={fileInput}
			type="file"
			accept=".mp3,.m4a,.aac,.ogg,.oga,.opus,.flac,.wav,audio/*"
			multiple
			hidden
			onchange={(e) => upload(e.currentTarget.files)}
		/>
		<button
			type="button"
			class="st-btn st-btn--secondary"
			onclick={() => fileInput?.click()}
			disabled={uploading}
			aria-busy={uploading}
		>
			<Icon name="cloud-upload" size={16} />
			{uploading ? m.music_adding() : m.music_add()}
		</button>
		{#if ownPieces.length === 0}
			<p class="hint">{m.music_none_own()}</p>
		{:else}
			<ul class="tracks">
				{#each ownPieces as track (track.id)}
					{@render row(track)}
				{/each}
			</ul>
		{/if}
	</section>

	<section>
		<h2>{m.music_set_heading()}</h2>
		<p class="intro">{m.music_set_intro()}</p>
		<ul class="tracks">
			{#each setPieces as track (track.id)}
				{@render row(track)}
			{/each}
		</ul>
	</section>
{/if}

{#snippet row(track: Track)}
	<li class:off={!track.enabled}>
		<label class="st-check use">
			<input
				type="checkbox"
				checked={track.enabled}
				onchange={(e) => toggle(track, e.currentTarget.checked)}
				aria-label={m.music_used()}
			/>
		</label>
		<div class="about">
			<div class="title">{track.title}</div>
			<div class="meta">
				{[track.author, track.license, moodName(track.mood), duration(track.seconds)]
					.filter(Boolean)
					.join(' · ')}
			</div>
			{#if track.error}
				<div class="problem">{m.music_not_usable({ reason: track.error })}</div>
			{:else if !track.present}
				<div class="meta">{m.music_set_missing()}</div>
			{/if}
		</div>
		{#if track.present}
			<audio controls preload="none" src={trackUrl(track.id)} onplay={playAlone}></audio>
		{/if}
		{#if track.kind === 'own'}
			<div class="actions">
				<button type="button" class="st-btn st-btn--sm st-btn--ghost" onclick={() => edit(track)}>
					{m.music_edit()}
				</button>
				<button
					type="button"
					class="st-btn st-btn--sm st-btn--ghost"
					onclick={() => (removing = track)}
					aria-label={m.music_remove()}
				>
					<Icon name="trash-2" size={16} />
				</button>
			</div>
		{/if}
	</li>
{/snippet}

{#if editing}
	<Dialog title={editing.track.file_name} onclose={() => (editing = null)}>
		<form
			class="edit"
			onsubmit={(e) => {
				e.preventDefault();
				saveEdit();
			}}
		>
			<label class="st-field">
				<span class="st-field__label">{m.music_title()}</span>
				<input class="st-input" bind:value={editing.change.title} maxlength="300" />
			</label>
			<label class="st-field">
				<span class="st-field__label">{m.music_author()}</span>
				<input class="st-input" bind:value={editing.change.author} maxlength="300" />
			</label>
			<label class="st-field">
				<span class="st-field__label">{m.music_license()}</span>
				<input class="st-input" bind:value={editing.change.license} maxlength="300" />
			</label>
			<label class="st-field">
				<span class="st-field__label">{m.music_link()}</span>
				<input class="st-input" type="url" bind:value={editing.change.link} maxlength="1000" />
			</label>
			<label class="st-field">
				<span class="st-field__label">{m.music_mood()}</span>
				<select class="st-input st-input--select" bind:value={editing.change.mood}>
					<option value={null}>
						{m.music_mood_by_sound({ mood: moodName(editing.track.sound_mood) })}
					</option>
					{#each MOODS as mood (mood)}
						<option value={mood}>{moodName(mood)}</option>
					{/each}
				</select>
			</label>
		</form>
		{#snippet footer()}
			<button type="button" class="st-btn" onclick={() => (editing = null)}>
				{m.music_cancel()}
			</button>
			<button type="button" class="st-btn st-btn--primary" onclick={saveEdit}>
				{m.music_save()}
			</button>
		{/snippet}
	</Dialog>
{/if}

{#if removing}
	<Dialog title={m.music_remove()} onclose={() => (removing = null)}>
		<p>{m.music_remove_confirm({ title: removing.title })}</p>
		{#snippet footer()}
			<button type="button" class="st-btn" onclick={() => (removing = null)}>
				{m.music_cancel()}
			</button>
			<button type="button" class="st-btn st-btn--danger" onclick={confirmRemove}>
				{m.music_remove()}
			</button>
		{/snippet}
	</Dialog>
{/if}

<style>
	h1 {
		margin: 0 0 var(--space-2);
	}
	h2 {
		margin: var(--space-6) 0 var(--space-2);
	}
	.intro {
		color: var(--color-text-muted);
		margin: 0 0 var(--space-3);
		max-width: 48rem;
	}
	.rights {
		margin: 0 0 var(--space-3);
		font-size: var(--text-sm);
	}
	.settings {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		max-width: 48rem;
	}
	.hint {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		margin: 0 0 var(--space-3) var(--space-6);
	}
	.tracks {
		list-style: none;
		margin: var(--space-3) 0 0;
		padding: 0;
		max-width: 60rem;
	}
	.tracks li {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border);
		flex-wrap: wrap;
	}
	.tracks li.off .about {
		opacity: 0.55;
	}
	.about {
		flex: 1 1 16rem;
		min-width: 0;
	}
	.title {
		font-weight: 600;
	}
	.meta {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.problem {
		color: var(--color-danger, #b42318);
		font-size: var(--text-sm);
	}
	audio {
		height: 2rem;
		max-width: 100%;
	}
	.actions {
		display: flex;
		gap: var(--space-1);
	}
	.edit {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-width: min(28rem, 80vw);
	}
</style>
