<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- Light, dark or as in the system; remembered in this browser. -->
<script lang="ts">
	import { m } from '#lib/paraglide/messages.js';
	import { setTheme, theme, THEME_CHOICES, type ThemeChoice } from '#lib/theme.svelte.js';
	import Icon from '#lib/ui/Icon.svelte';
	import Tooltip from '#lib/ui/Tooltip.svelte';

	const icons = { light: 'sun', dark: 'moon', system: 'monitor' } as const;
	const labels: Record<ThemeChoice, () => string> = {
		light: m.theme_light,
		dark: m.theme_dark,
		system: m.theme_system
	};
</script>

<div class="st-seg st-seg--icons" role="radiogroup" aria-label={m.theme()}>
	{#each THEME_CHOICES as choice (choice)}
		<Tooltip text={labels[choice]()} below>
			<button
				type="button"
				role="radio"
				aria-checked={theme.choice === choice}
				aria-label={labels[choice]()}
				onclick={() => setTheme(choice)}
			>
				<Icon name={icons[choice]} size={14} />
			</button>
		</Tooltip>
	{/each}
</div>
