<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<!-- One slideshow and how its photos were chosen (D-106): day by day and scene by scene, each
     photo shown, each group of near copies beside the photo it gave way to, the photos over the
     share of the day, and apart the screenshots, documents and poor photos. -->
<script lang="ts">
	import {
		ApiError,
		getAlbumSlideshow,
		getSlideshowPlan,
		previewUrl,
		thumbnailUrl,
		type Slideshow,
		type SlideshowPlan,
		type TracedPhoto
	} from '#lib/api.js';
	import { errorMessage } from '#lib/errors.js';
	import { m } from '#lib/paraglide/messages.js';
	import { getLocale } from '#lib/paraglide/runtime.js';
	import Dialog from '#lib/ui/Dialog.svelte';
	import Icon from '#lib/ui/Icon.svelte';
	import { resolve } from '$app/paths';
	import { page } from '$app/state';

	const id = $derived(page.params.id ?? '');
	const year = $derived(Number(page.params.year));
	const part = $derived(Number(page.params.part));

	let plan = $state<SlideshowPlan | null>(null);
	let slideshow = $state<Slideshow | null>(null);
	let error = $state<string | null>(null);
	let missing = $state(false);
	let looking = $state<TracedPhoto | null>(null);

	async function load() {
		try {
			const [album, got] = await Promise.all([
				getAlbumSlideshow(id),
				getSlideshowPlan(id, year, part).catch((e: unknown) => {
					if (e instanceof ApiError && e.status === 404) return null;
					throw e;
				})
			]);
			slideshow = album.slideshows.find((s) => s.year === year && s.part === part) ?? null;
			plan = got;
			missing = got === null;
			error = null;
		} catch (e) {
			error = errorMessage(e);
		}
	}

	$effect(() => {
		if (id) load();
	});

	/** A run of the scene: one photo, or a group of near copies with the one it gave way to. */
	interface Run {
		key: string;
		photos: TracedPhoto[];
	}
	interface Scene {
		number: number;
		runs: Run[];
	}
	interface Day {
		date: string;
		photos: number;
		shown: number;
		scenes: Scene[];
		apart: TracedPhoto[];
	}

	const days = $derived.by((): Day[] => {
		if (!plan) return [];
		const result: Day[] = [];
		for (const photo of plan.photos) {
			const date = photo.taken.slice(0, 10);
			let day = result.at(-1);
			if (!day || day.date !== date) {
				day = { date, photos: 0, shown: 0, scenes: [], apart: [] };
				result.push(day);
			}
			day.photos += 1;
			if (photo.fate === 'shown') day.shown += 1;
			if (photo.fate === 'junk' || photo.fate === 'poor') {
				day.apart.push(photo);
				continue;
			}
			let scene = day.scenes.at(-1);
			if (!scene || scene.number !== photo.scene) {
				scene = { number: photo.scene, runs: [] };
				day.scenes.push(scene);
			}
			const run = photo.group ? scene.runs.find((r) => r.key === photo.group) : undefined;
			if (run) run.photos.push(photo);
			else scene.runs.push({ key: photo.group ?? photo.id, photos: [photo] });
		}
		// In a group, the photo it gave way to comes first.
		for (const day of result)
			for (const scene of day.scenes)
				for (const run of scene.runs)
					run.photos.sort((a, b) => Number(b.id === run.key) - Number(a.id === run.key));
		return result;
	});

	const counts = $derived.by(() => {
		const result: Record<string, number> = {};
		for (const photo of plan?.photos ?? []) result[photo.fate] = (result[photo.fate] ?? 0) + 1;
		return result;
	});

	const fateName = (fate: string) =>
		({
			shown: m.slideshow_plan_shown(),
			series: m.album_slideshow_reason_series(),
			scene: m.album_slideshow_reason_scene(),
			junk: m.album_slideshow_reason_junk(),
			poor: m.album_slideshow_reason_poor()
		})[fate] ?? fate;
	const dayName = (date: string) =>
		new Date(`${date}T12:00:00`).toLocaleDateString(getLocale(), {
			weekday: 'short',
			day: 'numeric',
			month: 'long',
			year: 'numeric'
		});
	const time = (taken: string) => taken.slice(11, 16);
	const duration = (seconds: number) =>
		`${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`;
</script>

<p class="back">
	<a href={resolve('/albums/[id]', { id })}
		><Icon name="arrow-left" size={14} /> {m.slideshow_plan_back()}</a
	>
</p>

