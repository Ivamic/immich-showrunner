<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- A Lucide icon in the current text color. Without `label` it is decorative (hidden from screen
     readers): the button or text next to it carries the meaning. -->
<script lang="ts">
	import { ICONS, MIRRORED, type IconName } from './icons.js';

	let {
		name,
		size = 16,
		strokeWidth = 1.75,
		label
	}: { name: IconName; size?: number; strokeWidth?: number; label?: string } = $props();
</script>

<svg
	xmlns="http://www.w3.org/2000/svg"
	width={size}
	height={size}
	viewBox="0 0 24 24"
	fill="none"
	stroke="currentColor"
	stroke-width={strokeWidth}
	stroke-linecap="round"
	stroke-linejoin="round"
	role={label ? 'img' : undefined}
	aria-label={label}
	aria-hidden={label ? undefined : true}
	data-mirror={MIRRORED.has(name) ? 'rtl' : undefined}
>
	<!-- eslint-disable-next-line svelte/no-at-html-tags -- fixed markup from icons.ts -->
	{@html ICONS[name]}
</svg>

<style>
	svg {
		display: block;
		flex-shrink: 0;
	}
</style>
