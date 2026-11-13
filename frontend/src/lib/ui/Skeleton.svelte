<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- A gray block in place of content that is still loading. -->
<script lang="ts">
	let {
		width = '100%',
		height = '1rem',
		radius
	}: { width?: string; height?: string; radius?: string } = $props();
</script>

<span class="st-skel" style:width style:height style:border-radius={radius} aria-hidden="true"
></span>
