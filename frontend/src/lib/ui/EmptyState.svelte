<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Nothing to show: an icon, what it means and what comes next, on a faint dotted grid. -->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons.js';

	let {
		icon,
		title,
		text,
		children
	}: { icon: IconName; title: string; text?: string; children?: Snippet } = $props();
</script>

<div class="st-empty">
	<div class="st-empty__inner">
		<span class="st-empty__icon"><Icon name={icon} size={20} /></span>
		<p class="st-empty__title">{title}</p>
		{#if text}<p class="st-empty__text">{text}</p>{/if}
		{@render children?.()}
	</div>
</div>
