<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- The state of the sync. A first version: the full page comes with the next step. -->
<script lang="ts">
	import { getHealth, type Health } from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import StatusBadge from '#lib/ui/StatusBadge.svelte';

	let health = $state<Health | null>(null);
	let error = $state<string | null>(null);

	$effect(() => {
		getHealth()
			.then((h) => (health = h))
			.catch((e) => (error = errorMessage(e)));
	});
</script>

<h1>{m.status_heading()}</h1>
{#if error}
	<p class="st-banner st-banner--danger">{error}</p>
{:else if health}
	<p>
		<StatusBadge tone={health.ok === false ? 'danger' : 'success'}>
			{health.ok === false ? m.status_problem() : m.status_ok()}
		</StatusBadge>
	</p>
	<p>{m.status_shows({ count: String(health.shows) })}</p>
	{#if health.error}<p class="st-banner st-banner--danger">{health.error}</p>{/if}
{:else}
	<p>{m.status_loading()}</p>
{/if}
