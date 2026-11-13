<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- People shared with the user of the app: their names for Jellyfin and their descriptions, and
     the invitations into a cluster group. -->
<script lang="ts">
	import {
		acceptInvitation,
		editPerson,
		faceUrl,
		getPeople,
		type People,
		type Person
	} from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import Dialog from '#lib/ui/Dialog.svelte';
	import EmptyState from '#lib/ui/EmptyState.svelte';
	import Icon from '#lib/ui/Icon.svelte';
	import StatusBadge from '#lib/ui/StatusBadge.svelte';

	let data = $state<People | null>(null);
	let error = $state<string | null>(null);
	let busy = $state(false);
	let saved = $state(false);
	let editing = $state<Person | null>(null);
	let nameDraft = $state('');
	let descriptionDraft = $state('');

	async function load() {
		try {
			data = await getPeople();
			error = null;
		} catch (e) {
			error = errorMessage(e);
		}
	}

	$effect(() => {
		load();
	});

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

	function open(person: Person) {
		editing = person;
		nameDraft = person.name;
		descriptionDraft = person.description;
	}

	function save() {
		const person = editing;
		editing = null;
		if (!person) return;
		const patch: { name?: string; description?: string } = {};
		if (data?.can_write && nameDraft.trim() !== person.name) patch.name = nameDraft.trim();
		if (descriptionDraft.trim() !== person.description) patch.description = descriptionDraft;
		if (Object.keys(patch).length) return change(() => editPerson(person.id, patch));
	}
</script>

<h1>{m.people_heading()}</h1>
<p class="hint">{m.people_hint()}</p>

{#if error}
	<div class="st-banner st-banner--danger" role="alert">
		<Icon name="circle-alert" /><span class="st-banner__body">{error}</span>
	</div>
{/if}
{#if saved}
	<div class="st-banner st-banner--success" role="status">
		<Icon name="circle-check" /><span class="st-banner__body">{m.show_saved()}</span>
	</div>
{/if}

{#if data}
	{#if !data.can_write}
		<div class="st-banner st-banner--info">
			<Icon name="lock-open" /><span class="st-banner__body">{m.people_read_only()}</span>
		</div>
	{/if}

	<section class="group">
		<h2>{m.people_group_heading()}</h2>
		{#if data.group === null}
			<p class="hint">{m.people_group_unknown()}</p>
		{:else if data.group.length}
			<p>{m.people_group_members({ names: data.group.join(', ') })}</p>
		{:else}
			<p>{m.people_group_alone()}</p>
		{/if}
		{#each data.invitations as invitation (invitation.id)}
			<div class="st-banner st-banner--info">
				<Icon name="circle-alert" />
				<div class="st-banner__body">
					<p class="st-banner__title">
						{m.people_invitation({ names: invitation.from_users.join(', ') })}
					</p>
					{#if !data.can_accept}<p>{m.people_invitation_blocked()}</p>{/if}
				</div>
				{#if data.can_accept}
					<div class="st-banner__actions">
						<button
							type="button"
							class="st-btn st-btn--sm st-btn--primary"
							disabled={busy}
							onclick={() => change(() => acceptInvitation(invitation.id))}
						>
							{m.people_accept()}
						</button>
					</div>
				{/if}
			</div>
		{/each}
		<p class="hint">{m.people_group_hint()}</p>
	</section>

	{#if data.people.length === 0}
		<EmptyState icon="scan-search" title={m.people_empty_title()} text={m.people_empty_text()} />
	{:else}
		<ul class="people">
			{#each data.people as person (person.id)}
				<li class:off={!person.name}>
					<img src={faceUrl(person.id)} alt="" loading="lazy" />
					<div class="text">
						<span class="name">{person.name || m.people_no_name()}</span>
						{#if person.owner_names.length}
							<span class="meta">
								{m.people_owner_names({ names: person.owner_names.join(', ') })}
							</span>
						{/if}
						{#if !person.name}
							<StatusBadge tone="neutral">{m.people_not_in_jellyfin()}</StatusBadge>
						{/if}
						{#if person.description}<p class="description">{person.description}</p>{/if}
					</div>
					<button
						type="button"
						class="st-btn st-btn--sm"
						disabled={busy}
						onclick={() => open(person)}
					>
						{m.people_edit()}
					</button>
				</li>
			{/each}
		</ul>
	{/if}
{:else if !error}
	<p>{m.status_loading()}</p>
{/if}

{#if editing}
	<Dialog title={m.people_edit_title()} onclose={() => (editing = null)}>
		<div class="form">
			<img class="big" src={faceUrl(editing.id)} alt="" />
			<label class="st-field">
				<span class="st-field__label">{m.people_name_label()}</span>
				<input bind:value={nameDraft} disabled={!data?.can_write} />
				<span class="st-field__hint">{m.people_name_hint()}</span>
			</label>
			<label class="st-field">
				<span class="st-field__label">{m.people_description_label()}</span>
				<textarea class="st-input" rows="4" bind:value={descriptionDraft}></textarea>
				<span class="st-field__hint">{m.people_description_hint()}</span>
			</label>
		</div>
		{#snippet footer()}
			<button type="button" class="st-btn" onclick={() => (editing = null)}>{m.cancel()}</button>
			<button type="button" class="st-btn st-btn--primary" onclick={save}>{m.save()}</button>
		{/snippet}
	</Dialog>
{/if}

<style>
	h1 {
		margin: 0;
	}
	h2 {
		font-size: var(--text-lg);
		margin: 0 0 var(--space-2);
	}
	.hint {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.group {
		margin: var(--space-6) 0;
		padding: var(--space-4) var(--space-5);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface);
	}
	.people {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	li {
		display: grid;
		grid-template-columns: 3.5rem 1fr auto;
		gap: var(--space-4);
		align-items: center;
		padding: var(--space-3) 0;
		border-bottom: 1px solid var(--color-border);
	}
	li.off {
		opacity: 0.65;
	}
	li img {
		width: 3.5rem;
		height: 3.5rem;
		border-radius: 50%;
		object-fit: cover;
		background: var(--color-surface-sunken);
	}
	.text {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-1);
		min-width: 0;
	}
	.name {
		font-weight: 600;
	}
	.meta {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}
	.description {
		margin: 0;
		font-size: var(--text-sm);
		white-space: pre-line;
	}
	.form {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}
	.big {
		width: 6rem;
		height: 6rem;
		border-radius: 50%;
		object-fit: cover;
	}
</style>
