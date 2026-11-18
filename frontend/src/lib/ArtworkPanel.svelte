<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- The pictures of a show: what the media servers have now, other pictures to look at before
     they are made (another style, other frames for all or for one picture, the cover of the
     album), pinned pictures that stay as they are, and how far the work on them is. -->
<script lang="ts">
	import {
		applyArtwork,
		getArtwork,
		getStyles,
		pinArtwork,
		previewArtwork,
		thumbnailUrl,
		type Artwork,
		type ArtworkLookRequest,
		type ArtworkPicture,
		type ArtworkPreview,
		type Style
	} from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import { getLocale } from '#lib/paraglide/runtime.js';
	import Dialog from '#lib/ui/Dialog.svelte';
	import Icon from '#lib/ui/Icon.svelte';

	let { show, cover }: { show: string; cover: string | null } = $props();

	/** How often the page looks again while a sync draws or the videos are looked at. */
	const POLL_SYNCING_MS = 5000;
	const POLL_WAITING_MS = 20000;
	const LOOK_SLOTS = ['series_poster', 'landscape', 'fanart'] as const;

	let art = $state<Artwork | null>(null);
	let styles = $state<Style[]>([]);
	let error = $state<string | null>(null);
	let busy = $state(false);
	let saved = $state(false);
	let look = $state<{ request: ArtworkLookRequest; preview: ArtworkPreview | null } | null>(null);
	let seen = $state<string[]>([]);
	/** Pictures a sync is drawing again, marked until it is done. */
	let changing = $state<string[]>([]);

	async function load() {
		try {
			[art, styles] = await Promise.all([getArtwork(show), getStyles()]);
			error = null;
			if (!art.syncing) changing = [];
		} catch (e) {
			error = errorMessage(e);
		}
	}

	$effect(() => {
		if (show) load();
	});

	// While a sync runs or videos wait to be looked at, look again now and then: the new
	// pictures show up by themselves.
	$effect(() => {
		if (!art || !(art.syncing || art.waiting > 0)) return;
		const timer = setTimeout(load, art.syncing ? POLL_SYNCING_MS : POLL_WAITING_MS);
		return () => clearTimeout(timer);
	});

	const styleName = (id: string | null) => {
		const style = styles.find((s) => s.id === id);
		return style ? (style.names[getLocale()] ?? style.names.en ?? style.id) : '';
	};
	const offered = $derived(styles.filter((s) => s.enabled || s.id === art?.style_id));

	const picture = (slot: string) => art?.pictures.find((p) => p.slot === slot);
	const seasons = $derived(
		(art?.pictures ?? [])
			.filter((p) => p.kind === 'season_poster')
			.sort((a, b) => (a.season ?? 0) - (b.season ?? 0))
	);
	/** The cover of the album stands for the poster: nothing drawn to pin or change. */
	const isCover = (p: ArtworkPicture) => p.kind === 'series_poster' && !!art?.use_cover;
	const pinnable = $derived((art?.pictures ?? []).filter((p) => !isCover(p)));
	const allPinned = $derived(pinnable.length > 0 && pinnable.every((p) => p.pinned));
	const tall = (slot: string) => slot === 'series_poster' || slot.startsWith('season_poster');

	/** Draws other pictures for a look; "one more" asks again from the last one shown. */
	async function open(request: ArtworkLookRequest, again = false) {
		const current = again && look?.preview ? look.preview.choice : null;
		if (!again) seen = art?.style_id ? [art.style_id] : [];
		look = { request, preview: null };
		busy = true;
		try {
			const preview = await previewArtwork(show, { ...request, current, seen_styles: seen });
			look = { request, preview };
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
		const slot = look?.request.slot ?? null;
		const change = look?.request.change;
		look = null;
		if (!choice) return;
		const unpinned = pinnable.filter((p) => !p.pinned).map((p) => p.slot);
		const redrawn = slot
			? [slot]
			: change === 'cover' || change === 'drawn'
				? ['series_poster']
				: unpinned;
		await save(() => applyArtwork(show, choice), true);
		changing = redrawn;
	}

	async function pin(slots: string[] | null, pinned: boolean) {
		const unpinned = !pinned ? (slots ?? pinnable.map((p) => p.slot)) : [];
		await save(() => pinArtwork(show, slots, pinned), false);
		if (unpinned.length) changing = [...changing, ...unpinned];
	}

	async function save(action: () => Promise<unknown>, announce: boolean) {
		busy = true;
		try {
			await action();
			await load();
			if (announce) {
				saved = true;
				setTimeout(() => (saved = false), 6000);
			}
		} catch (e) {
			error = errorMessage(e);
		} finally {
			busy = false;
		}
	}

	function chooseStyle(event: Event & { currentTarget: HTMLSelectElement }, again: boolean) {
		const styleId = event.currentTarget.value;
		event.currentTarget.value = '';
		if (styleId) open({ change: 'style', style_id: styleId }, again);
	}
</script>

{#snippet styleSelect(again: boolean)}
	<div class="st-input st-input--select st-input--sm">
		<select
			aria-label={m.artwork_choose_style()}
			disabled={busy}
			onchange={(e) => chooseStyle(e, again)}
		>
			<option value="">{m.artwork_choose_style()}</option>
			{#each offered as style (style.id)}
				<option value={style.id}>{styleName(style.id)}</option>
			{/each}
		</select>
		<span class="st-select__chev"><Icon name="chevron-down" /></span>
	</div>
{/snippet}

{#snippet tile(p: ArtworkPicture, caption: string, extra: string)}
	<figure class={extra} class:pinned={p.pinned}>
		<div class="frame">
			<img src={p.url} alt="" loading="lazy" />
			{#if art?.syncing && changing.includes(p.slot)}
				<span class="redrawing"><Icon name="loader-circle" />{m.artwork_tile_redrawing()}</span>
			{/if}
		</div>
		<figcaption>
			<span class="caption">{caption}</span>
			{#if !isCover(p)}
				<span class="tools">
					{#if p.kind !== 'logo'}
						<button
							type="button"
							class="st-btn st-btn--ghost st-btn--sm icon"
							title={m.artwork_frames_of_one()}
							aria-label={m.artwork_frames_of_one()}
							disabled={busy || p.pinned}
							onclick={() => open({ change: 'frames', slot: p.slot })}
						>
							<Icon name="refresh-cw" />
						</button>
					{/if}
					<button
						type="button"
						class="st-btn st-btn--ghost st-btn--sm icon"
						title={p.pinned ? m.artwork_unpin() : m.artwork_pin()}
						aria-label={p.pinned ? m.artwork_unpin() : m.artwork_pin()}
						aria-pressed={p.pinned}
						disabled={busy}
						onclick={() => pin([p.slot], !p.pinned)}
					>
						<Icon name={p.pinned ? 'lock' : 'lock-open'} />
					</button>
				</span>
			{/if}
		</figcaption>
	</figure>
{/snippet}

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
	{#if art?.syncing && (changing.length || saved)}
		<div class="st-banner st-banner--info" role="status">
			<span class="st-spin"><Icon name="loader-circle" /></span><span class="st-banner__body"
				>{m.artwork_redrawing()}</span
			>
		</div>
	{:else if saved}
		<div class="st-banner st-banner--success" role="status">
			<Icon name="circle-check" /><span class="st-banner__body">{m.artwork_saved()}</span>
		</div>
	{/if}
	{#if art && art.waiting > 0}
		<div class="st-banner st-banner--info" role="status">
			<span class="st-spin"><Icon name="loader-circle" /></span><span class="st-banner__body"
				>{m.artwork_waiting({ count: String(art.waiting) })}</span
			>
		</div>
	{/if}

	{#if art}
		{#if art.pictures.length === 0}
			<p class="hint">{m.artwork_none_yet()}</p>
		{:else}
			{@const poster = picture('series_poster')}
			{@const landscape = picture('landscape')}
			{@const fanart = picture('fanart')}
			{@const logo = picture('logo')}
			<div class="pictures">
				{#if poster}{@render tile(poster, m.artwork_poster(), 'poster')}{/if}
				<div class="wide">
					{#if landscape}{@render tile(landscape, m.artwork_landscape(), '')}{/if}
					{#if fanart}{@render tile(fanart, m.artwork_fanart(), '')}{/if}
					{#if logo}{@render tile(logo, m.artwork_logo(), 'logo')}{/if}
				</div>
			</div>
			{#if seasons.length}
				<div class="seasons">
					{#each seasons as season (season.slot)}
						{@render tile(season, String(season.season), 'season')}
					{/each}
				</div>
			{/if}
		{/if}

		<div class="actions">
			<button
				type="button"
				class="st-btn st-btn--sm"
				disabled={busy}
				onclick={() => open({ change: 'style' })}
			>
				<Icon name="layout-grid" />
				{m.artwork_other_style()}
			</button>
			{@render styleSelect(false)}
			<button
				type="button"
				class="st-btn st-btn--sm"
				disabled={busy || allPinned}
				onclick={() => open({ change: 'frames' })}
			>
				<Icon name="refresh-cw" />
				{m.artwork_other_frames()}
			</button>
			{#if art.use_cover}
				<button
					type="button"
					class="st-btn st-btn--sm"
					disabled={busy}
					onclick={() => open({ change: 'drawn' })}
				>
					{m.artwork_drawn_poster()}
				</button>
			{:else if cover}
				<button
					type="button"
					class="st-btn st-btn--sm"
					disabled={busy}
					onclick={() => open({ change: 'cover' })}
				>
					{m.artwork_cover_poster()}
				</button>
			{/if}
			{#if pinnable.length}
				<button
					type="button"
					class="st-btn st-btn--sm"
					disabled={busy}
					onclick={() => pin(null, !allPinned)}
				>
					<Icon name={allPinned ? 'lock-open' : 'lock'} />
					{allPinned ? m.artwork_unpin_all() : m.artwork_pin_all()}
				</button>
			{/if}
		</div>
		<p class="hint">{m.artwork_pinned_hint()}</p>
	{/if}
</section>

{#if look}
	{@const slot = look.request.slot ?? null}
	<Dialog wide title={m.artwork_look_title()} onclose={() => (look = null)}>
		{#if !look.preview}
			<p class="drawing">
				<span class="st-spin"><Icon name="loader-circle" /></span>
				{m.artwork_drawing()}
			</p>
		{:else}
			{@const next = look.preview}
			<div class="look-head">
				<p class="hint">{m.artwork_style({ name: styleName(next.choice.style_id) })}</p>
				{#if look.request.change === 'style'}{@render styleSelect(true)}{/if}
			</div>
			<div class="compare">
				<span class="label">{m.artwork_now()}</span>
				<span class="label">{m.artwork_then()}</span>
				{#each slot ? [slot] : LOOK_SLOTS as key (key)}
					{@const now = picture(key)}
					<div class="cell" class:tall={tall(key)}>
						{#if key === 'series_poster' && art?.use_cover && cover}
							<img src={thumbnailUrl(cover)} alt="" />
						{:else if now}
							<img src={now.url} alt="" />
						{/if}
					</div>
					<div class="cell" class:tall={tall(key)}>
						{#if key === 'series_poster' && next.choice.use_cover && cover}
							<img src={thumbnailUrl(cover)} alt="" />
						{:else if next.pictures[key]}
							<img src={next.pictures[key]} alt="" />
						{:else if now?.pinned}
							<img src={now.url} alt="" />
							<span class="note"><Icon name="lock" />{m.artwork_pinned_stays()}</span>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
		{#snippet footer()}
			{#if look && look.request.change !== 'cover' && look.request.change !== 'drawn'}
				<button
					type="button"
					class="st-btn st-btn--ghost"
					disabled={busy}
					onclick={() => look && open({ ...look.request, style_id: null }, true)}
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
	.head,
	.look-head {
		display: flex;
		align-items: baseline;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	.look-head {
		align-items: center;
		justify-content: space-between;
		margin-bottom: var(--space-3);
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
	.st-spin {
		display: inline-flex;
	}
	figure {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}
	.frame {
		position: relative;
	}
	figure.pinned img {
		outline: 2px solid var(--color-accent, currentColor);
		outline-offset: 1px;
	}
	.redrawing {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-1);
		padding: var(--space-1);
		text-align: center;
		font-size: var(--text-xs, 0.75rem);
		color: #fff;
		background: rgb(0 0 0 / 55%);
		border-radius: var(--radius-sm);
	}
	figcaption {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs, 0.75rem);
		min-height: 1.75rem;
	}
	.tools {
		display: inline-flex;
	}
	.st-btn.icon {
		padding: var(--space-1);
		min-width: 0;
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
	.logo img {
		object-fit: contain;
		background: repeating-conic-gradient(#3a3a3a 0 25%, #2c2c2c 0 50%) 0 0 / 16px 16px;
	}
	.seasons {
		display: flex;
		gap: var(--space-2);
		overflow-x: auto;
		padding-bottom: var(--space-1);
	}
	.season {
		flex: 0 0 6.5rem;
	}
	.season img {
		aspect-ratio: 2 / 3;
		object-fit: cover;
	}
	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
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
	.cell {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
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
	.note {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-text-muted);
		font-size: var(--text-xs, 0.75rem);
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
