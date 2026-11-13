<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Logo and name. The mark: a clapperboard whose stripes take the module colors of the theme,
     over a screen with a play sign; one drawing serves both themes. -->
<script lang="ts">
	import { m } from '#lib/paraglide/messages.js';

	let { large = false, href }: { large?: boolean; href?: string } = $props();
</script>

<svelte:element this={href ? 'a' : 'span'} {href} class="st-brand" class:large>
	<svg viewBox="0 0 48 48" aria-hidden="true">
		<g stroke-linejoin="round">
			<path d="M6 10l36-4 0.8 7-36 4z" fill="var(--color-text)" />
			<path
				d="M11 9.4l3.8 6.6M19.5 8.4l3.8 6.6M28 7.5l3.8 6.6"
				stroke-width="3.4"
				stroke="var(--module-2)"
			/>
			<rect x="6" y="19" width="36" height="23" rx="3" fill="var(--color-text)" />
			<path d="M21 25v11l9-5.5z" fill="var(--module-1)" />
		</g>
	</svg>
	<span class="name">
		<span class="word">Showrunner</span>
		<span class="for">{m.brand_for_immich()}</span>
	</span>
</svelte:element>

<style>
	svg {
		width: 1.5rem;
		height: 1.5rem;
		border-radius: 0;
	}
	.name {
		display: inline-flex;
		align-items: baseline;
		gap: var(--space-1-5);
		white-space: nowrap;
	}
	.word {
		font-size: var(--text-md);
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.for {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}
	.large svg {
		width: 2.5rem;
		height: 2.5rem;
	}
	.large .word {
		font-size: var(--text-xl);
	}
</style>
