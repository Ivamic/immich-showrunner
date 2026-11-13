<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- A short state ("connected", "working: GeoCLIP"). A live state has a pulsing dot. -->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		tone = 'neutral',
		live = false,
		dot = false,
		outline = false,
		title,
		children
	}: {
		tone?: 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'accent';
		live?: boolean;
		dot?: boolean;
		outline?: boolean;
		title?: string;
		children: Snippet;
	} = $props();
</script>

<span
	class="st-badge st-badge--{tone}"
	class:st-badge--live={live}
	class:st-badge--outline={outline}
	{title}
>
	{#if dot || live}<i class="st-badge__dot" aria-hidden="true"></i>{/if}
	<span>{@render children()}</span>
</span>
