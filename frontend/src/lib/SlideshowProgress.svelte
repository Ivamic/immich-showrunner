<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- The slideshow being drawn now: which one, how far, and how many wait after it. With `show`,
     only while a slideshow of that album is drawn; `onchange` is called when the drawing moves
     on, so that the page can look again. -->
<script lang="ts">
	import { getSlideshowProgress, type SlideshowProgress } from '#lib/api.js';
	import { m } from '#lib/paraglide/messages.js';

	let { show, onchange }: { show?: string; onchange?: () => void } = $props();

	/** How often the page looks while a slideshow is drawn, and while none is. */
	const DRAWING_MS = 3000;
	const IDLE_MS = 15000;

	let progress = $state<SlideshowProgress | null>(null);
	let tick = $state(0);

	$effect(() => {
		void tick;
		let stopped = false;
		let timer: ReturnType<typeof setTimeout> | undefined;
		getSlideshowProgress()
			.catch(() => null)
			.then((got) => {
				if (stopped) return;
				const before = progress ? `${progress.album_id} ${progress.title}` : '';
				const now = got ? `${got.album_id} ${got.title}` : '';
				progress = got;
				if (before && before !== now) onchange?.();
				timer = setTimeout(() => tick++, got ? DRAWING_MS : IDLE_MS);
			});
		return () => {
			stopped = true;
			clearTimeout(timer);
		};
	});

	const shown = $derived(progress && (!show || progress.album_id === show) ? progress : null);
</script>

{#if shown}
	<div class="st-banner st-banner--info drawing" role="status">
		<div class="st-progress" class:st-progress--indeterminate={shown.percent === null}>
			<div class="st-progress__row">
				<span>
					{show
						? m.slideshow_drawing_album({ title: shown.title })
						: m.slideshow_drawing({ show: shown.show, title: shown.title })}
				</span>
				<span class="st-progress__value">
					{shown.percent === null ? m.slideshow_drawing_photos() : `${shown.percent}%`}
				</span>
			</div>
			<div class="st-progress__track">
				<div
					class="st-progress__bar"
					style:transform={shown.percent === null ? undefined : `scaleX(${shown.percent / 100})`}
				></div>
			</div>
			{#if shown.queue}
				<div class="st-progress__row">
					<span>{m.slideshow_drawing_queue({ count: String(shown.queue) })}</span>
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.drawing {
		display: block;
		max-width: 60rem;
		margin-bottom: var(--space-3);
	}
</style>
