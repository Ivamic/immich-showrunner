<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- A modal window over the page (native <dialog>: focus stays inside, Esc closes it). Closes
     also on the close button and on a click beside the window. -->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import { m } from '#lib/paraglide/messages.js';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons.js';

	let {
		title,
		icon,
		wide = false,
		onclose,
		children,
		footer
	}: {
		title: string;
		icon?: IconName;
		wide?: boolean;
		onclose: () => void;
		children: Snippet;
		footer?: Snippet;
	} = $props();

	let dialog: HTMLDialogElement;

	$effect(() => {
		dialog.showModal();
		return () => dialog.close();
	});
</script>

<dialog
	bind:this={dialog}
	class="st-dialog"
	class:st-dialog--wide={wide}
	aria-label={title}
	oncancel={(e) => {
		e.preventDefault();
		onclose();
	}}
	onclick={(e) => e.target === e.currentTarget && onclose()}
>
	<div class="st-dialog__head">
		{#if icon}<span class="st-dialog__icon"><Icon name={icon} /></span>{/if}
		<h2 class="st-dialog__title">{title}</h2>
		<button
			type="button"
			class="st-iconbtn st-iconbtn--sm"
			aria-label={m.save_dismiss()}
			onclick={onclose}
		>
			<Icon name="x" />
		</button>
	</div>
	<div class="st-dialog__body">{@render children()}</div>
	{#if footer}<div class="st-dialog__foot">{@render footer()}</div>{/if}
</dialog>

<style>
	dialog {
		padding: 0;
	}
	dialog::backdrop {
		background: var(--color-scrim);
		animation: st-fade var(--motion-base) var(--ease-out);
	}
</style>
