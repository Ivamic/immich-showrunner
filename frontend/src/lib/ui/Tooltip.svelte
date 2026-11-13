<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Short hint over a control, shown on hover after a pause and on keyboard focus. It is drawn
     over everything (fixed to the window), so it is never cut off by a scrolling panel and never
     widens one; it stays inside the window. A click hides it. It never takes pointer events, so
     in a dense row it cannot cover the neighbor the pointer moves to. The wrapped control keeps
     its own aria-label: the tooltip is for sighted users. -->
<script lang="ts">
	import { tick, type Snippet } from 'svelte';
	import Kbd from './Kbd.svelte';

	let {
		text,
		keys,
		below = false,
		children
	}: {
		text: string;
		/** Keyboard shortcut shown after the text. */
		keys?: string;
		/** Below the control rather than above (for controls at the top of the page). */
		below?: boolean;
		children: Snippet;
	} = $props();

	const DELAY_MS = 400;
	const GAP = 6;
	const EDGE = 8;

	let wrap: HTMLSpanElement;
	let tip: HTMLSpanElement | undefined = $state();
	let shown = $state(false);
	let position = $state<{ left: number; top: number } | null>(null);
	let timer: ReturnType<typeof setTimeout> | undefined;

	function schedule() {
		clearTimeout(timer);
		timer = setTimeout(show, DELAY_MS);
	}

	async function show() {
		shown = true;
		position = null;
		await tick();
		if (!tip || !shown) return;
		const target = wrap.getBoundingClientRect();
		const box = tip.getBoundingClientRect();
		const left = Math.min(
			Math.max(EDGE, target.left + target.width / 2 - box.width / 2),
			innerWidth - box.width - EDGE
		);
		const above = target.top - GAP - box.height;
		const under = target.bottom + GAP;
		// The preferred side, or the other one when there is no room.
		const top = (below && under + box.height <= innerHeight - EDGE) || above < EDGE ? under : above;
		position = { left, top };
	}

	function hide() {
		clearTimeout(timer);
		shown = false;
	}

	function focusIn(event: FocusEvent) {
		// Keyboard focus only: a click leaves the focus on the control but should not keep a hint.
		if ((event.target as HTMLElement).matches(':focus-visible')) show();
	}

	$effect(() => () => clearTimeout(timer));

	/** Moves the hint to <body>: under a blurred (glass) panel `fixed` would be relative to it. */
	function toBody(node: HTMLElement) {
		document.body.append(node);
		return { destroy: () => node.remove() };
	}

	// Any scroll (of the page or of a panel) moves the control away from the hint.
	$effect(() => {
		if (!shown) return;
		addEventListener('scroll', hide, { capture: true, passive: true });
		return () => removeEventListener('scroll', hide, { capture: true });
	});
</script>

<span
	class="wrap"
	bind:this={wrap}
	role="presentation"
	onpointerenter={schedule}
	onpointerleave={hide}
	onpointerdown={hide}
	onfocusin={focusIn}
	onfocusout={hide}
>
	{@render children()}
</span>
{#if shown}
	<span
		bind:this={tip}
		use:toBody
		class="st-tooltip tip"
		class:placed={position}
		style:left="{position?.left ?? 0}px"
		style:top="{position?.top ?? 0}px"
		aria-hidden="true"
	>
		{text}
		{#if keys}<Kbd>{keys}</Kbd>{/if}
	</span>
{/if}

<style>
	.wrap {
		display: inline-flex;
	}
	.tip {
		position: fixed;
		pointer-events: none;
		visibility: hidden;
	}
	.tip.placed {
		visibility: visible;
		animation: tip-in var(--motion-fast) var(--ease-out);
	}
	@keyframes tip-in {
		from {
			opacity: 0;
		}
	}
</style>
