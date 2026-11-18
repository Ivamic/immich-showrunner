<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- The pictures of a show: what the media servers have now, other pictures to look at before
     they are made (another style, other frames, the cover of the album), and keeping them as
     they are. -->
<script lang="ts">
	import {
		applyArtwork,
		freezeArtwork,
		getArtwork,
		getStyles,
		previewArtwork,
		thumbnailUrl,
		type Artwork,
		type ArtworkChange,
		type ArtworkKind,
		type ArtworkPreview,
		type Frozen,
		type Style
	} from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import { getLocale } from '#lib/paraglide/runtime.js';
	import Dialog from '#lib/ui/Dialog.svelte';
	import Icon from '#lib/ui/Icon.svelte';

	let { show, cover }: { show: string; cover: string | null } = $props();

	let art = $state<Artwork | null>(null);
	let styles = $state<Style[]>([]);
	let error = $state<string | null>(null);
	let busy = $state(false);
	let saved = $state(false);
	let look = $state<{ change: ArtworkChange; preview: ArtworkPreview | null } | null>(null);
	let seen = $state<string[]>([]);

	async function load() {
		try {
			[art, styles] = await Promise.all([getArtwork(show), getStyles()]);
			error = null;
		} catch (e) {
			error = errorMessage(e);
		}
	}

	$effect(() => {
		if (show) load();
	});

	const styleName = (id: string | null) => {
		const style = styles.find((s) => s.id === id);
		return style ? (style.names[getLocale()] ?? style.names.en ?? style.id) : '';
	};

	const picture = (kind: ArtworkKind) => art?.pictures.find((p) => p.kind === kind)?.url;
	const seasons = $derived(
		(art?.pictures ?? [])
			.filter((p) => p.kind === 'season_poster')
			.sort((a, b) => (a.season ?? 0) - (b.season ?? 0))
	);

	/** Draws other pictures for a look; "one more" asks again from the last one shown. */
	async function open(change: ArtworkChange, again = false) {
		const current = again && look?.preview ? look.preview.choice : null;
		if (!again) seen = art?.style_id ? [art.style_id] : [];
		look = { change, preview: null };
		busy = true;
		try {
			const preview = await previewArtwork(show, change, current, seen);
			look = { change, preview };
			if (!seen.includes(preview.choice.style_id)) seen = [...seen, preview.choice.style_id];
			error = null;
		} catch (e) {
			look = null;
			error = errorMessage(e);
		} finally {
			busy = false;
		}
	}

	async function apply() {
		const choice = look?.preview?.choice;
		look = null;
		if (!choice) return;
		await save(() => applyArtwork(show, choice));
	}

	async function save(action: () => Promise<unknown>) {
		busy = true;
		try {
			await action();
			await load();
			saved = true;
			setTimeout(() => (saved = false), 6000);
		} catch (e) {
			error = errorMessage(e);
		} finally {
			busy = false;
		}
	}

	const freezeOptions: [Frozen, () => string][] = [
		['none', m.artwork_frozen_none],
		['show', m.artwork_frozen_show],
		['all', m.artwork_frozen_all]
	];
</script>

