<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- The state of the sync: the last pass, what it could not do, and a pass on request. -->
<script lang="ts">
	import { getStatus, syncNow, type Status } from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import { getLocale } from '#lib/paraglide/runtime.js';
	import Dialog from '#lib/ui/Dialog.svelte';
	import Icon from '#lib/ui/Icon.svelte';
	import StatusBadge from '#lib/ui/StatusBadge.svelte';

	let status = $state<Status | null>(null);
	let error = $state<string | null>(null);
	let requested = $state(false);
	let confirmingForce = $state(false);

	async function load() {
		try {
			status = await getStatus();
			error = null;
			if (!status.running && requested && status.last_sync_at) requested = false;
		} catch (e) {
			error = errorMessage(e);
		}
	}

	// Often while a pass runs or was asked for, rarely otherwise.
	$effect(() => {
		load();
		const busy = requested || status?.running;
		const timer = setInterval(load, busy ? 2000 : 15000);
		return () => clearInterval(timer);
	});

	async function run(force = false) {
		confirmingForce = false;
		try {
			await syncNow(force);
			requested = true;
		} catch (e) {
			error = errorMessage(e);
		}
	}

	function time(value: string | null): string {
		if (!value) return m.status_never();
		return new Date(value).toLocaleString(getLocale(), { dateStyle: 'medium', timeStyle: 'short' });
	}

	const reasons: Record<string, () => string> = {
		not_a_video: m.skip_not_a_video,
		trashed: m.skip_trashed,
		offline: m.skip_offline,
		hidden: m.skip_hidden,
		no_path_mapping: m.skip_no_path_mapping,
		no_extension: m.skip_no_extension
	};
</script>

<div class="head">
	<h1>{m.status_heading()}</h1>
	<button
		type="button"
		class="st-btn st-btn--primary"
		onclick={() => run()}
		disabled={requested || status?.running}
	>
		<Icon name="refresh-cw" size={16} />
		{requested || status?.running ? m.status_syncing() : m.status_sync_now()}
	</button>
</div>

{#if error}
	<div class="st-banner st-banner--danger" role="alert">
		<Icon name="circle-alert" /><span class="st-banner__body">{error}</span>
	</div>
{/if}

{#if status}
	<section class="summary">
		<div>
			{#if status.running}
				<StatusBadge tone="info" live>{m.status_running()}</StatusBadge>
			{:else if status.held}
				<StatusBadge tone="warning" dot>{m.status_held()}</StatusBadge>
			{:else if status.ok === false}
				<StatusBadge tone="danger" dot>{m.status_problem()}</StatusBadge>
			{:else if status.ok === null}
				<StatusBadge tone="neutral">{m.status_waiting()}</StatusBadge>
			{:else}
				<StatusBadge tone="success" dot>{m.status_ok()}</StatusBadge>
			{/if}
		</div>
		<dl>
			<dt>{m.status_last_sync()}</dt>
			<dd>{time(status.last_sync_at)}</dd>
			<dt>{m.status_last_full_sync()}</dt>
			<dd>{time(status.last_full_sync_at)}</dd>
			<dt>{m.status_shows_label()}</dt>
			<dd>{status.shows}</dd>
			<dt>{m.status_last_changes()}</dt>
			<dd>
				{m.status_changes({
					created: String(status.created),
					replaced: String(status.replaced),
					removed: String(status.removed)
				})}
			</dd>
			<dt>{m.status_jellyfin_pending_label()}</dt>
			<dd>{status.jellyfin_pending}</dd>
		</dl>
		<p class="hint">
			{m.status_interval({ minutes: String(Math.round(status.sync_interval_seconds / 60)) })}
		</p>
	</section>

	{#if status.held}
		<div class="st-banner st-banner--warning" role="alert">
			<Icon name="triangle-alert" />
			<div class="st-banner__body">
				<p class="st-banner__title">{m.status_held_title()}</p>
				<p>
					{m.status_held_text({
						removed: String(status.held_links_removed),
						before: String(status.held_links_before)
					})}
				</p>
			</div>
			<div class="st-banner__actions">
				<button type="button" class="st-btn st-btn--sm" onclick={() => (confirmingForce = true)}>
					{m.status_force()}
				</button>
			</div>
		</div>
	{/if}

	{#each status.errors as message (message)}
		<div class="st-banner st-banner--danger">
			<Icon name="circle-alert" /><span class="st-banner__body">{message}</span>
		</div>
	{/each}

	{#if status.skipped.length}
		<section>
			<h2>{m.status_skipped_heading({ count: String(status.skipped.length) })}</h2>
			<p class="hint">{m.status_skipped_hint()}</p>
			<table>
				<thead>
					<tr><th>{m.status_album()}</th><th>{m.status_file()}</th><th>{m.status_reason()}</th></tr>
				</thead>
				<tbody>
					{#each status.skipped as item (item.album + item.file)}
						<tr>
							<td>{item.album}</td>
							<td class="mono">{item.file}</td>
							<td>{reasons[item.reason]?.() ?? item.reason}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</section>
	{/if}

	{#if status.pictures_failed.length}
		<section>
			<h2>{m.status_pictures_heading({ count: String(status.pictures_failed.length) })}</h2>
			<p class="hint">{m.status_pictures_hint()}</p>
			<ul class="mono">
				{#each status.pictures_failed as line (line)}<li>{line}</li>{/each}
			</ul>
		</section>
	{/if}

	{#if status.foreign.length}
		<section>
			<h2>{m.status_foreign_heading({ count: String(status.foreign.length) })}</h2>
			<p class="hint">{m.status_foreign_hint()}</p>
			<ul>
				{#each status.foreign as item (item.path)}
					<li><span class="mono">{item.path}</span> — {item.detail}</li>
				{/each}
			</ul>
		</section>
	{/if}

	<p class="hint version">Showrunner {status.version}</p>
{:else if !error}
	<p>{m.status_loading()}</p>
{/if}

{#if confirmingForce && status}
	<Dialog
		title={m.status_force_title()}
		icon="triangle-alert"
		onclose={() => (confirmingForce = false)}
	>
		<p>
			{m.status_force_text({
				removed: String(status.held_links_removed),
				before: String(status.held_links_before)
			})}
		</p>
		{#snippet footer()}
			<button type="button" class="st-btn" onclick={() => (confirmingForce = false)}>
				{m.cancel()}
			</button>
			<button type="button" class="st-btn st-btn--danger" onclick={() => run(true)}>
				{m.status_force_confirm()}
			</button>
		{/snippet}
	</Dialog>
{/if}

<style>
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		flex-wrap: wrap;
	}
	h1 {
		margin: 0;
	}
	section {
		margin-top: var(--space-6);
	}
	.summary {
		padding: var(--space-5);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface);
	}
	dl {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: var(--space-2) var(--space-6);
		margin: var(--space-4) 0 0;
	}
	dt {
		color: var(--color-text-muted);
	}
	dd {
		margin: 0;
	}
	h2 {
		font-size: var(--text-lg);
		margin: 0 0 var(--space-1);
	}
	.hint {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		margin: var(--space-2) 0;
	}
	.version {
		margin-top: var(--space-8);
	}
	.mono {
		font-family: var(--font-mono);
		font-size: var(--text-sm);
		word-break: break-all;
	}
	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}
	th,
	td {
		text-align: left;
		padding: var(--space-2);
		border-bottom: 1px solid var(--color-border);
		vertical-align: top;
	}
	th {
		color: var(--color-text-muted);
		font-weight: 500;
	}
	ul {
		margin: 0;
		padding-left: var(--space-5);
	}
</style>
