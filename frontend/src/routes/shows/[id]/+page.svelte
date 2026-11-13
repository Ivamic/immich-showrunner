<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- One show: its title and seasons, and its episodes with their titles, plots and order. -->
<script lang="ts">
	import {
		editEpisode,
		editShow,
		getShow,
		moveEpisode,
		thumbnailUrl,
		type Episode,
		type SeasonMode,
		type ShowDetail
	} from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import { getLocale } from '#lib/paraglide/runtime.js';
	import Dialog from '#lib/ui/Dialog.svelte';
	import Icon from '#lib/ui/Icon.svelte';
	import StatusBadge from '#lib/ui/StatusBadge.svelte';
	import Tooltip from '#lib/ui/Tooltip.svelte';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';

	const id = $derived(page.params.id ?? '');

	let show = $state<ShowDetail | null>(null);
	let error = $state<string | null>(null);
	let busy = $state(false);
	let saved = $state(false);
	let showTitle = $state('');
	let editingTitle = $state<string | null>(null);
	let titleDraft = $state('');
	let plotFor = $state<Episode | null>(null);
	let plotDraft = $state('');

	async function load() {
		try {
			show = await getShow(id);
			showTitle = show.title_edited ? show.title : '';
			error = null;
		} catch (e) {
			error = errorMessage(e);
		}
	}

	$effect(() => {
		if (id) load();
	});

	/** Runs a change, reloads the show and says that it is on its way to Jellyfin. */
	async function change(action: () => Promise<unknown>) {
		busy = true;
		try {
			await action();
			await load();
			saved = true;
			setTimeout(() => (saved = false), 4000);
		} catch (e) {
			error = errorMessage(e);
		} finally {
			busy = false;
		}
	}

	const seasons = $derived.by(() => {
		const groups: Record<number, Episode[]> = {};
		for (const episode of show?.episode_list ?? []) {
			(groups[episode.season] ??= []).push(episode);
		}
		return Object.entries(groups)
			.map(([season, list]) => [Number(season), list] as const)
			.sort(([a], [b]) => a - b);
	});

	function move(list: Episode[], episode: Episode, step: -1 | 1) {
		const visible = list.filter((e) => !e.hidden);
		const at = visible.indexOf(episode);
		// Up: between the two before it; down: between the two after it.
		const place =
			step < 0
				? { after: visible[at - 2]?.asset_id, before: visible[at - 1]?.asset_id }
				: { after: visible[at + 1]?.asset_id, before: visible[at + 2]?.asset_id };
		return change(() => moveEpisode(id, episode.asset_id, place));
	}

	function startTitle(episode: Episode) {
		editingTitle = episode.asset_id;
		titleDraft = episode.title;
	}

	function saveTitle(episode: Episode) {
		const value = titleDraft.trim();
		editingTitle = null;
		if (value === episode.title) return;
		return change(() =>
			editEpisode(id, episode.asset_id, {
				title: !value || value === episode.auto_title ? null : value
			})
		);
	}

	function openPlot(episode: Episode) {
		plotFor = episode;
		plotDraft = episode.plot;
	}

	function savePlot(reset = false) {
		const episode = plotFor;
		plotFor = null;
		if (!episode) return;
		const value = reset || plotDraft === episode.auto_plot ? null : plotDraft;
		return change(() => editEpisode(id, episode.asset_id, { plot: value }));
	}

	const date = (value: string) =>
		new Date(value).toLocaleString(getLocale(), {
			dateStyle: 'medium',
			timeStyle: 'short',
			timeZone: 'UTC'
		});
</script>

<p class="back">
	<a href={resolve('/shows')}><Icon name="arrow-left" size={14} /> {m.shows_heading()}</a>
</p>

