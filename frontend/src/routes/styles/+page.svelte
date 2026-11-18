<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- The styles of the pictures: which ones the app may choose for an album. -->
<script lang="ts">
	import { editStyle, getStyles, type Style } from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import { getLocale } from '#lib/paraglide/runtime.js';
	import Icon from '#lib/ui/Icon.svelte';

	let styles = $state<Style[] | null>(null);
	let error = $state<string | null>(null);
	let busy = $state(false);
	let saved = $state(false);

	async function load() {
		try {
			styles = await getStyles();
			error = null;
		} catch (e) {
			error = errorMessage(e);
		}
	}

	$effect(() => {
		load();
	});

	async function toggle(style: Style, enabled: boolean) {
		busy = true;
		try {
			await editStyle(style.id, enabled);
			await load();
			saved = true;
			setTimeout(() => (saved = false), 5000);
		} catch (e) {
			error = errorMessage(e);
			await load();
		} finally {
			busy = false;
		}
	}

	const name = (style: Style) => style.names[getLocale()] ?? style.names.en ?? style.id;
</script>

<h1>{m.styles_heading()}</h1>
<p class="intro">{m.styles_intro()}</p>

{#if error}
	<div class="st-banner st-banner--danger" role="alert">
		<Icon name="circle-alert" /><span class="st-banner__body">{error}</span>
	</div>
{/if}
{#if saved}
	<div class="st-banner st-banner--success" role="status">
		<Icon name="circle-check" /><span class="st-banner__body">{m.styles_saved()}</span>
	</div>
{/if}

{#if styles}
	<ul>
		{#each styles as style (style.id)}
			<li>
				<label class="st-check">
					<input
						type="checkbox"
						checked={style.enabled}
						disabled={busy}
						onchange={(e) => toggle(style, e.currentTarget.checked)}
					/>
					<span>{name(style)}</span>
				</label>
				<span class="count">{m.styles_shows({ count: String(style.shows) })}</span>
			</li>
		{/each}
	</ul>
{:else if !error}
	<p>{m.status_loading()}</p>
{/if}

<style>
	h1 {
		margin: 0 0 var(--space-2);
	}
	.intro {
		color: var(--color-text-muted);
		margin: 0 0 var(--space-4);
		max-width: 48rem;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		max-width: 32rem;
	}
	li {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--space-2) 0;
		border-bottom: 1px solid var(--color-border);
	}
	.count {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
</style>