<section class="artwork">
	<div class="head">
		<h2>{m.artwork_heading()}</h2>
		{#if art?.style_id}<span class="style"
				>{m.artwork_style({ name: styleName(art.style_id) })}</span
			>{/if}
	</div>

	{#if error}
		<div class="st-banner st-banner--danger" role="alert">
			<Icon name="circle-alert" /><span class="st-banner__body">{error}</span>
		</div>
	{/if}
	{#if saved}
		<div class="st-banner st-banner--success" role="status">
			<Icon name="circle-check" /><span class="st-banner__body">{m.artwork_saved()}</span>
		</div>
	{/if}

	{#if art}
		{#if art.pictures.length === 0}
			<p class="hint">{m.artwork_none_yet()}</p>
		{:else}
			<div class="pictures">
				{#if picture('series_poster')}
					<figure class="poster">
						<img src={picture('series_poster')} alt="" />
						<figcaption>{m.artwork_poster()}</figcaption>
					</figure>
				{/if}
				<div class="wide">
					{#if picture('landscape')}
						<figure>
							<img src={picture('landscape')} alt="" />
							<figcaption>{m.artwork_landscape()}</figcaption>
						</figure>
					{/if}
					{#if picture('fanart')}
						<figure>
							<img src={picture('fanart')} alt="" />
							<figcaption>{m.artwork_fanart()}</figcaption>
						</figure>
					{/if}
					{#if picture('logo')}
						<figure>
							<img class="logo" src={picture('logo')} alt="" />
							<figcaption>{m.artwork_logo()}</figcaption>
						</figure>
					{/if}
				</div>
			</div>
			{#if seasons.length}
				<div class="seasons">
					{#each seasons as season (season.season)}
						<figure>
							<img src={season.url} alt="" loading="lazy" />
							<figcaption>{season.season}</figcaption>
						</figure>
					{/each}
				</div>
			{/if}
		{/if}

		<div class="actions">
			<button type="button" class="st-btn st-btn--sm" disabled={busy} onclick={() => open('style')}>
				<Icon name="layout-grid" />
				{m.artwork_other_style()}
			</button>
			<button
				type="button"
				class="st-btn st-btn--sm"
				disabled={busy}
				onclick={() => open('frames')}
			>
				<Icon name="refresh-cw" />
				{m.artwork_other_frames()}
			</button>
			{#if art.use_cover}
				<button
					type="button"
					class="st-btn st-btn--sm"
					disabled={busy}
					onclick={() => open('drawn')}
				>
					{m.artwork_drawn_poster()}
				</button>
			{:else if cover}
				<button
					type="button"
					class="st-btn st-btn--sm"
					disabled={busy}
					onclick={() => open('cover')}
				>
					{m.artwork_cover_poster()}
				</button>
			{/if}
		</div>

		<div class="row">
			<span class="st-field__label">{m.artwork_frozen_label()}</span>
			<div class="st-seg" role="radiogroup" aria-label={m.artwork_frozen_label()}>
				{#each freezeOptions as [value, label] (value)}
					<button
						type="button"
						role="radio"
						aria-checked={art.frozen === value}
						disabled={busy}
						onclick={() => save(() => freezeArtwork(show, value))}
					>
						{label()}
					</button>
				{/each}
			</div>
		</div>
		<p class="hint">{m.artwork_frozen_hint()}</p>
	{/if}
</section>

{#if look}
	<Dialog wide title={m.artwork_look_title()} onclose={() => (look = null)}>
		{#if !look.preview}
			<p class="drawing"><Icon name="loader-circle" /> {m.artwork_drawing()}</p>
		{:else}
			{@const next = look.preview}
			{#if art?.frozen !== 'none'}
				<div class="st-banner st-banner--warning" role="note">
					<Icon name="triangle-alert" /><span class="st-banner__body"
						>{m.artwork_frozen_note()}</span
					>
				</div>
			{/if}
			<p class="hint">
				{m.artwork_style({ name: styleName(next.choice.style_id) })}
			</p>
			<div class="compare">
				<span class="label">{m.artwork_now()}</span>
				<span class="label">{m.artwork_then()}</span>
				{#each ['series_poster', 'landscape', 'fanart'] as const as kind (kind)}
					<div class="cell" class:tall={kind === 'series_poster'}>
						{#if kind === 'series_poster' && art?.use_cover && cover}
							<img src={thumbnailUrl(cover)} alt="" />
						{:else if picture(kind)}
							<img src={picture(kind)} alt="" />
						{/if}
					</div>
					<div class="cell" class:tall={kind === 'series_poster'}>
						{#if kind === 'series_poster' && next.choice.use_cover && cover}
							<img src={thumbnailUrl(cover)} alt="" />
						{:else if next.pictures[kind]}
							<img src={next.pictures[kind]} alt="" />
						{/if}
					</div>
				{/each}
			</div>
		{/if}
		{#snippet footer()}
			{#if look && look.change !== 'cover' && look.change !== 'drawn'}
				<button
					type="button"
					class="st-btn st-btn--ghost"
					disabled={busy}
					onclick={() => look && open(look.change, true)}
				>
					{m.artwork_one_more()}
				</button>
			{/if}
			<button type="button" class="st-btn" onclick={() => (look = null)}>{m.cancel()}</button>
			<button
				type="button"
				class="st-btn st-btn--primary"
				disabled={busy || !look?.preview}
				onclick={apply}
			>
				{m.artwork_apply()}
			</button>
		{/snippet}
	</Dialog>
{/if}

<style>
	.artwork {
		margin-top: var(--space-8);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.head {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	h2 {
		font-size: var(--text-lg);
		margin: 0;
	}
	.style,
	.hint {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		margin: 0;
	}
	figure {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	figcaption {
		color: var(--color-text-muted);
		font-size: var(--text-xs, 0.75rem);
	}
	img {
		display: block;
		width: 100%;
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
	}
	.pictures {
		display: grid;
		grid-template-columns: minmax(8rem, 12rem) 1fr;
		gap: var(--space-4);
		align-items: start;
	}
	.poster img {
		aspect-ratio: 2 / 3;
		object-fit: cover;
	}
	.wide {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
		gap: var(--space-3);
	}
	.wide img {
		aspect-ratio: 16 / 9;
		object-fit: cover;
	}
	.wide img.logo {
		object-fit: contain;
		background: repeating-conic-gradient(#3a3a3a 0 25%, #2c2c2c 0 50%) 0 0 / 16px 16px;
	}
	.seasons {
		display: flex;
		gap: var(--space-2);
		overflow-x: auto;
		padding-bottom: var(--space-1);
	}
	.seasons figure {
		flex: 0 0 5.5rem;
	}
	.seasons img {
		aspect-ratio: 2 / 3;
		object-fit: cover;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	.drawing {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 6rem;
	}
	.compare {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-3);
		align-items: start;
	}
	.label {
		font-weight: 600;
	}
	.cell img {
		aspect-ratio: 16 / 9;
		object-fit: cover;
	}
	.cell.tall {
		max-width: 12rem;
	}
	.cell.tall img {
		aspect-ratio: 2 / 3;
	}
	@media (max-width: 40rem) {
		.pictures {
			grid-template-columns: 1fr;
		}
		.poster {
			max-width: 12rem;
		}
	}
</style>