{#if error}
	<div class="st-banner st-banner--danger" role="alert">
		<Icon name="circle-alert" /><span class="st-banner__body">{error}</span>
	</div>
{/if}

<h1>{plan?.title ?? slideshow?.title ?? ''}</h1>
{#if slideshow}
	<p class="meta">
		{m.album_slideshow_info({
			duration: duration(slideshow.seconds),
			photos: String(slideshow.photos),
			left_out: String(slideshow.left_out)
		})}
	</p>
	{#if slideshow.state !== 'drawn'}
		<p class="hint">{m.slideshow_plan_redrawing()}</p>
	{/if}
{/if}

{#if missing}
	<p class="hint">{m.slideshow_plan_none()}</p>
{:else if plan}
	<p class="intro">{m.slideshow_plan_intro()}</p>
	<ul class="legend">
		{#each ['shown', 'series', 'scene', 'junk', 'poor'] as fate (fate)}
			{#if counts[fate]}
				<li><span class="swatch {fate}"></span>{fateName(fate)}: {counts[fate]}</li>
			{/if}
		{/each}
	</ul>

	{#each days as day (day.date)}
		<details class="day" open={days.length <= 7}>
			<summary>
				<span class="date">{dayName(day.date)}</span>
				<span class="meta"
					>{m.slideshow_plan_day({ shown: String(day.shown), photos: String(day.photos) })}</span
				>
			</summary>
			{#each day.scenes as scene (scene.number)}
				<div class="scene">
					<div class="when">
						{time(scene.runs[0].photos[0].taken)}–{time(
							scene.runs.at(-1)?.photos.at(-1)?.taken ?? scene.runs[0].photos[0].taken
						)}
					</div>
					<div class="runs">
						{#each scene.runs as run (run.key)}
							<div class="run" class:group={run.photos.length > 1}>
								{#each run.photos as photo (photo.id)}
									<button
										type="button"
										class="tile {photo.fate}"
										title="{time(photo.taken)} · {fateName(photo.fate)}"
										onclick={() => (looking = photo)}
									>
										<img src={thumbnailUrl(photo.id)} alt="" loading="lazy" />
										{#if photo.fate === 'series'}
											<span class="tag">{m.slideshow_plan_copy()}</span>
										{:else if photo.fate === 'scene'}
											<span class="tag">{m.slideshow_plan_over()}</span>
										{/if}
									</button>
								{/each}
							</div>
						{/each}
					</div>
				</div>
			{/each}
			{#if day.apart.length}
				<details class="apart">
					<summary>{m.slideshow_plan_apart({ count: String(day.apart.length) })}</summary>
					<div class="runs">
						{#each day.apart as photo (photo.id)}
							<button
								type="button"
								class="tile {photo.fate}"
								title="{time(photo.taken)} · {fateName(photo.fate)}"
								onclick={() => (looking = photo)}
							>
								<img src={thumbnailUrl(photo.id)} alt="" loading="lazy" />
								<span class="tag">{fateName(photo.fate)}</span>
							</button>
						{/each}
					</div>
				</details>
			{/if}
		</details>
	{/each}
{:else if !error}
	<p>{m.status_loading()}</p>
{/if}

{#if looking}
	<Dialog
		title="{dayName(looking.taken.slice(0, 10))}, {time(looking.taken)}"
		wide
		onclose={() => (looking = null)}
	>
		<img class="large" src={previewUrl(looking.id)} alt="" />
		<p class="meta">
			{fateName(looking.fate)} · {m.slideshow_plan_score({ score: looking.score.toFixed(2) })}
		</p>
	</Dialog>
{/if}

<style>
	.back {
		margin: 0 0 var(--space-4);
	}
	.back a {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-text-muted);
		text-decoration: none;
	}
	h1 {
		margin: 0 0 var(--space-1);
	}
	.meta,
	.hint {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		margin: 0 0 var(--space-2);
	}
	.intro {
		max-width: 60rem;
	}
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
		list-style: none;
		padding: 0;
		margin: 0 0 var(--space-4);
		font-size: var(--text-sm);
	}
	.legend li {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
	}
	.swatch {
		width: 0.9rem;
		height: 0.9rem;
		border-radius: 3px;
		background: var(--color-surface-sunken);
		border: 2px solid var(--color-border);
	}
	.swatch.shown {
		border-color: var(--color-accent);
	}
	.swatch.series,
	.swatch.scene,
	.swatch.junk,
	.swatch.poor {
		opacity: 0.45;
	}
	.day {
		border-top: 1px solid var(--color-border);
		padding: var(--space-2) 0;
	}
	.day > summary {
		cursor: pointer;
		display: flex;
		gap: var(--space-3);
		align-items: baseline;
		flex-wrap: wrap;
	}
	.date {
		font-weight: 600;
	}
	.day > summary .meta {
		margin: 0;
	}
	.scene {
		display: flex;
		gap: var(--space-3);
		margin-top: var(--space-3);
	}
	.when {
		flex: 0 0 5.5rem;
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		font-variant-numeric: tabular-nums;
		padding-top: var(--space-1);
	}
	.runs {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		min-width: 0;
	}
	.run {
		display: flex;
		gap: 2px;
	}
	.run.group {
		padding: 3px;
		border-radius: var(--radius-sm, 6px);
		background: var(--color-surface-sunken);
	}
	.tile {
		position: relative;
		width: 96px;
		height: 72px;
		padding: 0;
		border: 2px solid transparent;
		border-radius: 4px;
		overflow: hidden;
		background: var(--color-surface-sunken);
		cursor: zoom-in;
	}
	.tile img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}
	.tile.shown {
		border-color: var(--color-accent);
	}
	.tile.series,
	.tile.scene,
	.tile.junk,
	.tile.poor,
	.tile.other {
		opacity: 0.45;
	}
	.tile:hover {
		opacity: 1;
	}
	.tag {
		position: absolute;
		left: 0;
		right: 0;
		bottom: 0;
		font-size: 10px;
		line-height: 1.4;
		color: #fff;
		background: rgb(0 0 0 / 0.6);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.apart {
		margin: var(--space-3) 0 0 calc(5.5rem + var(--space-3));
		font-size: var(--text-sm);
	}
	.apart summary {
		cursor: pointer;
		color: var(--color-text-muted);
		margin-bottom: var(--space-2);
	}
	.large {
		display: block;
		max-width: 100%;
		max-height: 70vh;
		margin: 0 auto var(--space-2);
	}
	@media (max-width: 40rem) {
		.scene {
			flex-direction: column;
			gap: var(--space-1);
		}
		.when {
			flex: none;
		}
		.apart {
			margin-left: 0;
		}
		.tile {
			width: 72px;
			height: 54px;
		}
	}
</style>
