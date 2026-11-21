<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- The albums shared with the user of the app, as shows. -->
<script lang="ts">
	import { getShows, landscapeUrl, thumbnailUrl, type ShowSummary } from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import EmptyState from '#lib/ui/EmptyState.svelte';
	import Icon from '#lib/ui/Icon.svelte';
	import StatusBadge from '#lib/ui/StatusBadge.svelte';
	import { resolve } from '$app/paths';

	let shows = $state<ShowSummary[] | null>(null);
	let error = $state<string | null>(null);

	type View = 'drawn' | 'immich';
	const VIEW_KEY = 'showrunner-albums-view';
	function storedView(): View {
		try {
			return localStorage.getItem(VIEW_KEY) === 'immich' ? 'immich' : 'drawn';
		} catch {
			return 'drawn';
		}
	}
	let view = $state<View>(storedView());
	function choose(value: View) {
		view = value;
		try {
			localStorage.setItem(VIEW_KEY, value);
		} catch {
			// not kept: the choice holds for this visit
		}
	}

	/** The picture of a card: the one the app drew, or the cover of the album in Immich. */
	function picture(show: ShowSummary): string | null {
		if (view === 'drawn' && show.landscape_version)
			return landscapeUrl(show.album_id, show.landscape_version);
		return show.cover_asset_id ? thumbnailUrl(show.cover_asset_id) : null;
	}

	$effect(() => {
		getShows()
			.then((list) => (shows = list))
			.catch((e) => (error = errorMessage(e)));
	});
</script>

<h1>{m.albums_heading()}</h1>
<p class="hint">{m.shows_hint()}</p>
<div class="view st-seg" role="radiogroup" aria-label={m.albums_view_label()}>
	{#each [['drawn', m.albums_view_drawn()], ['immich', m.albums_view_immich()]] as [value, label] (value)}
		<button
			type="button"
			role="radio"
			aria-checked={view === value}
			onclick={() => choose(value as View)}
		>
			{label}
		</button>
	{/each}
</div>

{#if error}
	<div class="st-banner st-banner--danger" role="alert">
		<Icon name="circle-alert" /><span class="st-banner__body">{error}</span>
	</div>
{:else if shows === null}
	<p>{m.status_loading()}</p>
{:else if shows.length === 0}
	<EmptyState icon="layout-grid" title={m.shows_empty_title()} text={m.shows_empty_text()} />
{:else}
	<ul class="grid">
		{#each shows as show (show.album_id)}
			<li class:hidden={show.hidden}>
				<a href={resolve('/albums/[id]', { id: show.album_id })}>
					<div class="cover">
						{#if picture(show)}
							<img src={picture(show)} alt="" loading="lazy" />
						{/if}
					</div>
					<div class="text">
						<span class="title">{show.title}</span>
						{#if show.title_edited}
							<span class="album">{m.shows_album({ name: show.album_name })}</span>
						{/if}
						<span class="meta">
							{m.shows_episodes({ count: String(show.episodes) })}
							{#if show.hidden}<StatusBadge tone="warning">{m.shows_hidden()}</StatusBadge>{/if}
							{#if show.season_mode === 'single'}
								<StatusBadge tone="neutral">{m.shows_one_season()}</StatusBadge>
							{/if}
						</span>
					</div>
				</a>
			</li>
		{/each}
	</ul>
{/if}

<style>
	h1 {
		margin: 0;
	}
	.hint {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr));
		gap: var(--space-4);
		list-style: none;
		margin: var(--space-6) 0 0;
		padding: 0;
	}
	a {
		display: flex;
		flex-direction: column;
		height: 100%;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface);
		color: inherit;
		text-decoration: none;
		overflow: hidden;
	}
	a:hover {
		border-color: var(--color-border-strong);
	}
	.hidden a {
		opacity: 0.6;
	}
	.view {
		margin-top: var(--space-4);
	}
	/* Every card has the same picture frame: a tall cover is cut to it, not the frame stretched. */
	.cover {
		position: relative;
		aspect-ratio: 16 / 9;
		overflow: hidden;
		background: var(--color-surface-sunken);
	}
	img {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.text {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		padding: var(--space-3) var(--space-4) var(--space-4);
	}
	.title {
		font-weight: 600;
	}
	.album,
	.meta {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}
</style>
