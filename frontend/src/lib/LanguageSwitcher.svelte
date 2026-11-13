<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Languages by their own names, never flags. The list closes on a click outside and on Esc. -->
<script lang="ts">
	import { m } from '#lib/paraglide/messages.js';
	import { LANGUAGE_NAMES as names } from '#lib/languages.js';
	import { getLocale, locales, setLocale } from '#lib/paraglide/runtime.js';
	import Icon from '#lib/ui/Icon.svelte';

	let open = $state(false);
	let root: HTMLDivElement | undefined = $state();
	const current = getLocale();

	function closeOutside(event: PointerEvent) {
		if (open && root && !root.contains(event.target as Node)) open = false;
	}

	function closeOnEscape(event: KeyboardEvent) {
		if (!open || event.key !== 'Escape') return;
		event.preventDefault();
		open = false;
		root?.querySelector('button')?.focus();
	}
</script>

<svelte:window onpointerdown={closeOutside} onkeydown={closeOnEscape} />

<div class="st-langsw" bind:this={root}>
	<button
		type="button"
		class="st-btn st-btn--ghost st-btn--sm"
		aria-haspopup="menu"
		aria-expanded={open}
		aria-label="{m.language()}: {names[current]}"
		onclick={() => (open = !open)}
	>
		<Icon name="languages" size={14} />
		<span lang={current}>{names[current]}</span>
		<Icon name="chevron-down" size={14} />
	</button>
	{#if open}
		<div class="st-menu" role="menu" aria-label={m.language()}>
			{#each locales as locale (locale)}
				<button
					type="button"
					class="st-menu__item"
					role="menuitemradio"
					aria-checked={locale === current}
					lang={locale}
					onclick={() => setLocale(locale)}
				>
					<span class="st-menu__label">{names[locale]}</span>
					{#if locale === current}
						<span class="st-menu__check"><Icon name="check" /></span>
					{/if}
				</button>
			{/each}
		</div>
	{/if}
</div>