{#if error}
	<div class="st-banner st-banner--danger" role="alert">
		<Icon name="circle-alert" /><span class="st-banner__body">{error}</span>
	</div>
{/if}

{#if show}
	<header class="show">
		<div class="cover">
			{#if show.cover_asset_id}<img src={thumbnailUrl(show.cover_asset_id)} alt="" />{/if}
		</div>
		<div class="settings">
			<h1>{show.title}</h1>
			<form
				onsubmit={(e) => {
					e.preventDefault();
					change(() => editShow(id, { title: showTitle.trim() || null }));
				}}
			>
				<label class="st-field">
					<span class="st-field__label">{m.show_title_label()}</span>
					<input bind:value={showTitle} placeholder={show.album_name} disabled={busy} />
					<span class="st-field__hint">{m.show_title_hint({ name: show.album_name })}</span>
				</label>
				<button type="submit" class="st-btn st-btn--sm" disabled={busy}>{m.save()}</button>
			</form>

			<div class="row">
				<span class="st-field__label">{m.show_seasons_label()}</span>
				<div class="st-seg" role="radiogroup" aria-label={m.show_seasons_label()}>
					{#each [['year', m.show_seasons_year()], ['single', m.show_seasons_single()]] as [mode, label] (mode)}
						<button
							type="button"
							role="radio"
							aria-checked={show.season_mode === mode}
							disabled={busy}
							onclick={() => change(() => editShow(id, { season_mode: mode as SeasonMode }))}
						>
							{label}
						</button>
					{/each}
				</div>
			</div>
			<p class="hint">{m.show_seasons_hint()}</p>

			<label class="st-check">
				<input
					type="checkbox"
					checked={show.hidden}
					disabled={busy}
					onchange={(e) => change(() => editShow(id, { hidden: e.currentTarget.checked }))}
				/>
				<span>{m.show_hide()}</span>
			</label>
		</div>
	</header>

	{#if saved}
		<div class="st-banner st-banner--success" role="status">
			<Icon name="circle-check" /><span class="st-banner__body">{m.show_saved()}</span>
		</div>
	{/if}

	{#each seasons as [season, list] (season)}
		<section>
			<h2>
				{show.season_mode === 'single'
					? m.show_season_one()
					: m.show_season({ year: String(season) })}
			</h2>
			<ol>
				{#each list as episode, i (episode.asset_id)}
					<li class:hidden={episode.hidden}>
						<img class="thumb" src={thumbnailUrl(episode.asset_id)} alt="" loading="lazy" />
						<span class="number">{episode.hidden ? '–' : episode.number}</span>
						<div class="body">
							{#if editingTitle === episode.asset_id}
								<form
									onsubmit={(e) => {
										e.preventDefault();
										saveTitle(episode);
									}}
								>
									<input
										class="st-input st-input--sm"
										bind:value={titleDraft}
										placeholder={episode.auto_title}
										onkeydown={(e) => e.key === 'Escape' && (editingTitle = null)}
									/>
								</form>
							{:else}
								<button type="button" class="title" onclick={() => startTitle(episode)}>
									{episode.title}
								</button>
							{/if}
							<span class="meta">
								{date(episode.filmed_at)} · <span class="file">{episode.file_name}</span>
								{#if episode.title_edited}<StatusBadge tone="info"
										>{m.episode_title_edited()}</StatusBadge
									>{/if}
								{#if episode.plot_edited}<StatusBadge tone="info"
										>{m.episode_plot_edited()}</StatusBadge
									>{/if}
								{#if episode.moved}<StatusBadge tone="info">{m.episode_moved()}</StatusBadge>{/if}
								{#if episode.hidden}<StatusBadge tone="warning">{m.episode_hidden()}</StatusBadge
									>{/if}
							</span>
							{#if episode.plot}<p class="plot">{episode.plot}</p>{/if}
						</div>
						<div class="actions">
							{#if !episode.hidden}
								<Tooltip text={m.episode_up()}>
									<button
										type="button"
										class="st-iconbtn st-iconbtn--sm"
										aria-label={m.episode_up()}
										disabled={busy || i === 0}
										onclick={() => move(list, episode, -1)}
									>
										<Icon name="chevron-up" />
									</button>
								</Tooltip>
								<Tooltip text={m.episode_down()}>
									<button
										type="button"
										class="st-iconbtn st-iconbtn--sm"
										aria-label={m.episode_down()}
										disabled={busy || list.filter((e) => !e.hidden).at(-1) === episode}
										onclick={() => move(list, episode, 1)}
									>
										<Icon name="chevron-down" />
									</button>
								</Tooltip>
							{/if}
							<Tooltip text={m.episode_edit_plot()}>
								<button
									type="button"
									class="st-iconbtn st-iconbtn--sm"
									aria-label={m.episode_edit_plot()}
									disabled={busy}
									onclick={() => openPlot(episode)}
								>
									<Icon name="rows-3" />
								</button>
							</Tooltip>
							{#if episode.title_edited || episode.moved}
								<Tooltip text={m.episode_reset()}>
									<button
										type="button"
										class="st-iconbtn st-iconbtn--sm"
										aria-label={m.episode_reset()}
										disabled={busy}
										onclick={() =>
											change(() =>
												editEpisode(id, episode.asset_id, { title: null, sort_at: null })
											)}
									>
										<Icon name="undo-2" />
									</button>
								</Tooltip>
							{/if}
							<Tooltip text={episode.hidden ? m.episode_show() : m.episode_hide()}>
								<button
									type="button"
									class="st-iconbtn st-iconbtn--sm"
									aria-label={episode.hidden ? m.episode_show() : m.episode_hide()}
									disabled={busy}
									onclick={() =>
										change(() => editEpisode(id, episode.asset_id, { hidden: !episode.hidden }))}
								>
									<Icon name="eye-off" />
								</button>
							</Tooltip>
						</div>
					</li>
				{/each}
			</ol>
		</section>
	{/each}
{:else if !error}
	<p>{m.status_loading()}</p>
{/if}

{#if plotFor}
	<Dialog title={m.episode_plot_title()} onclose={() => (plotFor = null)}>
		<label class="st-field">
			<span class="st-field__label">{plotFor.title}</span>
			<textarea class="st-input" rows="6" bind:value={plotDraft}></textarea>
			{#if plotFor.auto_plot}
				<span class="st-field__hint">{m.episode_plot_from_immich({ text: plotFor.auto_plot })}</span
				>
			{/if}
		</label>
		{#snippet footer()}
			{#if plotFor?.plot_edited}
				<button type="button" class="st-btn st-btn--ghost" onclick={() => savePlot(true)}>
					{m.episode_plot_reset()}
				</button>
			{/if}
			<button type="button" class="st-btn" onclick={() => (plotFor = null)}>{m.cancel()}</button>
			<button type="button" class="st-btn st-btn--primary" onclick={() => savePlot()}>
				{m.save()}
			</button>
		{/snippet}
	</Dialog>
{/if}

<style>
	.back {
		margin: 0 0 var(--space-4);
	}
	.back a {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-text-muted);
		text-decoration: none;
	}
	.show {
		display: grid;
		grid-template-columns: minmax(10rem, 16rem) 1fr;
		gap: var(--space-6);
		align-items: start;
	}
	@media (max-width: 40rem) {
		.show {
			grid-template-columns: 1fr;
		}
	}
	.cover {
		aspect-ratio: 16 / 9;
		border-radius: var(--radius-lg);
		background: var(--color-surface-sunken);
		overflow: hidden;
	}
	.cover img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.settings {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	h1 {
		margin: 0;
	}
	.settings form {
		display: flex;
		align-items: end;
		gap: var(--space-2);
	}
	.settings form .st-field {
		flex: 1;
	}
	.row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		flex-wrap: wrap;
	}
	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	section {
		margin-top: var(--space-8);
	}
	h2 {
		font-size: var(--text-lg);
		margin: 0 0 var(--space-2);
	}
	ol {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: grid;
		grid-template-columns: 6rem 2rem 1fr auto;
		gap: var(--space-3);
		align-items: start;
		padding: var(--space-3) 0;
		border-bottom: 1px solid var(--color-border);
	}
	li.hidden {
		opacity: 0.55;
	}
	.thumb {
		width: 6rem;
		aspect-ratio: 16 / 9;
		object-fit: cover;
		border-radius: var(--radius-sm);
		background: var(--color-surface-sunken);
	}
	.number {
		font-variant-numeric: tabular-nums;
		color: var(--color-text-muted);
		text-align: right;
		padding-top: var(--space-1);
	}
	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}
	.title {
		all: unset;
		cursor: text;
		font-weight: 600;
	}
	.title:hover,
	.title:focus-visible {
		text-decoration: underline dotted;
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.file {
		font-family: var(--font-mono);
	}
	.plot {
		margin: 0;
		font-size: var(--text-sm);
		white-space: pre-line;
	}
	.actions {
		display: flex;
		gap: var(--space-1);
	}
	@media (max-width: 40rem) {
		li {
			grid-template-columns: 4.5rem 1.5rem 1fr;
		}
		.thumb {
			width: 4.5rem;
		}
		.actions {
			grid-column: 1 / -1;
			justify-content: flex-end;
		}
	}
</style>
