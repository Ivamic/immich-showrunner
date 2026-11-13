<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- The albums shared with the user of the app, as shows. -->
<script lang="ts">
	import { getShows, thumbnailUrl, type ShowSummary } from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import EmptyState from '#lib/ui/EmptyState.svelte';
	import Icon from '#lib/ui/Icon.svelte';
	import StatusBadge from '#lib/ui/StatusBadge.svelte';
	import { resolve } from '$app/paths';

	let shows = $state<ShowSummary[] | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		getShows()
			.then((list) => (shows = list))
			.catch((e) => (error = errorMessage(e)));
	});
</script>

<h1>{m.shows_heading()}</h1>
<p class="hint">{m.shows_hint()}</p>

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
				<a href={resolve('/shows/[id]', { id: show.album_id })}>
					<div class="cover">
						{#if show.cover_asset_id}
							<img src={thumbnailUrl(show.cover_asset_id)} alt="" loading="lazy" />
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
	.cover {
		aspect-ratio: 16 / 9;
		background: var(--color-surface-sunken);
	}
	img {
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
