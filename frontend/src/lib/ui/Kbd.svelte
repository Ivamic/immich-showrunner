<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- A key as drawn on a keyboard: 1–9, Enter, S, ←. -->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let { subtle = false, children }: { subtle?: boolean; children: Snippet } = $props();
</script>

<kbd class="st-kbd" class:st-kbd--subtle={subtle}>{@render children()}</kbd>
